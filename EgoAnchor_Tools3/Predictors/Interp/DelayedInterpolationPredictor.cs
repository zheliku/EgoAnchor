using System;
using System.Collections.Generic;
using EgoAnchor.Tools3.Core;
using EgoAnchor.Tools3.Data;
using EgoAnchor.Tools3.Sim;

namespace EgoAnchor.Tools3.Predictors.Interp
{
    /// <summary>样条类型。</summary>
    public enum SplineKind
    {
        Hermite,
        CentripetalCatmullRom,
    }

    /// <summary>
    /// 「延迟一周期 + 插值」预测器 (C 行)。
    ///
    /// 思路 (VR snapshot interpolation 标准做法): 主动牺牲约一个观测周期 Δ 的延迟, 把渲染时刻 t
    /// 的输出取在 **t − Δ** 处。因为 t − Δ 总是落在两个已经到达的控制点**之间**, 所以可以做
    /// **真正的插值** (而非外推): 既严格过点, 又能用样条保证 C¹/C² 连续。无需"猜未来"。
    ///
    /// 两层可插拔:
    ///   - 控制点来源 IControlPointSource: 原始 / 1€平滑 / Kalman平滑 (决定去不去噪、有无速度切线)
    ///   - 样条 SplineKind: Hermite (用速度切线) / 向心 Catmull-Rom (用相邻点自动定切线)
    ///
    /// 位置直接用样条; 旋转在"相对 P1 姿态的切空间向量"上用同一套样条, 再 Exp 回四元数,
    /// 与位置同构、无 gimbal lock。
    /// </summary>
    public sealed class DelayedInterpolationPredictor : IPredictor
    {
        private readonly IControlPointSource source;
        private readonly SplineKind spline;
        private readonly List<ControlPoint> points = new();
        private double delaySeconds = 0.25;       // 实际延迟 (实测采集-渲染延迟 × 安全系数)
        private double latencyEstimate;            // 实测 now - 最新控制点时间 的 EMA
        private const double LatencySafetyMargin = 1.15;
        private const double MinDelaySeconds = 0.25;
        // Hermite 切线模长上限 = 此倍数 × 控制点弦长 (Fritsch-Carlson 单调三次插值标准)。防运动急停时速度切线
        // 滞后 (Kalman 速度衰减不够快) 导致两个位置几乎重合的控制点之间挂着非零切线 → 样条鼓出再弹回 = 过冲振铃。
        // 停下时弦长≈0→切线≈0→不鼓包; 真实运动时弦长≈v·span≈切线 ≪ K·弦长→不裁剪、行为不变。与 Unity DelayedInterpStrategy 同步。
        private const double TangentChordRatio = 3.0;

        public DelayedInterpolationPredictor(IControlPointSource source, SplineKind spline)
        {
            this.source = source;
            this.spline = spline;
        }

        public string Label => spline == SplineKind.CentripetalCatmullRom
            ? $"{source.Name}_catmull"
            : $"{source.Name}_hermite";

        public bool HasEstimate => points.Count >= 2;

        public void Reset()
        {
            source.Reset();
            points.Clear();
            delaySeconds = MinDelaySeconds;
            latencyEstimate = 0.0;
        }

        public void OnObservation(in Observation observation)
        {
            ControlPoint cp = source.Accept(observation);
            points.Add(cp);

            // 控制点缓冲不需要太长, 保留最近若干个即可 (插值只用 t-Δ 附近的 2~4 个)
            if (points.Count > 64)
            {
                points.RemoveRange(0, points.Count - 64);
            }
        }

        public Pose PredictAt(double renderTimeSeconds)
        {
            if (points.Count == 0)
            {
                return Pose.Identity;
            }

            if (points.Count == 1)
            {
                return new Pose(points[0].Position, points[0].Rotation);
            }

            // 关键修复: 延迟 = 实测"采集-渲染延迟" (= now - 最新控制点时间), 不是观测周期。
            // 否则 target 比最新控制点还新 -> 退化成外推 -> 锯齿跳变 (真机表现)。
            double observedLatency = Math.Max(renderTimeSeconds - points[^1].Time, 0.0);
            double follow = observedLatency > latencyEstimate ? 0.5 : 0.05; // 快升慢降
            latencyEstimate += follow * (observedLatency - latencyEstimate);
            delaySeconds = Math.Max(latencyEstimate * LatencySafetyMargin, MinDelaySeconds);

            double target = renderTimeSeconds - delaySeconds;

            // target 早于最早控制点: 输出最早点 (启动阶段)
            if (target <= points[0].Time)
            {
                return new Pose(points[0].Position, points[0].Rotation);
            }

            // target 仍晚于最新控制点 (极端情况余量不足): 退化为外推最后一段, 但仍连续
            if (target >= points[^1].Time)
            {
                return new Pose(points[^1].Position, points[^1].Rotation);
            }

            // 找到 bracket: points[i].Time <= target < points[i+1].Time
            int i = FindBracket(target);
            ControlPoint p1 = points[i];
            ControlPoint p2 = points[i + 1];
            double span = Math.Max(p2.Time - p1.Time, 1e-6);
            double u = (target - p1.Time) / span;

            return spline == SplineKind.CentripetalCatmullRom
                ? InterpCatmull(i, u)
                : InterpHermite(p1, p2, u, span);
        }

        private int FindBracket(double target)
        {
            // 线性从尾部找 (target 通常靠近末尾), 控制点少, 足够快
            for (int i = points.Count - 2; i >= 0; i--)
            {
                if (points[i].Time <= target)
                {
                    return i;
                }
            }

            return 0;
        }

        private Pose InterpHermite(ControlPoint p1, ControlPoint p2, double u, double span)
        {
            // 速度切线: 自带就用自带; 否则用相邻点差分 (Catmull 式)
            Vec3 v1 = p1.LinVel;
            Vec3 v2 = p2.LinVel;
            Vec3 a1 = p1.AngVel;
            Vec3 a2 = p2.AngVel;
            if (!p1.HasVelocity || !p2.HasVelocity)
            {
                (v1, a1) = DiffVelocityAt(IndexOf(p1.Time));
                (v2, a2) = DiffVelocityAt(IndexOf(p2.Time));
            }

            // 切线限幅 (防急停过冲): 把速度切线模长限到 K × 弦长/span。弦长≈0 (停下) → 切线≈0 → 不鼓包;
            // 真实运动时弦长≈v·span → 切线≈弦长 ≪ K·弦长 → 不裁剪。位置/旋转通道各按自己的弦长独立限幅。
            double posCap = TangentChordRatio * (p2.Position - p1.Position).Magnitude / span;
            v1 = ClampMagnitude(v1, posCap);
            v2 = ClampMagnitude(v2, posCap);

            Vec3 pos = Spline.Hermite(p1.Position, v1, p2.Position, v2, u, span);

            // 旋转: 在 p1 切空间里对 (0 -> log(p1^-1 p2)) 做 Hermite, 切线用角速度 (同样按旋转弦长限幅)
            Quat r2Aligned = Quat.AlignHemisphere(p1.Rotation, p2.Rotation);
            Vec3 logEnd = Quat.Log(p1.Rotation.Inverse() * r2Aligned);
            double rotCap = TangentChordRatio * logEnd.Magnitude / span;
            a1 = ClampMagnitude(a1, rotCap);
            a2 = ClampMagnitude(a2, rotCap);
            Vec3 rotVec = Spline.Hermite(Vec3.Zero, a1, logEnd, a2, u, span);
            Quat rot = p1.Rotation * Quat.Exp(rotVec);
            return new Pose(pos, rot.Normalized());
        }

        /// <summary>把向量模长限到 maxMagnitude (≥0); maxMagnitude≈0 时归零 (急停弦长≈0 → 切线≈0, 杀过冲)。</summary>
        private static Vec3 ClampMagnitude(Vec3 v, double maxMagnitude)
        {
            double m = v.Magnitude;
            if (m <= maxMagnitude || m < 1e-9)
            {
                return v;
            }

            return v * (maxMagnitude / m);
        }

        private Pose InterpCatmull(int i, double u)
        {
            // 取 P0 P1 P2 P3 (边界用端点复制)
            ControlPoint p0 = points[Math.Max(i - 1, 0)];
            ControlPoint p1 = points[i];
            ControlPoint p2 = points[i + 1];
            ControlPoint p3 = points[Math.Min(i + 2, points.Count - 1)];

            Vec3 pos = Spline.CentripetalCatmullRom(p0.Position, p1.Position, p2.Position, p3.Position, u);

            // 旋转: 在 p1 切空间里把四个姿态映射成向量, 做向心 Catmull-Rom
            Vec3 l0 = LogRel(p1.Rotation, p0.Rotation);
            Vec3 l1 = Vec3.Zero; // p1 相对自己 = 0
            Vec3 l2 = LogRel(p1.Rotation, p2.Rotation);
            Vec3 l3 = LogRel(p1.Rotation, p3.Rotation);
            Vec3 rotVec = Spline.CentripetalCatmullRom(l0, l1, l2, l3, u);
            Quat rot = p1.Rotation * Quat.Exp(rotVec);
            return new Pose(pos, rot.Normalized());
        }

        private static Vec3 LogRel(Quat reference, Quat q)
        {
            Quat aligned = Quat.AlignHemisphere(reference, q);
            return Quat.Log(reference.Inverse() * aligned);
        }

        private int IndexOf(double time)
        {
            for (int k = 0; k < points.Count; k++)
            {
                if (Math.Abs(points[k].Time - time) < 1e-9)
                {
                    return k;
                }
            }

            return 0;
        }

        /// <summary>用相邻点中心差分估计第 k 个控制点处的速度/角速度 (供原始点 Hermite 用)。</summary>
        private (Vec3 lin, Vec3 ang) DiffVelocityAt(int k)
        {
            int a = Math.Max(k - 1, 0);
            int b = Math.Min(k + 1, points.Count - 1);
            double dt = points[b].Time - points[a].Time;
            if (dt < 1e-6)
            {
                return (Vec3.Zero, Vec3.Zero);
            }

            Vec3 lin = (points[b].Position - points[a].Position) / dt;
            Vec3 ang = LogRel(points[k].Rotation, points[b].Rotation) - LogRel(points[k].Rotation, points[a].Rotation);
            ang /= dt;
            return (lin, ang);
        }
    }
}

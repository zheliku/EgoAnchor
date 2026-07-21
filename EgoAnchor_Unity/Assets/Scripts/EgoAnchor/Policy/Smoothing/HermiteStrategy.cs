using System.Collections.Generic;
using System.Globalization;
using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>样条类型。</summary>
    public enum SplineKind
    {
        /// <summary>三次 Hermite (用控制点速度当切线)。</summary>
        Hermite,

        /// <summary>向心 Catmull-Rom (用相邻点自动定切线)。</summary>
        CentripetalCatmullRom,
    }

    /// <summary>
    /// C 路平滑策略：延迟一周期 + 插值。主动牺牲约一个观测周期 Δ 的延迟。
    ///
    /// 把渲染时刻 now 的输出取在 now-Δ 处。因为 now-Δ 总落在两个已到达控制点**之间**，
    /// 所以做的是**真正的插值** (而非外推)：既严格过点，又能用样条保证 C¹ 连续，无需"猜未来"、无 overshoot。
    ///
    /// 控制点来自任意 MotionModel.LatestControlPoint (CV=原始点 / Kalman / OneEuro=去噪点)，
    /// 与运动模型自由组合。位置用样条；旋转在相对 P1 姿态的切空间向量上用同一套样条再 Exp 回。
    /// </summary>
    public sealed class HermiteStrategy : SmoothingStrategy
    {
        /// <summary>
        /// 延迟安全系数 × 实测"采集→渲染延迟" = 实际延迟。
        /// 关键修复：延迟必须覆盖真实的采集-渲染延迟 (推理+传输+陈旧，实测可达 ~350ms)，
        /// 否则插值目标 now-Δ 会落在最新控制点之后，退化成外推 → 锯齿跳变。
        /// 1.15 = 留 15% 余量，保证目标稳稳落在两个已知点之间。
        /// </summary>
        [Tooltip("延迟安全系数 × 实测采集-渲染延迟 = 实际延迟。必须 >1 以保证插值不退化为外推 (那会锯齿跳变)。越大越平滑但延迟越久。默认 1.15。")]
        [Range(1.0f, 2.0f)]
        [SerializeField] private float latencySafetyMargin = 1.15f;

        /// <summary>手动延迟下限，单位秒。实测延迟不足时兜底，确保至少这么多延迟。</summary>
        [Tooltip("手动延迟下限 (秒)。实测延迟估计未稳定前的兜底；也可调大强制更稳。默认 0.25。")]
        [Range(0.0f, 0.6f)]
        [SerializeField] private float minDelaySeconds = 0.25f;

        /// <summary>样条类型：Hermite (用速度切线) 或向心 Catmull-Rom (用相邻点)。</summary>
        [Tooltip("样条类型。Hermite 用控制点速度当切线 (配 Kalman/OneEuro 更稳)；向心 Catmull-Rom 用相邻点自动定切线 (配原始点更直观)。默认 Hermite。")]
        [SerializeField] private SplineKind spline = SplineKind.Hermite;

        /// <summary>
        /// Hermite 切线模长上限 = 此倍数 × 两控制点弦长，默认 3。
        /// 这是项目使用的弦长归一化限幅，并非完整的分量单调三次插值约束。
        /// 物体急停时两控制点位置几乎重合 (弦长≈0) 但 Kalman 速度估计滞后仍非零 → Hermite 切线挂在重合点上
        /// 鼓出再弹回 = 过冲振铃 (用户报告"运动停下后 anchor 来回轻微震荡")。把切线限到弦长的 K 倍:
        /// 停下时弦长≈0 → 切线≈0 → 不鼓包; 真实运动时弦长≈v·span≈切线 << K·弦长 → 不裁剪、行为不变。
        /// 越小越不易过冲但运动中越"直" (插值偏向折线); K≥1 才保证过点处不反向。
        /// </summary>
        [Tooltip("Hermite 切线模长上限 = 此倍数 × 控制点弦长。防运动急停时速度切线滞后导致的过冲振铃 (停下时弦长≈0→切线被压到≈0)；真实运动时切线≈弦长远低于上限故不受影响。越小越不易过冲但运动中插值越直。默认 3。")]
        [Range(1.0f, 8.0f)]
        [SerializeField] private float hermiteTangentChordRatio = 3.0f;

        private readonly List<ControlPoint> points = new List<ControlPoint>(64);
        private float delaySeconds = 0.25f;
        private float latencyEstimateSeconds; // 实测 now - 最新控制点时间的 EMA
        private double lastOutputTimeSeconds; // 上次输出时间，用于限制延迟变化率
        private const float MaxDelayChangePerSecond = 0.05f; // 延迟变化率限制: 最多每秒变化50ms，防突变

        public override string StrategyName =>
            spline == SplineKind.CentripetalCatmullRom ? "catmull" : "hermite";
        public override string ConfigurationFingerprint => string.Format(
            CultureInfo.InvariantCulture,
            "margin:{0:R}|min:{1:R}|spline:{2}|tangent:{3:R}",
            latencySafetyMargin,
            minDelaySeconds,
            spline,
            hermiteTangentChordRatio);

        public override float NominalLatencySeconds => delaySeconds;

        public override void ResetStrategy()
        {
            points.Clear();
            delaySeconds = Mathf.Max(minDelaySeconds, 0.05f);
            latencyEstimateSeconds = 0.0f;
            lastOutputTimeSeconds = 0.0;
            OutputTargetTimeSeconds = double.NaN;
        }

        public override void OnObservation(MotionModel model, in AnchorObservation observation)
        {
            ControlPoint cp = model.LatestControlPoint;
            if (!cp.Valid)
            {
                return;
            }

            points.Add(cp);
            if (points.Count > 64)
            {
                points.RemoveRange(0, points.Count - 64);
            }
        }

        public override Pose Output(MotionModel model, double nowSeconds)
        {
            double previousOutputTime = lastOutputTimeSeconds;
            lastOutputTimeSeconds = nowSeconds;
            if (points.Count == 0)
            {
                OutputTargetTimeSeconds = nowSeconds;
                return model.PredictAt(nowSeconds);
            }

            if (points.Count == 1)
            {
                OutputTargetTimeSeconds = points[0].TimeSeconds;
                return points[0].Pose;
            }

            // 实测采集-渲染延迟 = now - 最新控制点时间。用 EMA 跟踪其峰值水平，
            // 延迟设为它的安全倍数，保证插值目标稳稳落在已知点之间。
            float observedLatency = Mathf.Max((float)(nowSeconds - points[points.Count - 1].TimeSeconds), 0.0f);
            // 偏向跟随较大值 (快升慢降)，避免延迟不足导致外推
            latencyEstimateSeconds = AnchorMath.UpdateAsymmetricEma(latencyEstimateSeconds, observedLatency);

            // 计算目标延迟，但限制变化速率防止突变影响用户体验
            float targetDelay = Mathf.Max(latencyEstimateSeconds * Mathf.Clamp(latencySafetyMargin, 1.0f, 2.0f), minDelaySeconds);
            float maxDelta = MaxDelayChangePerSecond * Mathf.Max((float)(nowSeconds - previousOutputTime), 0.0f);
            delaySeconds = Mathf.MoveTowards(delaySeconds, targetDelay, maxDelta);

            double target = nowSeconds - delaySeconds;

            // 启动阶段：target 早于最早控制点 -> 输出最早点
            if (target <= points[0].TimeSeconds)
            {
                OutputTargetTimeSeconds = points[0].TimeSeconds;
                return points[0].Pose;
            }

            // target 仍晚于最新控制点 (延迟余量不够极端情况)：退化为最后一段外推，仍连续
            if (target >= points[points.Count - 1].TimeSeconds)
            {
                OutputTargetTimeSeconds = target;
                ControlPoint last = points[points.Count - 1];
                float ahead = (float)(target - last.TimeSeconds);
                return AnchorMath.Integrate(last.Pose, last.LinearVelocity, last.AngularVelocityRad, ahead);
            }

            int i = FindBracket(target);
            ControlPoint p1 = points[i];
            ControlPoint p2 = points[i + 1];
            float span = Mathf.Max((float)(p2.TimeSeconds - p1.TimeSeconds), 1e-6f);
            float u = Mathf.Clamp01((float)(target - p1.TimeSeconds) / span);

            OutputTargetTimeSeconds = target;
            return spline == SplineKind.CentripetalCatmullRom
                ? InterpCatmull(i, u)
                : InterpHermite(p1, p2, u, span);
        }

        private int FindBracket(double target)
        {
            for (int i = points.Count - 2; i >= 0; i--)
            {
                if (points[i].TimeSeconds <= target)
                {
                    return i;
                }
            }

            return 0;
        }

        private Pose InterpHermite(ControlPoint p1, ControlPoint p2, float u, float span)
        {
            // 切线限幅 (防急停过冲): 把端点速度切线的模长限到 K × 弦长/span。弦长≈0 (停下) → 切线≈0 → 不鼓包;
            // 真实运动时弦长≈v·span → 切线≈弦长 << K·弦长 → 不裁剪。位置与旋转通道各按自己的弦长独立限幅。
            float k = Mathf.Max(hermiteTangentChordRatio, 1.0f);

            Vector3 posChord = p2.Pose.position - p1.Pose.position;
            float posCap = k * posChord.magnitude / span; // 速度上限 (m/s); span>0 由调用方保证
            Vector3 v1 = ClampMagnitude(p1.LinearVelocity, posCap);
            Vector3 v2 = ClampMagnitude(p2.LinearVelocity, posCap);
            Vector3 pos = Spline.Hermite(p1.Pose.position, v1, p2.Pose.position, v2, u, span);

            // 旋转：在 p1 切空间里对 (0 -> log(p1^-1 p2)) 做 Hermite，切线用角速度 (同样按旋转弦长限幅)
            Quaternion alignedP2 = AnchorMath.AlignHemisphere(p1.Pose.rotation, p2.Pose.rotation);
            Quaternion p1ToP2 = AnchorMath.Multiply(
                AnchorMath.Inverse(p1.Pose.rotation),
                alignedP2);
            Vector3 logEnd = AnchorMath.Log(p1ToP2);
            float rotCap = k * logEnd.magnitude / span; // 角速度上限 (rad/s)
            Vector3 w1 = ClampMagnitude(p1.AngularVelocityRad, rotCap);
            // 控制点存的是 body-local 角速度，而 Hermite 插值变量是 Log(p1^-1*p)。
            // 在 p2 端必须用 SO(3) 右雅可比逆换成 Log 向量导数，不能直接混用两者。
            Vector3 w2LogRate = AnchorMath.ApplyRightJacobianInverse(logEnd, p2.AngularVelocityRad);
            Vector3 w2 = ClampMagnitude(w2LogRate, rotCap);
            Vector3 rotVec = Spline.Hermite(Vector3.zero, w1, logEnd, w2, u, span);
            Quaternion rot = AnchorMath.Multiply(p1.Pose.rotation, AnchorMath.Exp(rotVec));
            return new Pose(pos, rot);
        }

        /// <summary>把向量模长限到 maxMagnitude (≥0)；maxMagnitude≈0 时归零 (急停弦长≈0 → 切线≈0, 杀过冲)。</summary>
        private static Vector3 ClampMagnitude(Vector3 v, float maxMagnitude)
        {
            float m = v.magnitude;
            if (m <= maxMagnitude || m < 1e-9f)
            {
                return v;
            }

            return v * (maxMagnitude / m);
        }

        private Pose InterpCatmull(int i, float u)
        {
            ControlPoint p0 = points[Mathf.Max(i - 1, 0)];
            ControlPoint p1 = points[i];
            ControlPoint p2 = points[i + 1];
            ControlPoint p3 = points[Mathf.Min(i + 2, points.Count - 1)];

            Vector3 pos = Spline.CentripetalCatmullRom(p0.Pose.position, p1.Pose.position, p2.Pose.position, p3.Pose.position, u);

            Vector3 l0 = AnchorMath.RelativeRotationLog(p1.Pose.rotation, p0.Pose.rotation);
            Vector3 l1 = Vector3.zero;
            Vector3 l2 = AnchorMath.RelativeRotationLog(p1.Pose.rotation, p2.Pose.rotation);
            Vector3 l3 = AnchorMath.RelativeRotationLog(p1.Pose.rotation, p3.Pose.rotation);
            Vector3 rotVec = Spline.CentripetalCatmullRom(l0, l1, l2, l3, u);
            Quaternion rot = AnchorMath.Multiply(p1.Pose.rotation, AnchorMath.Exp(rotVec));
            return new Pose(pos, rot);
        }
    }
}

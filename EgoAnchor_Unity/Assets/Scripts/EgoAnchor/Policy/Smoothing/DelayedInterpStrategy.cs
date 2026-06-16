using System.Collections.Generic;
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
    public sealed class DelayedInterpStrategy : SmoothingStrategy
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

        private readonly List<ControlPoint> points = new List<ControlPoint>(64);
        private float delaySeconds = 0.25f;
        private float latencyEstimateSeconds; // 实测 now - 最新控制点时间 的 EMA

        public override string StrategyName => spline == SplineKind.CentripetalCatmullRom ? "interp_catmull" : "interp_hermite";

        public override float NominalLatencySeconds => delaySeconds;

        public override void ResetStrategy()
        {
            points.Clear();
            delaySeconds = Mathf.Max(minDelaySeconds, 0.05f);
            latencyEstimateSeconds = 0.0f;
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
            if (points.Count == 0)
            {
                return model.PredictAt(nowSeconds);
            }

            if (points.Count == 1)
            {
                return points[0].Pose;
            }

            // 实测采集-渲染延迟 = now - 最新控制点时间。用 EMA 跟踪其峰值水平，
            // 延迟设为它的安全倍数，保证插值目标稳稳落在已知点之间。
            float observedLatency = Mathf.Max((float)(nowSeconds - points[points.Count - 1].TimeSeconds), 0.0f);
            // 偏向跟随较大值 (快升慢降)，避免延迟不足导致外推
            latencyEstimateSeconds = AnchorMath.UpdateAsymmetricEma(latencyEstimateSeconds, observedLatency);
            delaySeconds = Mathf.Max(latencyEstimateSeconds * Mathf.Clamp(latencySafetyMargin, 1.0f, 2.0f), minDelaySeconds);

            double target = nowSeconds - delaySeconds;

            // 启动阶段：target 早于最早控制点 -> 输出最早点
            if (target <= points[0].TimeSeconds)
            {
                return points[0].Pose;
            }

            // target 仍晚于最新控制点 (延迟余量不够极端情况)：退化为最后一段外推，仍连续
            if (target >= points[points.Count - 1].TimeSeconds)
            {
                ControlPoint last = points[points.Count - 1];
                float ahead = (float)(target - last.TimeSeconds);
                return AnchorMath.Integrate(last.Pose, last.LinearVelocity, last.AngularVelocityRad, ahead);
            }

            int i = FindBracket(target);
            ControlPoint p1 = points[i];
            ControlPoint p2 = points[i + 1];
            float span = Mathf.Max((float)(p2.TimeSeconds - p1.TimeSeconds), 1e-6f);
            float u = Mathf.Clamp01((float)(target - p1.TimeSeconds) / span);

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
            Vector3 pos = Spline.Hermite(p1.Pose.position, p1.LinearVelocity, p2.Pose.position, p2.LinearVelocity, u, span);

            // 旋转：在 p1 切空间里对 (0 -> log(p1^-1 p2)) 做 Hermite，切线用角速度
            Vector3 logEnd = AnchorMath.RelativeRotationLog(p1.Pose.rotation, p2.Pose.rotation);
            Vector3 rotVec = Spline.Hermite(Vector3.zero, p1.AngularVelocityRad, logEnd, p2.AngularVelocityRad, u, span);
            Quaternion rot = AnchorMath.Multiply(p1.Pose.rotation, AnchorMath.Exp(rotVec));
            return new Pose(pos, rot);
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

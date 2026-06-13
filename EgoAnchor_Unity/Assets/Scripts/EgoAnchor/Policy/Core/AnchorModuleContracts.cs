using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// GateModule 对一帧测量的处理动作。
    /// </summary>
    public enum GateAction
    {
        /// <summary>接受测量，交给 estimator 正常更新。</summary>
        Accept,

        /// <summary>贴合测量，通常用于首帧或重定位。</summary>
        Snap,

        /// <summary>保持当前估计，不更新 estimator。</summary>
        Hold,

        /// <summary>拒绝测量，不更新 estimator，并把原因写入诊断。</summary>
        Reject,
    }

    /// <summary>
     /// EstimatorModule 在指定时间点预测得到的 anchor 状态。
     /// 该结构只描述 Unity world 坐标下的估计结果，不持有滤波器内部协方差。
    /// </summary>
    public readonly struct AnchorEstimate
    {
        /// <summary>预测得到的 Unity world pose。</summary>
        public readonly Pose Pose;

        /// <summary>预测时刻的线速度，单位米/秒。</summary>
        public readonly Vector3 LinearVelocity;

        /// <summary>预测时刻的角速度，单位 rad/s。</summary>
        public readonly Vector3 AngularVelocityRad;

        /// <summary>该估计对应的时间，单位秒。</summary>
        public readonly double TimeSeconds;

        /// <summary>估计器内部置信度，范围 0..1；普通 baseline 可固定为 1。</summary>
        public readonly float Confidence;

        /// <summary>最近一次进入估计器的感知可靠性分数，范围 0..1。</summary>
        public readonly float ReliabilityScore;

        /// <summary>本次估计实际使用的前推时长，单位秒；已包含 estimator 内部安全上限。</summary>
        public readonly float PredictAheadSeconds;

        /// <summary>
        /// 构造 anchor 估计快照。
        /// </summary>
        public AnchorEstimate(
            Pose pose,
            Vector3 linearVelocity,
            Vector3 angularVelocityRad,
            double timeSeconds,
            float confidence = 1.0f,
            float reliabilityScore = 1.0f,
            float predictAheadSeconds = 0.0f)
        {
            Pose = pose;
            LinearVelocity = linearVelocity;
            AngularVelocityRad = angularVelocityRad;
            TimeSeconds = timeSeconds;
            Confidence = Mathf.Clamp01(confidence);
            ReliabilityScore = Mathf.Clamp01(reliabilityScore);
            PredictAheadSeconds = Mathf.Max(predictAheadSeconds, 0.0f);
        }

        /// <summary>
        /// 构造无速度的一帧估计。
        /// </summary>
        public static AnchorEstimate Stationary(Pose pose, double timeSeconds, float reliabilityScore = 1.0f)
        {
            return new AnchorEstimate(pose, Vector3.zero, Vector3.zero, timeSeconds, 1.0f, reliabilityScore);
        }
    }

    /// <summary>
    /// GateModule 的稳定决策结果。
    /// </summary>
    public readonly struct GateDecision
    {
        /// <summary>本帧门控动作。</summary>
        public readonly GateAction Action;

        /// <summary>稳定原因字符串，供日志、eval 和论文统计使用。</summary>
        public readonly string Reason;

        /// <summary>
        /// 构造门控决策。
        /// </summary>
        public GateDecision(GateAction action, string reason)
        {
            Action = action;
            Reason = reason ?? string.Empty;
        }

        /// <summary>构造 Accept 决策。</summary>
        public static GateDecision Accept(string reason) => new GateDecision(GateAction.Accept, reason);

        /// <summary>构造 Snap 决策。</summary>
        public static GateDecision Snap(string reason) => new GateDecision(GateAction.Snap, reason);

        /// <summary>构造 Hold 决策。</summary>
        public static GateDecision Hold(string reason) => new GateDecision(GateAction.Hold, reason);

        /// <summary>构造 Reject 决策。</summary>
        public static GateDecision Reject(string reason) => new GateDecision(GateAction.Reject, reason);

        /// <summary>
        /// 将 gate 动作映射到现有 policy action 枚举。
        /// </summary>
        public AnchorPolicyAction ToPolicyAction()
        {
            switch (Action)
            {
                case GateAction.Accept:
                    return AnchorPolicyAction.Accept;
                case GateAction.Snap:
                    return AnchorPolicyAction.Snap;
                case GateAction.Reject:
                    return AnchorPolicyAction.Reject;
                default:
                    return AnchorPolicyAction.Hold;
            }
        }
    }

    /// <summary>
    /// OutputStageModule 对 estimator 输出做显示整形时需要的 runtime 上下文。
    /// </summary>
    public readonly struct OutputContext
    {
        /// <summary>最近一次被接受测量的 sample 时间，单位秒。</summary>
        public readonly double LastAcceptedTimeSeconds;

        /// <summary>当前渲染时间距最近一次接受测量的间隔，单位秒。</summary>
        public readonly double GapSeconds;

        /// <summary>最近一次被接受测量的可靠性分数。</summary>
        public readonly float LastScore;

        /// <summary>当前 anchor 生命周期状态。</summary>
        public readonly AnchorState State;

        /// <summary>当前运动状态。</summary>
        public readonly AnchorMotionState MotionState;

        /// <summary>
        /// 构造输出整形上下文。
        /// </summary>
        public OutputContext(
            double lastAcceptedTimeSeconds,
            double gapSeconds,
            float lastScore,
            AnchorState state,
            AnchorMotionState motionState)
        {
            LastAcceptedTimeSeconds = lastAcceptedTimeSeconds;
            GapSeconds = gapSeconds;
            LastScore = lastScore;
            State = state;
            MotionState = motionState;
        }
    }
}

namespace EgoAnchor.Policy
{
    /// <summary>
    /// 内联 score/jump 门控对一帧测量的处理动作。
    /// </summary>
    public enum GateAction
    {
        /// <summary>接受测量，交给运动模型正常更新。</summary>
        Accept,

        /// <summary>贴合测量，通常用于首帧或重定位。</summary>
        Snap,

        /// <summary>保持当前估计，不更新运动模型。</summary>
        Hold,

        /// <summary>拒绝测量，不更新运动模型，并把原因写入诊断。</summary>
        Reject,
    }

    /// <summary>
    /// 内联门控的稳定决策结果。
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
}

namespace EgoAnchor.Policy
{
    /// <summary>
    /// anchor policy 对单帧观测的决策类型。
    /// </summary>
    public enum AnchorPolicyAction
    {
        /// <summary>接受本帧测量，滤波器正常校正。</summary>
        Accept,

        /// <summary>拒绝本帧测量（低分或跳变超阈）。</summary>
        Reject,

        /// <summary>本帧无测量且处于短时续航窗口内。</summary>
        Coast,

        /// <summary>保持上一输出，不更新滤波器。</summary>
        Hold,

        /// <summary>贴合接受：滤波器硬重置到本帧测量（首测量、重定位、瞬移恢复）。</summary>
        Snap,
    }

    /// <summary>
    /// anchor policy 对单帧观测的输入分类结果。
    ///
    /// 自统一滤波重构后，决策不再携带输出 pose：渲染输出统一由每帧
    /// PolicyController.Advance 返回的 AnchorPolicyOutput 提供，
    /// 本结构只用于诊断、日志与离线 policy 分布统计。
    /// </summary>
    public readonly struct AnchorPolicyDecision
    {
        /// <summary>本次策略动作。</summary>
        public readonly AnchorPolicyAction Action;

        /// <summary>决策后的 anchor 状态。</summary>
        public readonly AnchorState State;

        /// <summary>本次决策原因。</summary>
        public readonly string Reason;

        /// <summary>
        /// 构造 anchor policy 决策结果。
        /// </summary>
        /// <param name="action">本次策略动作。</param>
        /// <param name="state">决策后的 anchor 状态。</param>
        /// <param name="reason">本次决策原因。</param>
        public AnchorPolicyDecision(AnchorPolicyAction action, AnchorState state, string reason)
        {
            Action = action;
            State = state;
            Reason = reason ?? string.Empty;
        }
    }
}

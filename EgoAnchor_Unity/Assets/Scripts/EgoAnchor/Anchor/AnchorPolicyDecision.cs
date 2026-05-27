using UnityEngine;

namespace EgoAnchor.Anchor
{
    /// <summary>
    /// anchor policy 对单帧观测的决策类型。
    /// </summary>
    public enum AnchorPolicyAction
    {
        /// <summary>接受本帧 pose，并更新 raw/stable anchor。</summary>
        Accept,

        /// <summary>拒绝本帧 pose，并保持上一 stable anchor。</summary>
        Reject,

        /// <summary>短时缺失 pose，用预测或上一 stable anchor 续航。</summary>
        Coast,

        /// <summary>保持上一 stable anchor，不进行外推。</summary>
        Hold,

        /// <summary>清空本地状态或等待重新搜索。</summary>
        Reset,
    }

    /// <summary>
    /// anchor policy 单次决策结果。
    /// </summary>
    public readonly struct AnchorPolicyDecision
    {
        /// <summary>本次策略动作。</summary>
        public readonly AnchorPolicyAction Action;

        /// <summary>决策后的 anchor 状态。</summary>
        public readonly AnchorState State;

        /// <summary>是否有可输出的 stable pose。</summary>
        public readonly bool HasOutputPose;

        /// <summary>输出 stable pose；HasOutputPose=false 时为 Pose.identity。</summary>
        public readonly Pose OutputPose;

        /// <summary>本次决策原因。</summary>
        public readonly string Reason;

        /// <summary>
        /// 构造 anchor policy 决策结果。
        /// </summary>
        /// <param name="action">本次策略动作。</param>
        /// <param name="state">决策后的 anchor 状态。</param>
        /// <param name="hasOutputPose">是否有可输出的 stable pose。</param>
        /// <param name="outputPose">输出 stable pose。</param>
        /// <param name="reason">本次决策原因。</param>
        public AnchorPolicyDecision(AnchorPolicyAction action, AnchorState state, bool hasOutputPose, Pose outputPose, string reason)
        {
            Action = action;
            State = state;
            HasOutputPose = hasOutputPose;
            OutputPose = outputPose;
            Reason = reason ?? string.Empty;
        }
    }
}

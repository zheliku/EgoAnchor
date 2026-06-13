namespace EgoAnchor.Policy
{
    /// <summary>
    /// 不使用可靠性分数的最小门控模块。
    /// 它只区分无 pose、对齐失败、首帧、重定位和普通接受，用于公平 baseline。
    /// </summary>
    public sealed class NullGateModule : AnchorGateModule
    {
        /// <summary>日志和 eval 使用的模块名。</summary>
        public override string ModuleName => "null_gate";

        /// <summary>
        /// 根据 pose 有效性做最小门控，不读取 ReliabilityScore。
        /// </summary>
        public override GateDecision Evaluate(in AnchorObservation observation, in AnchorEstimate predicted, bool hasEstimate)
        {
            if (!observation.HasAlignedPose && !observation.HasServerPose)
            {
                return GateDecision.Hold("no_pose");
            }

            if (!observation.HasAlignedPose && observation.HasServerPose)
            {
                return GateDecision.Hold("align_failed");
            }

            if (!hasEstimate && observation.HasAlignedPose)
            {
                return GateDecision.Snap("first_accept");
            }

            if (observation.IsRelocalization && observation.HasAlignedPose)
            {
                return GateDecision.Snap("relocalize_accept");
            }

            return GateDecision.Accept("score_accept");
        }

        /// <summary>本模块无内部状态。</summary>
        public override void ResetModule()
        {
        }
    }
}

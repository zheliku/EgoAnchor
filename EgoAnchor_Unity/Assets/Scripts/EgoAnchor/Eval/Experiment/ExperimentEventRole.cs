namespace EgoAnchor.Eval.Experiment
{
    /// <summary>人工事件在实验协议中的稳定角色标识，供采集状态机和离线指标共同使用。</summary>
    public static class ExperimentEventRole
    {
        /// <summary>尚未标记人工事件。</summary>
        public const string None = "";

        /// <summary>起停或状态转换开始，用于计算响应、解锁和重新锁定。</summary>
        public const string TransitionStarted = "transition_started";

        /// <summary>遮挡开始，用于确定遮挡可用性统计窗口的左边界。</summary>
        public const string OcclusionStarted = "occlusion_started";

        /// <summary>目标重新可见，用于确定恢复时延的起点。</summary>
        public const string TargetVisible = "target_visible";

        /// <summary>不需要专用时序语义的通用人工标记。</summary>
        public const string GenericMarker = "generic_marker";

        /// <summary>根据场景协议解析事件标记动作应写入的主角色。</summary>
        public static string ResolvePrimary(string scenarioId)
        {
            switch (scenarioId)
            {
                case "start_stop_6dof":
                    return TransitionStarted;
                case "occlusion_recovery":
                    return OcclusionStarted;
                default:
                    return GenericMarker;
            }
        }

        /// <summary>判断当前场景是否使用“遮挡开始到目标重新可见”的双角色协议。</summary>
        public static bool SupportsTargetVisible(string scenarioId)
        {
            return scenarioId == "occlusion_recovery";
        }
    }
}

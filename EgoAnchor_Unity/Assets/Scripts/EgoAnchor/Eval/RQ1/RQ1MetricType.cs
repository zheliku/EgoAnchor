namespace EgoAnchor.Eval.RQ1
{
    /// <summary>
    /// RQ1 评估场景类型枚举，对齐论文当前的静态锚定质量实验结构。
    /// <para>
    /// RQ1 只评估静止场景，共两种：<br/>
    /// 1. 长时静止观察：控制器静置桌面，用户正常头部运动<br/>
    /// 2. 遮挡恢复：用户手部遮挡目标后移开<br/>
    /// 慢速平移 / 快速挥动 / 旋转已移交 RQ2，不在 RQ1 采集。
    /// </para>
    /// </summary>
    public enum RQ1MetricType
    {
        /// <summary>无标记。</summary>
        None = 0,

        /// <summary>长时静止观察：控制器静置桌面，用户正常头部运动。</summary>
        StaticObservation = 1,

        /// <summary>遮挡恢复：揭示目标时开始单次标记，恢复稳定后结束标记。</summary>
        OcclusionRecovery = 2
    }

    /// <summary>
    /// RQ1MetricType 扩展方法。
    /// </summary>
    public static class RQ1MetricTypeExtensions
    {
        /// <summary>转换为日志字段字符串（snake_case），与 Python 侧场景标签一致。</summary>
        public static string ToLogString(this RQ1MetricType type)
        {
            return type switch
            {
                RQ1MetricType.StaticObservation => "static_observation",
                RQ1MetricType.OcclusionRecovery => "occlusion_recovery",
                _ => "none"
            };
        }

        /// <summary>获取建议时长（秒）；遮挡恢复为单次事件返回 0。</summary>
        public static int GetSuggestedDuration(this RQ1MetricType type)
        {
            return type switch
            {
                RQ1MetricType.StaticObservation => 80,
                RQ1MetricType.OcclusionRecovery => 0,
                _ => 0
            };
        }

        /// <summary>获取显示名称。</summary>
        public static string GetDisplayName(this RQ1MetricType type)
        {
            return type switch
            {
                RQ1MetricType.StaticObservation => "Static",
                RQ1MetricType.OcclusionRecovery => "Occlusion",
                _ => "None"
            };
        }

        /// <summary>获取描述信息。</summary>
        public static string GetDescription(this RQ1MetricType type)
        {
            return type switch
            {
                RQ1MetricType.StaticObservation => "Static on table, normal head movement",
                RQ1MetricType.OcclusionRecovery => "Reveal target, then mark one recovery event",
                _ => ""
            };
        }
    }
}

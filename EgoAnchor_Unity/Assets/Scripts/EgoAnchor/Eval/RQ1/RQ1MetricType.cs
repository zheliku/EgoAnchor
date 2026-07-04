namespace EgoAnchor.Eval.RQ1
{
    /// <summary>
    /// RQ1 评估指标类型枚举（对齐论文 egoanchor_cn_v4.typ RQ1 实验条件）。
    /// <para>
    /// RQ1 评估五种运动模式：<br/>
    /// 1. 长时静止（60s）：物体静置桌面，用户头部正常活动<br/>
    /// 2. 慢速平移（20s）：5-10 cm/s 水平移动<br/>
    /// 3. 快速挥动（20s）：50+ cm/s 快速运动<br/>
    /// 4. 旋转运动（20s）：绕多个轴旋转<br/>
    /// 5. 遮挡恢复（重复10次）：短暂遮挡后恢复
    /// </para>
    /// </summary>
    public enum RQ1MetricType
    {
        /// <summary>无标记。</summary>
        None = 0,

        /// <summary>长时静止（60s）：物体静置桌面，用户头部正常活动。</summary>
        StaticObservation = 1,

        /// <summary>慢速平移（20s）：5-10 cm/s 水平移动。</summary>
        SlowTranslation = 2,

        /// <summary>快速挥动（20s）：50+ cm/s 快速运动。</summary>
        FastMotion = 3,

        /// <summary>旋转运动（20s）：绕多个轴旋转。</summary>
        Rotation = 4,

        /// <summary>遮挡恢复（重复10次）：短暂遮挡后恢复。</summary>
        OcclusionRecovery = 5
    }

    /// <summary>
    /// RQ1MetricType 扩展方法。
    /// </summary>
    public static class RQ1MetricTypeExtensions
    {
        /// <summary>转换为日志字段字符串（snake_case）。</summary>
        public static string ToLogString(this RQ1MetricType type)
        {
            return type switch
            {
                RQ1MetricType.StaticObservation => "static_observation",
                RQ1MetricType.SlowTranslation => "slow_translation",
                RQ1MetricType.FastMotion => "fast_motion",
                RQ1MetricType.Rotation => "rotation",
                RQ1MetricType.OcclusionRecovery => "occlusion_recovery",
                _ => "none"
            };
        }

        /// <summary>获取建议时长（秒）。</summary>
        public static int GetSuggestedDuration(this RQ1MetricType type)
        {
            return type switch
            {
                RQ1MetricType.StaticObservation => 60,
                RQ1MetricType.SlowTranslation => 20,
                RQ1MetricType.FastMotion => 20,
                RQ1MetricType.Rotation => 20,
                RQ1MetricType.OcclusionRecovery => 0,  // 单次事件
                _ => 0
            };
        }

        /// <summary>获取显示名称。</summary>
        public static string GetDisplayName(this RQ1MetricType type)
        {
            return type switch
            {
                RQ1MetricType.StaticObservation => "Static",
                RQ1MetricType.SlowTranslation => "Slow Trans",
                RQ1MetricType.FastMotion => "Fast Move",
                RQ1MetricType.Rotation => "Rotation",
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
                RQ1MetricType.SlowTranslation => "5-10 cm/s horizontal movement",
                RQ1MetricType.FastMotion => "50+ cm/s fast motion",
                RQ1MetricType.Rotation => "Rotation around multiple axes",
                RQ1MetricType.OcclusionRecovery => "Brief occlusion then recovery",
                _ => ""
            };
        }
    }
}

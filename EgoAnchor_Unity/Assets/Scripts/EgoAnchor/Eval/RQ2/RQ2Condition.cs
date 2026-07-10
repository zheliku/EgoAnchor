namespace EgoAnchor.Eval.RQ2
{
    /// <summary>
    /// RQ2 动态追踪试次的运动场景。
    /// </summary>
    public enum RQ2Condition
    {
        /// <summary>当前没有进行中的 RQ2 试次。</summary>
        None = 0,

        /// <summary>低速、近似匀速的平移试次。</summary>
        SlowTranslation = 1,

        /// <summary>包含较高线速度与明显加减速的快速挥动试次。</summary>
        FastMotion = 2,

        /// <summary>以姿态变化为主的旋转试次。</summary>
        Rotation = 3,
    }

    /// <summary>
    /// RQ2 场景的稳定日志表示。
    /// </summary>
    public static class RQ2ConditionExtensions
    {
        /// <summary>
        /// 将运动场景转换为 Python 分析契约使用的 snake_case 字符串。
        /// </summary>
        /// <param name="condition">待转换的 RQ2 运动场景。</param>
        /// <returns>稳定的日志字段值。</returns>
        public static string ToLogString(this RQ2Condition condition)
        {
            return condition switch
            {
                RQ2Condition.SlowTranslation => "slow_translation",
                RQ2Condition.FastMotion => "fast_motion",
                RQ2Condition.Rotation => "rotation",
                _ => "none",
            };
        }

        /// <summary>
        /// 获取运行时状态面板使用的简短场景名称。
        /// </summary>
        /// <param name="condition">待显示的 RQ2 运动场景。</param>
        /// <returns>英文场景名称。</returns>
        public static string GetDisplayName(this RQ2Condition condition)
        {
            return condition switch
            {
                RQ2Condition.SlowTranslation => "Slow Translation",
                RQ2Condition.FastMotion => "Fast Motion",
                RQ2Condition.Rotation => "Rotation",
                _ => "None",
            };
        }

    }
}

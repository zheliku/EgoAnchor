namespace EgoAnchor.Eval.RQ2
{
    /// <summary>
    /// RQ2 动态追踪试次的运动类型。
    /// </summary>
    public enum RQ2Condition
    {
        /// <summary>当前没有进行中的 RQ2 试次。</summary>
        None = 0,

        /// <summary>中低速平移试次；枚举值与默认数字键一致。</summary>
        Translation = 1,

        /// <summary>中低速旋转试次；枚举值与默认数字键一致。</summary>
        Rotation = 2,
    }

    /// <summary>
    /// RQ2 运动类型的稳定日志表示。
    /// </summary>
    public static class RQ2ConditionExtensions
    {
        /// <summary>
        /// 将运动类型转换为 Python 分析契约使用的 snake_case 字符串。
        /// </summary>
        /// <param name="condition">待转换的 RQ2 运动类型。</param>
        /// <returns>稳定的日志字段值。</returns>
        public static string ToLogString(this RQ2Condition condition)
        {
            return condition switch
            {
                RQ2Condition.Translation => "translation",
                RQ2Condition.Rotation => "rotation",
                _ => "none",
            };
        }

        /// <summary>
        /// 获取运行时状态面板使用的简短运动类型名称。
        /// </summary>
        /// <param name="condition">待显示的 RQ2 运动类型。</param>
        /// <returns>英文运动类型名称。</returns>
        public static string GetDisplayName(this RQ2Condition condition)
        {
            return condition switch
            {
                RQ2Condition.Translation => "Translation",
                RQ2Condition.Rotation => "Rotation",
                _ => "None",
            };
        }
    }
}

namespace EgoAnchor.Reliability
{
    /// <summary>
    /// Unity anchor policy 对可靠性评分的分层判断结果。
    /// </summary>
    public enum ReliabilityLevel
    {
        /// <summary>可靠性足以接受并更新 anchor。</summary>
        Accept,

        /// <summary>可靠性不足以更新，但可短时保持或冻结。</summary>
        Hold,

        /// <summary>可靠性过低，应视为丢失或进入重获取。</summary>
        Reject,
    }

    /// <summary>
    /// 可靠性评分判定结果。
    /// </summary>
    public readonly struct ReliabilityScore
    {
        /// <summary>评分分层。</summary>
        public readonly ReliabilityLevel Level;

        /// <summary>归一化评分，范围 0..1。</summary>
        public readonly float Score;

        /// <summary>判定原因。</summary>
        public readonly string Reason;

        /// <summary>
        /// 构造可靠性评分判定结果。
        /// </summary>
        /// <param name="level">评分分层。</param>
        /// <param name="score">归一化评分。</param>
        /// <param name="reason">判定原因。</param>
        public ReliabilityScore(ReliabilityLevel level, float score, string reason)
        {
            Level = level;
            Score = score;
            Reason = reason ?? string.Empty;
        }
    }
}

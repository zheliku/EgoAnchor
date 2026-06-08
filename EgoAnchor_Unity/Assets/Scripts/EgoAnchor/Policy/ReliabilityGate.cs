using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// 根据 Python perception reliability score 和 flags 判断当前 pose 是否可用于 anchor 更新。
    ///
    /// 本类不重新运行视觉算法，只消费 PoseResult 中已经携带的诊断量。
    /// </summary>
    public sealed class ReliabilityGate
    {
        /// <summary>允许直接更新 anchor 的最低评分。</summary>
        private readonly float minAcceptScore;

        /// <summary>允许保持/冻结但不更新的最低评分。</summary>
        private readonly float minHoldScore;

        /// <summary>
        /// 构造可靠性 gate。
        /// </summary>
        /// <param name="minAcceptScore">直接接受 pose 的最低评分。</param>
        /// <param name="minHoldScore">进入 hold/freeze 的最低评分。</param>
        public ReliabilityGate(float minAcceptScore = 0.35f, float minHoldScore = 0.12f)
        {
            this.minAcceptScore = Mathf.Clamp01(minAcceptScore);
            this.minHoldScore = Mathf.Clamp01(Mathf.Min(minHoldScore, this.minAcceptScore));
        }

        /// <summary>允许直接更新 anchor 的最低评分。</summary>
        public float MinAcceptScore => minAcceptScore;

        /// <summary>允许保持/冻结但不更新的最低评分。</summary>
        public float MinHoldScore => minHoldScore;

        /// <summary>
        /// 评估单帧 anchor 观测可靠性。
        /// </summary>
        /// <param name="observation">Unity anchor policy 观测。</param>
        /// <returns>可靠性分层和原因。</returns>
        public ReliabilityScore Evaluate(AnchorObservation observation)
        {
            float score = Mathf.Clamp01(observation.ReliabilityScore);
            if (!observation.HasAlignedPose)
            {
                return new ReliabilityScore(ReliabilityLevel.Reject, score, observation.FailureReason);
            }

            if (ContainsFlag(observation, "no_pose") || ContainsFlag(observation, "invalid_pose"))
            {
                return new ReliabilityScore(ReliabilityLevel.Reject, score, "flag_reject");
            }

            if (score >= minAcceptScore)
            {
                return new ReliabilityScore(ReliabilityLevel.Accept, score, "score_accept");
            }

            if (score >= minHoldScore)
            {
                return new ReliabilityScore(ReliabilityLevel.Hold, score, "score_hold");
            }

            return new ReliabilityScore(ReliabilityLevel.Reject, score, "score_reject");
        }

        /// <summary>
        /// 检查 observation flags 中是否包含指定片段。
        /// </summary>
        /// <param name="observation">Unity anchor policy 观测。</param>
        /// <param name="token">待查找片段。</param>
        /// <returns>是否命中。</returns>
        private static bool ContainsFlag(AnchorObservation observation, string token)
        {
            if (observation.ReliabilityFlags == null || string.IsNullOrEmpty(token))
            {
                return false;
            }

            foreach (string flag in observation.ReliabilityFlags)
            {
                if (!string.IsNullOrEmpty(flag) && flag.Contains(token))
                {
                    return true;
                }
            }

            return false;
        }
    }
}

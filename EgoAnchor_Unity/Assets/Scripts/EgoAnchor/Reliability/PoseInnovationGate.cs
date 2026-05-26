using UnityEngine;

namespace EgoAnchor.Reliability
{
    /// <summary>
    /// 检测相邻 anchor pose 的突变。
    ///
    /// 该 gate 用于拦截明显不合理的 world-space 跳变。它不负责平滑；
    /// 被拒绝的 pose 会由 AnchorPolicyController 保持上一 stable pose 并进入 FrozenUncertain。
    /// </summary>
    public sealed class PoseInnovationGate
    {
        /// <summary>单次更新允许的最大平移跳变，单位米。</summary>
        private readonly float maxTranslationMeters;

        /// <summary>单次更新允许的最大旋转跳变，单位度。</summary>
        private readonly float maxRotationDegrees;

        /// <summary>
        /// 构造 pose innovation gate。
        /// </summary>
        /// <param name="maxTranslationMeters">单次更新允许的最大平移跳变，单位米。</param>
        /// <param name="maxRotationDegrees">单次更新允许的最大旋转跳变，单位度。</param>
        public PoseInnovationGate(float maxTranslationMeters = 0.80f, float maxRotationDegrees = 90f)
        {
            this.maxTranslationMeters = Mathf.Max(0.001f, maxTranslationMeters);
            this.maxRotationDegrees = Mathf.Max(1f, maxRotationDegrees);
        }

        /// <summary>单次更新允许的最大平移跳变，单位米。</summary>
        public float MaxTranslationMeters => maxTranslationMeters;

        /// <summary>单次更新允许的最大旋转跳变，单位度。</summary>
        public float MaxRotationDegrees => maxRotationDegrees;

        /// <summary>
        /// 判断候选 pose 相对上一 stable pose 是否可接受。
        /// </summary>
        /// <param name="candidate">当前候选 world pose。</param>
        /// <param name="previousStable">上一 stable world pose。</param>
        /// <param name="hasPreviousStable">是否已有上一 stable pose。</param>
        /// <param name="reason">拒绝原因；接受时为空。</param>
        /// <returns>是否通过 gate。</returns>
        public bool IsAccepted(Pose candidate, Pose previousStable, bool hasPreviousStable, out string reason)
        {
            reason = string.Empty;
            if (!hasPreviousStable)
            {
                return true;
            }

            float translation = Vector3.Distance(candidate.position, previousStable.position);
            if (translation > maxTranslationMeters)
            {
                reason = $"translation_jump_{translation:F3}m";
                return false;
            }

            float rotation = Quaternion.Angle(candidate.rotation, previousStable.rotation);
            if (rotation > maxRotationDegrees)
            {
                reason = $"rotation_jump_{rotation:F1}deg";
                return false;
            }

            return true;
        }
    }
}

using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// PoseToAnchorRuntime 旁路挂载的 reliability-aware anchor policy 宿主。
    ///
    /// 本组件只负责持有 Inspector 阈值和 PolicyController 生命周期。是否启用 policy
    /// 由 PoseToAnchorRuntime 是否引用该组件决定；网络接收、frame alignment、Transform
    /// 应用仍分别保留在各自层里。
    /// </summary>
    public sealed class AnchorPolicyHost : MonoBehaviour
    {
        /// <summary>直接接受 pose 的最低可靠性评分。</summary>
        [Header("Reliability Gate")]
        [Tooltip("直接接受 pose 的最低可靠性评分。PoseResult.reliability_score 低于该值时不会更新 stable pose。")]
        [Range(0f, 1f)]
        [SerializeField] private float minAcceptScore = 0.35f;

        /// <summary>进入 hold/freeze 的最低可靠性评分。</summary>
        [Tooltip("进入 hold/freeze 的最低可靠性评分。低于该值时更快进入 Lost；高于该值但低于接受阈值时保持上一 stable pose。")]
        [Range(0f, 1f)]
        [SerializeField] private float minHoldScore = 0.12f;

        /// <summary>单次更新允许的最大平移跳变，单位米。</summary>
        [Header("Innovation Gate")]
        [Tooltip("单次更新允许的最大 world-space 平移跳变，单位米。超过后拒绝本帧 pose，避免 anchor 瞬移。")]
        [Min(0.001f)]
        [SerializeField] private float maxTranslationJumpMeters = 0.80f;

        /// <summary>单次更新允许的最大旋转跳变，单位度。</summary>
        [Tooltip("单次更新允许的最大 world-space 旋转跳变，单位度。超过后拒绝本帧 pose。")]
        [Min(1f)]
        [SerializeField] private float maxRotationJumpDegrees = 90f;

        /// <summary>短时 coasting 的时间上限，单位秒。</summary>
        [Header("Lifecycle")]
        [Tooltip("短时没有 pose 时允许 predictor/coasting 的时间上限，单位秒。")]
        [Min(0.01f)]
        [SerializeField] private float coastTimeoutSeconds = 0.45f;

        /// <summary>进入 Lost 的无可靠 pose 时间，单位秒。</summary>
        [Tooltip("连续没有可靠 pose 超过该时间后进入 Lost，单位秒。")]
        [Min(0.05f)]
        [SerializeField] private float lostTimeoutSeconds = 2.0f;

        /// <summary>当前 policy controller。</summary>
        private PolicyController controller;

        /// <summary>当前 policy 状态。</summary>
        public AnchorState State => Controller.State;

        /// <summary>policy 是否已有 stable pose。</summary>
        public bool HasStablePose => Controller.HasStablePose;

        /// <summary>当前 policy stable pose。</summary>
        public Pose StablePose => Controller.StablePose;

        /// <summary>
        /// Unity Awake：构造 policy controller。
        /// </summary>
        private void Awake()
        {
            Rebuild();
        }

        /// <summary>
        /// Inspector 修改阈值时重建 policy controller。
        /// </summary>
        private void OnValidate()
        {
            Rebuild();
        }

        /// <summary>
        /// 输入一帧观测并返回 policy 决策。
        /// </summary>
        /// <param name="observation">Unity anchor policy 观测。</param>
        /// <returns>本帧 policy 决策。</returns>
        public AnchorPolicyDecision AcceptPose(AnchorObservation observation)
        {
            return Controller.AcceptPose(observation);
        }

        /// <summary>
        /// reset command 或 status event 到达时通知 policy。
        /// </summary>
        /// <param name="sampleTimeSeconds">Unity 单调时间，单位秒。</param>
        /// <param name="reason">reset 原因。</param>
        public void NotifyReset(double sampleTimeSeconds, string reason)
        {
            Controller.NotifyReset(sampleTimeSeconds, reason);
        }

        /// <summary>
        /// reacquire command 或 status event 到达时通知 policy。
        /// </summary>
        /// <param name="sampleTimeSeconds">Unity 单调时间，单位秒。</param>
        /// <param name="reason">reacquire 原因。</param>
        public void NotifyReacquire(double sampleTimeSeconds, string reason)
        {
            Controller.NotifyReacquire(sampleTimeSeconds, reason);
        }

        /// <summary>
        /// 暂停本地 anchor policy。
        /// </summary>
        /// <param name="sampleTimeSeconds">Unity 单调时间，单位秒。</param>
        /// <param name="reason">暂停原因。</param>
        public void NotifyPause(double sampleTimeSeconds, string reason)
        {
            Controller.NotifyPause(sampleTimeSeconds, reason);
        }

        /// <summary>
        /// 恢复本地 anchor policy。
        /// </summary>
        /// <param name="sampleTimeSeconds">Unity 单调时间，单位秒。</param>
        /// <param name="reason">恢复原因。</param>
        public void NotifyResume(double sampleTimeSeconds, string reason)
        {
            Controller.NotifyResume(sampleTimeSeconds, reason);
        }

        /// <summary>
        /// 清空 policy 内部 stable pose 和状态机。
        /// </summary>
        /// <param name="sampleTimeSeconds">Unity 单调时间，单位秒。</param>
        /// <param name="reason">清空原因。</param>
        public void Clear(double sampleTimeSeconds, string reason)
        {
            Controller.Clear(sampleTimeSeconds, reason);
        }

        /// <summary>
        /// 重新构造 policy controller。会清空 policy 内部历史状态。
        /// </summary>
        public void Rebuild()
        {
            controller = new PolicyController(
                new ReliabilityGate(minAcceptScore, minHoldScore),
                new InnovationGate(maxTranslationJumpMeters, maxRotationJumpDegrees),
                new AnchorPredictor(coastTimeoutSeconds),
                new AnchorStateMachine(coastTimeoutSeconds, lostTimeoutSeconds)
            );
        }

        /// <summary>确保 controller 存在并返回。</summary>
        private PolicyController Controller
        {
            get
            {
                if (controller == null)
                {
                    Rebuild();
                }

                return controller;
            }
        }
    }
}

using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// reliability-aware anchor policy controller。
    ///
    /// 它组合可靠性评分 gate、pose innovation gate、短时 predictor 和 anchor 状态机，
    /// 将低频、延迟、含噪或间歇失效的 pose stream 转换为 Unity 可用的 anchor 更新行为。
    /// 本类不解码 Protobuf、不访问 NATS、不修改 Transform。
    /// </summary>
    public sealed class PolicyController
    {
        /// <summary>感知可靠性 gate。</summary>
        private readonly ReliabilityGate reliabilityGate;

        /// <summary>pose 跳变 gate。</summary>
        private readonly InnovationGate innovationGate;

        /// <summary>短时预测器。</summary>
        private readonly AnchorPredictor predictor;

        /// <summary>anchor 生命周期状态机。</summary>
        private readonly AnchorStateMachine stateMachine;

        /// <summary>最近 accepted stable pose。</summary>
        private Pose stablePose;

        /// <summary>是否已有 stable pose。</summary>
        private bool hasStablePose;

        /// <summary>最近可靠 pose 的 Unity 单调时间，单位秒。</summary>
        private double lastReliablePoseTimeSeconds = -1.0;

        /// <summary>连续低可靠 pose 开始时间，单位秒；-1 表示当前不在低可靠段。</summary>
        private double lowReliabilityStartTimeSeconds = -1.0;

        /// <summary>
        /// 构造 anchor policy controller。
        /// </summary>
        /// <param name="reliabilityGate">感知可靠性 gate；为空时使用默认阈值。</param>
        /// <param name="innovationGate">pose 跳变 gate；为空时使用默认阈值。</param>
        /// <param name="predictor">短时预测器；为空时使用默认参数。</param>
        /// <param name="stateMachine">状态机；为空时使用默认时间阈值。</param>
        public PolicyController(
            ReliabilityGate reliabilityGate = null,
            InnovationGate innovationGate = null,
            AnchorPredictor predictor = null,
            AnchorStateMachine stateMachine = null)
        {
            this.reliabilityGate = reliabilityGate ?? new ReliabilityGate();
            this.innovationGate = innovationGate ?? new InnovationGate();
            this.predictor = predictor ?? new AnchorPredictor();
            this.stateMachine = stateMachine ?? new AnchorStateMachine();
            stablePose = Pose.identity;
        }

        /// <summary>当前 anchor 生命周期状态。</summary>
        public AnchorState State => stateMachine.State;

        /// <summary>是否已有 stable pose。</summary>
        public bool HasStablePose => hasStablePose;

        /// <summary>当前 stable pose。</summary>
        public Pose StablePose => stablePose;

        /// <summary>最近一次状态变化事件。</summary>
        public AnchorLifecycleEvent LastLifecycleEvent => stateMachine.LastEvent;

        /// <summary>
        /// 输入一帧 anchor observation，并返回 anchor 更新决策。
        /// </summary>
        /// <param name="observation">frame alignment 后的 anchor observation。</param>
        /// <returns>本帧策略决策。</returns>
        public AnchorPolicyDecision AcceptPose(AnchorObservation observation)
        {
            if (!observation.HasAlignedPose)
            {
                return HandleMissing(observation);
            }

            ReliabilityScore reliability = reliabilityGate.Evaluate(observation);
            if (
                observation.IsRelocalization
                && observation.ReliabilityScore >= reliabilityGate.MinHoldScore
                && reliability.Level != ReliabilityLevel.Reject
            )
            {
                return AcceptStablePose(observation, "relocalize_accept");
            }

            if (reliability.Level != ReliabilityLevel.Accept)
            {
                AnchorState holdState = HandleLowReliability(observation, reliability.Reason);
                return new AnchorPolicyDecision(
                    AnchorPolicyAction.Reject,
                    holdState,
                    hasStablePose,
                    hasStablePose ? stablePose : Pose.identity,
                    reliability.Reason
                );
            }

            if (!innovationGate.IsAccepted(observation.WorldPose, stablePose, hasStablePose, out string innovationReason))
            {
                AnchorState frozenState = stateMachine.OnUncertainPose(observation.SampleTimeSeconds, innovationReason);
                return new AnchorPolicyDecision(
                    AnchorPolicyAction.Reject,
                    frozenState,
                    hasStablePose,
                    hasStablePose ? stablePose : Pose.identity,
                    innovationReason
                );
            }

            return AcceptStablePose(observation, reliability.Reason);
        }

        /// <summary>
        /// reset command 被本地接受或 Python status event 指示 reset 时调用。
        /// </summary>
        /// <param name="sampleTimeSeconds">当前 Unity 单调时间，单位秒。</param>
        /// <param name="reason">reset 原因。</param>
        public void NotifyReset(double sampleTimeSeconds, string reason)
        {
            ClearStablePose();
            stateMachine.OnReset(sampleTimeSeconds, reason);
        }

        /// <summary>
        /// reacquire command 被本地接受或 Python status event 指示 reacquire 时调用。
        /// </summary>
        /// <param name="sampleTimeSeconds">当前 Unity 单调时间，单位秒。</param>
        /// <param name="reason">reacquire 原因。</param>
        public void NotifyReacquire(double sampleTimeSeconds, string reason)
        {
            ClearStablePose();
            stateMachine.OnReacquire(sampleTimeSeconds, reason);
        }

        /// <summary>
        /// 用户暂停本地 anchor 更新。
        /// </summary>
        /// <param name="sampleTimeSeconds">当前 Unity 单调时间，单位秒。</param>
        /// <param name="reason">暂停原因。</param>
        public void NotifyPause(double sampleTimeSeconds, string reason)
        {
            stateMachine.OnPause(sampleTimeSeconds, reason);
        }

        /// <summary>
        /// 用户恢复本地 anchor 更新。
        /// </summary>
        /// <param name="sampleTimeSeconds">当前 Unity 单调时间，单位秒。</param>
        /// <param name="reason">恢复原因。</param>
        public void NotifyResume(double sampleTimeSeconds, string reason)
        {
            stateMachine.OnResume(sampleTimeSeconds, reason);
        }

        /// <summary>
        /// Python 报告不可恢复错误时调用，驱动状态机进入 Error。
        /// </summary>
        /// <param name="sampleTimeSeconds">当前 Unity 单调时间，单位秒。</param>
        /// <param name="reason">错误原因。</param>
        public void NotifyError(double sampleTimeSeconds, string reason)
        {
            stateMachine.OnError(sampleTimeSeconds, reason);
        }

        /// <summary>
        /// Python 报告目标丢失时调用，驱动状态机进入 Lost。
        /// </summary>
        /// <param name="sampleTimeSeconds">当前 Unity 单调时间，单位秒。</param>
        /// <param name="reason">丢失原因。</param>
        public void NotifyLost(double sampleTimeSeconds, string reason)
        {
            lowReliabilityStartTimeSeconds = -1.0;
            stateMachine.OnMissingPose(sampleTimeSeconds, double.PositiveInfinity, hasStablePose, reason);
        }

        /// <summary>
        /// 清空本地 policy 状态。
        /// </summary>
        /// <param name="sampleTimeSeconds">当前 Unity 单调时间，单位秒。</param>
        /// <param name="reason">清空原因。</param>
        public void Clear(double sampleTimeSeconds, string reason)
        {
            ClearStablePose();
            stateMachine.Clear(sampleTimeSeconds, reason);
        }

        /// <summary>
        /// 处理缺失 pose、对齐失败或无 pose 观测。
        /// </summary>
        /// <param name="observation">缺失或失败观测。</param>
        /// <returns>本帧策略决策。</returns>
        private AnchorPolicyDecision HandleMissing(AnchorObservation observation)
        {
            double secondsSinceReliable = lastReliablePoseTimeSeconds < 0.0
                ? double.PositiveInfinity
                : observation.SampleTimeSeconds - lastReliablePoseTimeSeconds;
            AnchorState nextState = stateMachine.OnMissingPose(
                observation.SampleTimeSeconds,
                secondsSinceReliable,
                hasStablePose,
                observation.FailureReason
            );

            if (nextState == AnchorState.Coasting && predictor.TryPredict(observation.SampleTimeSeconds, out Pose predictedPose))
            {
                stablePose = predictedPose;
                hasStablePose = true;
                return new AnchorPolicyDecision(AnchorPolicyAction.Coast, nextState, true, stablePose, observation.FailureReason);
            }

            return new AnchorPolicyDecision(
                AnchorPolicyAction.Hold,
                nextState,
                hasStablePose,
                hasStablePose ? stablePose : Pose.identity,
                observation.FailureReason
            );
        }

        /// <summary>
        /// 清空 stable pose 和预测状态。
        /// </summary>
        private void ClearStablePose()
        {
            stablePose = Pose.identity;
            hasStablePose = false;
            lastReliablePoseTimeSeconds = -1.0;
            predictor.Reset();
            lowReliabilityStartTimeSeconds = -1.0;
        }

        /// <summary>
        /// 接受当前 world pose 作为新的 stable pose，并同步状态机与预测器。
        /// </summary>
        /// <param name="observation">已完成 frame alignment 的 pose 观测。</param>
        /// <param name="reason">接受原因。</param>
        /// <returns>本帧策略决策。</returns>
        private AnchorPolicyDecision AcceptStablePose(AnchorObservation observation, string reason)
        {
            stablePose = observation.WorldPose;
            hasStablePose = true;
            lastReliablePoseTimeSeconds = observation.SampleTimeSeconds;
            lowReliabilityStartTimeSeconds = -1.0;
            predictor.Observe(stablePose, observation.SampleTimeSeconds);
            AnchorState state = stateMachine.OnReliablePose(observation.SampleTimeSeconds, reason);
            return new AnchorPolicyDecision(AnchorPolicyAction.Accept, state, true, stablePose, reason);
        }

        /// <summary>
        /// 处理低可靠但仍有 pose 的观测：短时冻结，持续过久后进入 Lost。
        /// </summary>
        /// <param name="observation">低可靠 anchor observation。</param>
        /// <param name="reason">低可靠原因。</param>
        /// <returns>转移后的 anchor 状态。</returns>
        private AnchorState HandleLowReliability(AnchorObservation observation, string reason)
        {
            if (lowReliabilityStartTimeSeconds < 0.0)
            {
                lowReliabilityStartTimeSeconds = observation.SampleTimeSeconds;
            }

            double lowDuration = observation.SampleTimeSeconds - lowReliabilityStartTimeSeconds;
            if (!hasStablePose)
            {
                return stateMachine.OnMissingPose(observation.SampleTimeSeconds, double.PositiveInfinity, false, reason);
            }

            if (lowDuration >= stateMachine.LostTimeoutSeconds)
            {
                return stateMachine.OnMissingPose(observation.SampleTimeSeconds, double.PositiveInfinity, true, reason);
            }

            return stateMachine.OnUncertainPose(observation.SampleTimeSeconds, reason);
        }
    }
}

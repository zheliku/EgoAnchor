using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// reliability-aware anchor policy controller（统一自适应滤波版）。
    ///
    /// 消息驱动入口 AcceptPose 负责"测量提交"：时序守卫 -> 测量门控（分数滞回 / 重定位旁路 /
    /// 马氏 innovation / 瞬移恢复）-> 按可靠性与运动状态自适应噪声校正统一 6DoF 滤波器 ->
    /// 状态机转移，返回输入分类决策。渲染帧驱动入口 Advance 负责"输出与计时"：
    /// 推进 coast/lost 计时（与消息解耦，感知停发也能正常退化），并把提交态预测到当前
    /// 时刻输出，使低频 pose 流变成逐帧连续的 anchor 运动。
    /// 本类不解码 Protobuf、不访问 NATS、不修改 Transform、不读取 Unity Time；
    /// 全部时间显式传入，可被 smoke 工具直接驱动。
    /// </summary>
    public sealed class PolicyController
    {
        /// <summary>当前参数包。</summary>
        private AnchorPolicyConfig config;

        /// <summary>统一 6DoF 自适应滤波器。</summary>
        private readonly AnchorPoseFilter filter;

        /// <summary>测量门控。</summary>
        private readonly AnchorMeasurementGate gate;

        /// <summary>静止/运动状态分类器。</summary>
        private readonly MotionStateClassifier classifier;

        /// <summary>anchor 生命周期状态机。</summary>
        private AnchorStateMachine stateMachine;

        /// <summary>最近一次被接受测量的到达时间，单位秒；coast/lost 计时基于到达时间，与管线延迟解耦。</summary>
        private double lastAcceptSampleTime = -1.0;

        /// <summary>最近一次被接受测量的 capture 时间，单位秒；时序守卫基于它判定测量乱序（冻结封账会推进滤波器内部时间，不能直接比较）。</summary>
        private double lastMeasurementCaptureTime = -1.0;

        /// <summary>是否冻结输出外推。低分拒绝/保持期间为 true：感知不健康时不再沿旧速度外推。</summary>
        private bool outputFrozen;

        /// <summary>最近一次决策/缺失原因，用于解释 Advance 输出。</summary>
        private string lastReason = "uninitialized";

        /// <summary>最近一次决策是否为接受类（Accept/Snap）。</summary>
        private bool lastDecisionAccepted;

        /// <summary>累计接受的测量数（含贴合接受）。</summary>
        private long acceptedCount;

        /// <summary>累计拒绝的测量数。</summary>
        private long rejectedCount;

        /// <summary>最近一次门控的 innovation 统计。</summary>
        private InnovationStats lastInnovation;

        /// <summary>最近一次门控的位置有效测量噪声，单位 m^2。</summary>
        private float lastREffPos;

        /// <summary>最近一次 Advance 实际使用的前推时长，单位秒。</summary>
        private float lastPredictAheadSeconds;

        /// <summary>
        /// 构造 anchor policy controller。
        /// </summary>
        /// <param name="config">参数包；为空时使用默认参数。</param>
        public PolicyController(AnchorPolicyConfig config = null)
        {
            this.config = config ?? new AnchorPolicyConfig();
            this.config.Validate();
            filter = new AnchorPoseFilter(this.config);
            gate = new AnchorMeasurementGate(this.config);
            classifier = new MotionStateClassifier(this.config);
            stateMachine = new AnchorStateMachine(this.config.maxCoastSeconds, this.config.lostTimeoutSeconds);
        }

        /// <summary>当前 anchor 生命周期状态。</summary>
        public AnchorState State => stateMachine.State;

        /// <summary>最近一次状态变化事件。</summary>
        public AnchorLifecycleEvent LastLifecycleEvent => stateMachine.LastEvent;

        /// <summary>当前运动状态。</summary>
        public AnchorMotionState MotionState => classifier.State;

        /// <summary>滤波器是否已有提交态。</summary>
        public bool HasFilterState => filter.HasState;

        /// <summary>当前估计线速度模长，单位米/秒。</summary>
        public float SpeedMps => filter.Velocity.magnitude;

        /// <summary>当前估计角速度模长，单位度/秒。</summary>
        public float AngularSpeedDps => filter.AngularSpeedDps;

        /// <summary>最近一次门控的位置 innovation 马氏距离平方。</summary>
        public float LastInnovationPosD2 => lastInnovation.PosD2;

        /// <summary>最近一次门控的旋转 innovation 马氏距离平方。</summary>
        public float LastInnovationRotD2 => lastInnovation.RotD2;

        /// <summary>最近一次门控的位置有效测量噪声，单位 m^2。</summary>
        public float LastREffPos => lastREffPos;

        /// <summary>最近一次 Advance 实际使用的前推时长，单位秒。</summary>
        public float PredictAheadSeconds => lastPredictAheadSeconds;

        /// <summary>累计接受的测量数（含贴合接受）。</summary>
        public long AcceptedCount => acceptedCount;

        /// <summary>累计拒绝的测量数。</summary>
        public long RejectedCount => rejectedCount;

        /// <summary>
        /// 热更参数包，不清空滤波/门控/分类历史。
        /// 仅当 coast/lost 时长变化时重建状态机并回填当前状态。
        /// </summary>
        /// <param name="newConfig">新的参数包。</param>
        public void ApplyConfig(AnchorPolicyConfig newConfig)
        {
            if (newConfig == null)
            {
                return;
            }

            newConfig.Validate();
            bool timeoutsChanged = !Mathf.Approximately((float)stateMachine.CoastTimeoutSeconds, newConfig.maxCoastSeconds)
                || !Mathf.Approximately((float)stateMachine.LostTimeoutSeconds, newConfig.lostTimeoutSeconds);

            config = newConfig;
            filter.ApplyConfig(newConfig);
            gate.ApplyConfig(newConfig);
            classifier.ApplyConfig(newConfig);

            if (timeoutsChanged)
            {
                RebuildStateMachinePreservingState();
            }
        }

        /// <summary>
        /// 输入一帧 anchor observation，提交测量并返回输入分类决策。
        /// 渲染输出请使用 Advance。
        /// </summary>
        /// <param name="observation">frame alignment 后的 anchor observation。</param>
        /// <returns>本帧输入分类决策。</returns>
        public AnchorPolicyDecision AcceptPose(AnchorObservation observation)
        {
            if (stateMachine.State == AnchorState.Paused)
            {
                return Classified(AnchorPolicyAction.Hold, AnchorState.Paused, "paused", accepted: false);
            }

            if (!observation.HasAlignedPose)
            {
                return HandleMissing(observation);
            }

            double measurementTime = observation.HasCaptureTime
                ? observation.CaptureTimeSeconds
                : observation.SampleTimeSeconds;

            // 时序守卫：超龄或乱序（早于上一条已接受测量）的测量直接丢弃，保证滤波时间轴单调。
            if (observation.SampleTimeSeconds - measurementTime > config.maxMeasurementAgeSeconds
                || (filter.HasState && measurementTime <= lastMeasurementCaptureTime))
            {
                rejectedCount++;
                return Classified(AnchorPolicyAction.Reject, stateMachine.State, "stale_measurement", accepted: false);
            }

            AnchorGateResult gateResult = gate.Evaluate(in observation, filter, filter.StaticMode, measurementTime);
            lastInnovation = gateResult.Innovation;
            lastREffPos = gateResult.REffPos;

            switch (gateResult.Action)
            {
                case AnchorGateAction.AcceptSnap:
                {
                    filter.Snap(observation.WorldPose, measurementTime);
                    classifier.Reset();
                    lastAcceptSampleTime = observation.SampleTimeSeconds;
                    lastMeasurementCaptureTime = measurementTime;
                    outputFrozen = false;
                    acceptedCount++;
                    AnchorState snapState = stateMachine.OnReliablePose(observation.SampleTimeSeconds, gateResult.Reason);
                    return Classified(AnchorPolicyAction.Snap, snapState, gateResult.Reason, accepted: true);
                }
                case AnchorGateAction.Accept:
                {
                    filter.Correct(observation.WorldPose, measurementTime, gateResult.REffPos, gateResult.REffRot);
                    classifier.Observe(observation.WorldPose, in lastInnovation, measurementTime);
                    filter.SetStaticMode(classifier.IsStatic);
                    lastAcceptSampleTime = observation.SampleTimeSeconds;
                    lastMeasurementCaptureTime = measurementTime;
                    outputFrozen = false;
                    acceptedCount++;
                    AnchorState acceptState = stateMachine.OnReliablePose(observation.SampleTimeSeconds, gateResult.Reason);
                    return Classified(AnchorPolicyAction.Accept, acceptState, gateResult.Reason, accepted: true);
                }
                case AnchorGateAction.Hold:
                {
                    outputFrozen = true;
                    AnchorState holdState = stateMachine.OnUncertainPose(observation.SampleTimeSeconds, gateResult.Reason);
                    return Classified(AnchorPolicyAction.Hold, holdState, gateResult.Reason, accepted: false);
                }
                default:
                {
                    rejectedCount++;
                    // 低分/硬 flag 拒绝表示感知不健康，冻结外推；跳变拒绝仍信任预测，允许继续 coast。
                    if (gateResult.Reason == "score_reject" || gateResult.Reason == "flag_reject")
                    {
                        outputFrozen = true;
                    }

                    AnchorState rejectState = stateMachine.OnUncertainPose(observation.SampleTimeSeconds, gateResult.Reason);
                    return Classified(AnchorPolicyAction.Reject, rejectState, gateResult.Reason, accepted: false);
                }
            }
        }

        /// <summary>
        /// 每渲染帧推进计时并输出当前 anchor pose。
        /// 计时基于"距最近被接受测量的时长"，与消息到达解耦：感知停发时
        /// 也会按 Coasting -> FrozenUncertain -> Lost 正常退化。
        /// </summary>
        /// <param name="nowSeconds">当前 Unity 单调时间，单位秒。</param>
        /// <returns>本帧 anchor 输出。</returns>
        public AnchorPolicyOutput Advance(double nowSeconds)
        {
            if (stateMachine.State == AnchorState.Paused)
            {
                lastPredictAheadSeconds = 0f;
                filter.FreezeCoast(nowSeconds);
                return new AnchorPolicyOutput(
                    filter.HasState,
                    filter.PredictAt(nowSeconds, AnchorPredictMode.Hold),
                    AnchorState.Paused,
                    classifier.State,
                    0f,
                    "paused"
                );
            }

            if (!filter.HasState)
            {
                lastPredictAheadSeconds = 0f;
                return AnchorPolicyOutput.None(stateMachine.State, lastReason);
            }

            double gap = nowSeconds - lastAcceptSampleTime;
            string gapReason = lastDecisionAccepted ? "no_recent_measurement" : lastReason;
            AnchorState state;
            AnchorPredictMode mode;

            if (gap <= config.coastGraceSeconds)
            {
                // 正常消息间隙：不做状态转移，跟踪态前推隐藏延迟，冻结态封账保持。
                state = stateMachine.State;
                if (outputFrozen)
                {
                    filter.FreezeCoast(nowSeconds);
                    mode = AnchorPredictMode.Hold;
                }
                else
                {
                    mode = AnchorPredictMode.Track;
                }
            }
            else if (gap <= config.maxCoastSeconds)
            {
                if (outputFrozen)
                {
                    filter.FreezeCoast(nowSeconds);
                    state = stateMachine.OnUncertainPose(nowSeconds, gapReason);
                    mode = AnchorPredictMode.Hold;
                }
                else
                {
                    state = stateMachine.OnMissingPose(nowSeconds, gap, hasStablePose: true, gapReason);
                    mode = AnchorPredictMode.Coast;
                }
            }
            else
            {
                // 超过续航上限：把外推位姿封账并清零速度（显示连续，不回跳）；
                // 状态机按时长进入 FrozenUncertain 或 Lost，协方差随冻结时长增长使重获更容易。
                filter.FreezeCoast(nowSeconds);
                state = stateMachine.OnMissingPose(nowSeconds, gap, hasStablePose: true, gapReason);
                mode = AnchorPredictMode.Hold;
            }

            Pose pose = filter.PredictAt(nowSeconds, mode);
            lastPredictAheadSeconds = ComputePredictAhead(nowSeconds, mode);
            return new AnchorPolicyOutput(true, pose, state, classifier.State, lastPredictAheadSeconds, gapReason);
        }

        /// <summary>
        /// reset command 被本地接受或 Python status event 指示 reset 时调用。
        /// </summary>
        /// <param name="sampleTimeSeconds">当前 Unity 单调时间，单位秒。</param>
        /// <param name="reason">reset 原因。</param>
        public void NotifyReset(double sampleTimeSeconds, string reason)
        {
            ResetTrackingState(reason);
            stateMachine.OnReset(sampleTimeSeconds, reason);
        }

        /// <summary>
        /// reacquire command 被本地接受或 Python status event 指示 reacquire 时调用。
        /// </summary>
        /// <param name="sampleTimeSeconds">当前 Unity 单调时间，单位秒。</param>
        /// <param name="reason">reacquire 原因。</param>
        public void NotifyReacquire(double sampleTimeSeconds, string reason)
        {
            ResetTrackingState(reason);
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
        /// Python 报告目标丢失时调用：冻结外推并驱动状态机进入 Lost。
        /// </summary>
        /// <param name="sampleTimeSeconds">当前 Unity 单调时间，单位秒。</param>
        /// <param name="reason">丢失原因。</param>
        public void NotifyLost(double sampleTimeSeconds, string reason)
        {
            outputFrozen = true;
            lastReason = reason ?? "server_lost";
            lastDecisionAccepted = false;
            filter.FreezeCoast(sampleTimeSeconds);
            stateMachine.OnMissingPose(sampleTimeSeconds, double.PositiveInfinity, filter.HasState, reason);
        }

        /// <summary>
        /// 清空本地 policy 状态。
        /// </summary>
        /// <param name="sampleTimeSeconds">当前 Unity 单调时间，单位秒。</param>
        /// <param name="reason">清空原因。</param>
        public void Clear(double sampleTimeSeconds, string reason)
        {
            ResetTrackingState(reason);
            stateMachine.Clear(sampleTimeSeconds, reason);
        }

        /// <summary>
        /// 处理缺失 pose、对齐失败或无 pose 观测：只驱动状态机，不改滤波状态。
        /// </summary>
        /// <param name="observation">缺失或失败观测。</param>
        /// <returns>本帧输入分类决策。</returns>
        private AnchorPolicyDecision HandleMissing(AnchorObservation observation)
        {
            double gap = lastAcceptSampleTime < 0.0
                ? double.PositiveInfinity
                : observation.SampleTimeSeconds - lastAcceptSampleTime;
            AnchorState state = stateMachine.OnMissingPose(
                observation.SampleTimeSeconds,
                gap,
                filter.HasState,
                observation.FailureReason
            );
            AnchorPolicyAction action = state == AnchorState.Coasting && !outputFrozen
                ? AnchorPolicyAction.Coast
                : AnchorPolicyAction.Hold;
            return Classified(action, state, observation.FailureReason, accepted: false);
        }

        /// <summary>
        /// 记录决策原因并构造决策结果。
        /// </summary>
        private AnchorPolicyDecision Classified(AnchorPolicyAction action, AnchorState state, string reason, bool accepted)
        {
            lastReason = reason ?? string.Empty;
            lastDecisionAccepted = accepted;
            return new AnchorPolicyDecision(action, state, reason);
        }

        /// <summary>
        /// 清空滤波/门控/分类与计时状态（不动状态机）。
        /// </summary>
        private void ResetTrackingState(string reason)
        {
            filter.Reset();
            gate.Reset();
            classifier.Reset();
            lastAcceptSampleTime = -1.0;
            lastMeasurementCaptureTime = -1.0;
            outputFrozen = false;
            lastReason = reason ?? string.Empty;
            lastDecisionAccepted = false;
            lastInnovation = default;
            lastREffPos = 0f;
            lastPredictAheadSeconds = 0f;
        }

        /// <summary>
        /// 计算本帧实际前推时长，仅用于诊断展示。
        /// </summary>
        private float ComputePredictAhead(double nowSeconds, AnchorPredictMode mode)
        {
            float gap = Mathf.Max((float)(nowSeconds - filter.StateTimeSeconds), 0f);
            switch (mode)
            {
                case AnchorPredictMode.Track:
                    return filter.StaticMode ? 0f : Mathf.Min(gap, config.maxPredictAheadSeconds);
                case AnchorPredictMode.Coast:
                    return gap;
                default:
                    return 0f;
            }
        }

        /// <summary>
        /// coast/lost 时长配置变化时重建状态机并回填当前状态。
        /// AnchorStateMachine 的时长在构造时固定（该类保持冻结不改），
        /// 这里通过对应转移调用恢复观测状态，保证 Inspector 热更不丢生命周期。
        /// </summary>
        private void RebuildStateMachinePreservingState()
        {
            AnchorState previous = stateMachine.State;
            stateMachine = new AnchorStateMachine(config.maxCoastSeconds, config.lostTimeoutSeconds);
            const string reason = "config_reapplied";
            switch (previous)
            {
                case AnchorState.Searching:
                    stateMachine.OnReset(0.0, reason);
                    break;
                case AnchorState.Tracking:
                    stateMachine.OnReliablePose(0.0, reason);
                    break;
                case AnchorState.Coasting:
                    stateMachine.OnMissingPose(0.0, 0.0, hasStablePose: true, reason);
                    break;
                case AnchorState.FrozenUncertain:
                    stateMachine.OnUncertainPose(0.0, reason);
                    break;
                case AnchorState.Lost:
                    stateMachine.OnMissingPose(0.0, double.PositiveInfinity, hasStablePose: true, reason);
                    break;
                case AnchorState.Relocalizing:
                    stateMachine.OnReacquire(0.0, reason);
                    break;
                case AnchorState.Paused:
                    stateMachine.OnPause(0.0, reason);
                    break;
                case AnchorState.Error:
                    stateMachine.OnError(0.0, reason);
                    break;
                default:
                    break;
            }
        }
    }
}

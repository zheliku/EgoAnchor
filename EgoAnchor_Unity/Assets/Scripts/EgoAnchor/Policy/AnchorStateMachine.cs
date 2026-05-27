namespace EgoAnchor.Policy
{
    /// <summary>
    /// Unity anchor 生命周期状态机。
    ///
    /// 本类只维护 anchor 状态和最近状态变化原因，不做坐标转换、不做滤波、
    /// 不订阅网络。PoseToAnchorRuntime 或 AnchorPolicyHost/PolicyController 根据 pose 质量和
    /// command/status 事件调用它，从而把状态转移逻辑从 MonoBehaviour 中拆出来。
    /// </summary>
    public sealed class AnchorStateMachine
    {
        /// <summary>短时无 pose 时保持 Coasting 的时间上限，单位秒。</summary>
        private readonly double coastTimeoutSeconds;

        /// <summary>进入 Lost 的无可靠 pose 时间上限，单位秒。</summary>
        private readonly double lostTimeoutSeconds;

        /// <summary>当前 anchor 生命周期状态。</summary>
        private AnchorState state = AnchorState.Uninitialized;

        /// <summary>暂停前的状态，用于 resume 时恢复。</summary>
        private AnchorState stateBeforePause = AnchorState.Uninitialized;

        /// <summary>最近一次状态变化事件。</summary>
        private AnchorLifecycleEvent lastEvent;

        /// <summary>
        /// 构造 anchor 状态机。
        /// </summary>
        /// <param name="coastTimeoutSeconds">短时无 pose 的 coasting 上限，单位秒。</param>
        /// <param name="lostTimeoutSeconds">进入 Lost 的无可靠 pose 上限，单位秒。</param>
        public AnchorStateMachine(double coastTimeoutSeconds = 0.45, double lostTimeoutSeconds = 2.0)
        {
            this.coastTimeoutSeconds = coastTimeoutSeconds > 0.0 ? coastTimeoutSeconds : 0.45;
            this.lostTimeoutSeconds = lostTimeoutSeconds > this.coastTimeoutSeconds
                ? lostTimeoutSeconds
                : this.coastTimeoutSeconds * 3.0;
            lastEvent = new AnchorLifecycleEvent(AnchorState.Uninitialized, AnchorState.Uninitialized, "initialized");
        }

        /// <summary>当前 anchor 生命周期状态。</summary>
        public AnchorState State => state;

        /// <summary>短时无 pose 时保持 Coasting 的时间上限，单位秒。</summary>
        public double CoastTimeoutSeconds => coastTimeoutSeconds;

        /// <summary>进入 Lost 的无可靠 pose 时间上限，单位秒。</summary>
        public double LostTimeoutSeconds => lostTimeoutSeconds;

        /// <summary>最近一次状态变化事件。</summary>
        public AnchorLifecycleEvent LastEvent => lastEvent;

        /// <summary>
        /// 可靠 pose 被接受时进入 Tracking。
        /// </summary>
        /// <param name="sampleTimeSeconds">当前 Unity 单调时间，单位秒。</param>
        /// <param name="reason">状态变化原因。</param>
        /// <returns>当前状态。</returns>
        public AnchorState OnReliablePose(double sampleTimeSeconds, string reason = "reliable_pose")
        {
            if (state == AnchorState.Paused)
            {
                return state;
            }

            return TransitionTo(AnchorState.Tracking, reason, sampleTimeSeconds);
        }

        /// <summary>
        /// pose 可疑或被 gate 拒绝时进入 FrozenUncertain。
        /// </summary>
        /// <param name="sampleTimeSeconds">当前 Unity 单调时间，单位秒。</param>
        /// <param name="reason">拒绝或冻结原因。</param>
        /// <returns>当前状态。</returns>
        public AnchorState OnUncertainPose(double sampleTimeSeconds, string reason)
        {
            if (state == AnchorState.Paused)
            {
                return state;
            }

            return TransitionTo(AnchorState.FrozenUncertain, reason, sampleTimeSeconds);
        }

        /// <summary>
        /// 缺少 pose 时根据缺失时长进入 Searching、Coasting 或 Lost。
        /// </summary>
        /// <param name="sampleTimeSeconds">当前 Unity 单调时间，单位秒。</param>
        /// <param name="secondsSinceReliablePose">距离最近可靠 pose 的时间，单位秒。</param>
        /// <param name="hasStablePose">Unity 是否已有可保持的稳定 anchor pose。</param>
        /// <param name="reason">缺失原因。</param>
        /// <returns>当前状态。</returns>
        public AnchorState OnMissingPose(double sampleTimeSeconds, double secondsSinceReliablePose, bool hasStablePose, string reason)
        {
            if (state == AnchorState.Paused)
            {
                return state;
            }

            if (!hasStablePose)
            {
                return TransitionTo(AnchorState.Searching, reason, sampleTimeSeconds);
            }

            if (secondsSinceReliablePose <= coastTimeoutSeconds)
            {
                return TransitionTo(AnchorState.Coasting, reason, sampleTimeSeconds);
            }

            if (secondsSinceReliablePose >= lostTimeoutSeconds)
            {
                return TransitionTo(AnchorState.Lost, reason, sampleTimeSeconds);
            }

            return TransitionTo(AnchorState.FrozenUncertain, reason, sampleTimeSeconds);
        }

        /// <summary>
        /// reset 后进入 Searching。
        /// </summary>
        /// <param name="sampleTimeSeconds">当前 Unity 单调时间，单位秒。</param>
        /// <param name="reason">reset 原因。</param>
        /// <returns>当前状态。</returns>
        public AnchorState OnReset(double sampleTimeSeconds, string reason)
        {
            return TransitionTo(AnchorState.Searching, reason, sampleTimeSeconds);
        }

        /// <summary>
        /// reacquire 后进入 Relocalizing。
        /// </summary>
        /// <param name="sampleTimeSeconds">当前 Unity 单调时间，单位秒。</param>
        /// <param name="reason">reacquire 原因。</param>
        /// <returns>当前状态。</returns>
        public AnchorState OnReacquire(double sampleTimeSeconds, string reason)
        {
            return TransitionTo(AnchorState.Relocalizing, reason, sampleTimeSeconds);
        }

        /// <summary>
        /// 用户暂停 anchor 更新。
        /// </summary>
        /// <param name="sampleTimeSeconds">当前 Unity 单调时间，单位秒。</param>
        /// <param name="reason">暂停原因。</param>
        /// <returns>当前状态。</returns>
        public AnchorState OnPause(double sampleTimeSeconds, string reason)
        {
            if (state != AnchorState.Paused)
            {
                stateBeforePause = state;
            }

            return TransitionTo(AnchorState.Paused, reason, sampleTimeSeconds);
        }

        /// <summary>
        /// 用户恢复 anchor 更新。
        /// </summary>
        /// <param name="sampleTimeSeconds">当前 Unity 单调时间，单位秒。</param>
        /// <param name="reason">恢复原因。</param>
        /// <returns>当前状态。</returns>
        public AnchorState OnResume(double sampleTimeSeconds, string reason)
        {
            AnchorState target = stateBeforePause == AnchorState.Paused ? AnchorState.Searching : stateBeforePause;
            if (target == AnchorState.Uninitialized)
            {
                target = AnchorState.Searching;
            }

            return TransitionTo(target, reason, sampleTimeSeconds);
        }

        /// <summary>
        /// 出现不可恢复错误时进入 Error。
        /// </summary>
        /// <param name="sampleTimeSeconds">当前 Unity 单调时间，单位秒。</param>
        /// <param name="reason">错误原因。</param>
        /// <returns>当前状态。</returns>
        public AnchorState OnError(double sampleTimeSeconds, string reason)
        {
            return TransitionTo(AnchorState.Error, reason, sampleTimeSeconds);
        }

        /// <summary>
        /// 清空状态机到 Uninitialized。
        /// </summary>
        /// <param name="sampleTimeSeconds">当前 Unity 单调时间，单位秒。</param>
        /// <param name="reason">清空原因。</param>
        public void Clear(double sampleTimeSeconds, string reason)
        {
            TransitionTo(AnchorState.Uninitialized, reason, sampleTimeSeconds);
            stateBeforePause = AnchorState.Uninitialized;
        }

        /// <summary>
        /// 统一执行状态转移并记录事件。
        /// </summary>
        /// <param name="nextState">目标状态。</param>
        /// <param name="reason">转移原因。</param>
        /// <param name="sampleTimeSeconds">当前 Unity 单调时间，单位秒。</param>
        /// <returns>转移后的状态。</returns>
        private AnchorState TransitionTo(AnchorState nextState, string reason, double sampleTimeSeconds)
        {
            AnchorState previous = state;
            state = nextState;
            lastEvent = new AnchorLifecycleEvent(previous, nextState, reason);
            return state;
        }
    }
}

namespace EgoAnchor.Anchor
{
    /// <summary>
    /// Unity anchor 生命周期状态。
    ///
    /// 该状态只描述 Unity 应用层 anchor 行为，不等同于 Python perception runtime 的
    /// detect/register/track phase。Python 负责输出 camera-space pose 与诊断；
    /// Unity 负责把不可靠 pose stream 组织成可用于 MR 交互的 anchor 生命周期。
    /// </summary>
    public enum AnchorState
    {
        /// <summary>尚未收到有效 pose，或 runtime 还未完成必要配置。</summary>
        Uninitialized,

        /// <summary>正在等待 Python 检测/register，Unity 暂无稳定 anchor。</summary>
        Searching,

        /// <summary>持续收到可靠 pose，anchor 正常更新。</summary>
        Tracking,

        /// <summary>短时间缺少 pose，使用预测或上一稳定 pose 维持显示。</summary>
        Coasting,

        /// <summary>pose 不可靠，冻结稳定输出并标记为不确定。</summary>
        FrozenUncertain,

        /// <summary>长时间没有可靠 pose，anchor 已丢失或停止更新。</summary>
        Lost,

        /// <summary>用户或系统主动请求重新获取目标。</summary>
        Relocalizing,

        /// <summary>用户暂停 anchor 更新。</summary>
        Paused,

        /// <summary>协议、对齐或 runtime 出现需要人工排查的错误。</summary>
        Error,
    }

    /// <summary>
    /// Anchor 生命周期状态变化记录。
    /// </summary>
    public readonly struct AnchorLifecycleEvent
    {
        /// <summary>状态变化前的状态。</summary>
        public readonly AnchorState PreviousState;

        /// <summary>状态变化后的状态。</summary>
        public readonly AnchorState CurrentState;

        /// <summary>触发状态变化的原因。</summary>
        public readonly string Reason;

        /// <summary>触发状态变化的 Unity 单调时间，单位秒。</summary>
        public readonly double SampleTimeSeconds;

        /// <summary>
        /// 构造一条 anchor 生命周期事件。
        /// </summary>
        /// <param name="previousState">状态变化前的状态。</param>
        /// <param name="currentState">状态变化后的状态。</param>
        /// <param name="reason">触发状态变化的原因。</param>
        /// <param name="sampleTimeSeconds">触发状态变化的 Unity 单调时间，单位秒。</param>
        public AnchorLifecycleEvent(AnchorState previousState, AnchorState currentState, string reason, double sampleTimeSeconds)
        {
            PreviousState = previousState;
            CurrentState = currentState;
            Reason = reason ?? string.Empty;
            SampleTimeSeconds = sampleTimeSeconds;
        }
    }
}

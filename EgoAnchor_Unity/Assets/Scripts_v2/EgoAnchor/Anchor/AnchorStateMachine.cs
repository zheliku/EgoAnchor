namespace EgoAnchor.V2.Anchor
{
    /// <summary>
    /// v2 anchor 生命周期状态。
    ///
    /// 状态机用于把间歇、低频、可能失败的 pose observation 转成对用户稳定可解释的 anchor 生命周期，
    /// 不应与网络接收或 Transform 应用逻辑混在一起。
    /// </summary>
    public enum AnchorState
    {
        /// <summary>尚未初始化，未收到有效配置或控制命令。</summary>
        Uninitialized,

        /// <summary>正在寻找目标，等待首次可靠 register/re-register。</summary>
        Searching,

        /// <summary>收到连续可靠 pose，正常跟踪。</summary>
        Tracking,

        /// <summary>短时丢失或低置信度，暂时用预测/保持策略滑行。</summary>
        Coasting,

        /// <summary>不确定性过高，冻结在最后可信 pose，避免错误跳变。</summary>
        FrozenUncertain,

        /// <summary>目标丢失，无法安全输出稳定 pose。</summary>
        Lost,

        /// <summary>正在执行主动重定位流程。</summary>
        Relocalizing,

        /// <summary>用户或系统暂停 anchor 更新。</summary>
        Paused,
    }

    /// <summary>
    /// v2 anchor 状态机占位。
    /// 后续应集中处理 reset/reacquire/pause、PoseResult.has_pose、可靠性评分和失败原因等事件。
    /// </summary>
    public sealed class AnchorStateMachine
    {
        /// <summary>当前 anchor 生命周期状态。</summary>
        public AnchorState State { get; private set; } = AnchorState.Uninitialized;

        /// <summary>
        /// 重置状态机，进入 Searching 等待重新捕获目标。
        /// </summary>
        public void Reset()
        {
            State = AnchorState.Searching;
        }
    }
}

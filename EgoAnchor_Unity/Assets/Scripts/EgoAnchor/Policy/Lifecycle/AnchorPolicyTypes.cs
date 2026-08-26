namespace EgoAnchor.Policy
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
        /// <summary>
        /// 尚无可用 anchor：冷启动、等待 Python 检测/register、reset 或 reacquire 后重建中。
        /// 触发原因（cold start / reset / reacquire / low_score_reacquire）见 policy reason，不再单列状态。
        /// </summary>
        Searching,

        /// <summary>
        /// anchor 正常显示：最近一次可靠 pose 仍在 coast 窗口内。
        ///
        /// 渲染帧率高于 pose 到达率，因此绝大多数帧都处于"上一条可靠 pose 之后、下一条到达之前"的
        /// 帧间空档，物体停在预测位置。该空档属于正常追踪，不单列状态；实际空档长度见 observation_age_ms。
        /// </summary>
        Tracking,

        /// <summary>已有 anchor 但当前 pose 不可信：质量评估门控拒绝，或超出 coast 窗口仍未到 lost 超时。</summary>
        Uncertain,

        /// <summary>超过 lost 超时仍无可靠 pose，anchor 已丢失。</summary>
        Lost,

        /// <summary>用户暂停 anchor 更新。</summary>
        Paused,

        /// <summary>协议、对齐或 runtime 出现需要人工排查的错误。</summary>
        Error,
    }

    /// <summary>
    /// anchor 目标的运动状态。
    /// </summary>
    public enum AnchorMotionState
    {
        /// <summary>暂无足够证据，通常表示冷启动或刚重置。</summary>
        Unknown,

        /// <summary>静止，输出阶段可以启用静止锁或更强抖动抑制。</summary>
        Static,

        /// <summary>运动，输出阶段应优先保持跟随和低延迟。</summary>
        Moving,
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

        /// <summary>
        /// 构造一条 anchor 生命周期事件。
        /// </summary>
        /// <param name="previousState">状态变化前的状态。</param>
        /// <param name="currentState">状态变化后的状态。</param>
        /// <param name="reason">触发状态变化的原因。</param>
        public AnchorLifecycleEvent(AnchorState previousState, AnchorState currentState, string reason)
        {
            PreviousState = previousState;
            CurrentState = currentState;
            Reason = reason ?? string.Empty;
        }
    }
}

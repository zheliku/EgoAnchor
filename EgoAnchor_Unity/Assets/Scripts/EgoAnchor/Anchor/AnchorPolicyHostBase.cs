using UnityEngine;

namespace EgoAnchor.Anchor
{
    /// <summary>
    /// PoseToAnchorRuntime 可调用的 policy host 抽象接口。
    ///
    /// Anchor 层只依赖这个基类，因此不会直接依赖 Reliability 层的具体 gate/controller。
    /// Reliability 层可通过派生 MonoBehaviour 提供具体实现并挂在同一个 GameObject 上。
    /// </summary>
    public abstract class AnchorPolicyHostBase : MonoBehaviour
    {
        /// <summary>当前 policy 推导出的 anchor 生命周期状态。</summary>
        public abstract AnchorState State { get; }

        /// <summary>
        /// 输入一帧观测并返回 policy 决策。
        /// </summary>
        /// <param name="observation">Unity anchor policy 观测。</param>
        /// <returns>本帧 policy 决策。</returns>
        public abstract AnchorPolicyDecision AcceptPose(AnchorObservation observation);

        /// <summary>
        /// reset command 或 status event 到达时通知 policy。
        /// </summary>
        /// <param name="sampleTimeSeconds">Unity 单调时间，单位秒。</param>
        /// <param name="reason">reset 原因。</param>
        public abstract void NotifyReset(double sampleTimeSeconds, string reason);

        /// <summary>
        /// reacquire command 或 status event 到达时通知 policy。
        /// </summary>
        /// <param name="sampleTimeSeconds">Unity 单调时间，单位秒。</param>
        /// <param name="reason">reacquire 原因。</param>
        public abstract void NotifyReacquire(double sampleTimeSeconds, string reason);

        /// <summary>
        /// 暂停本地 anchor policy。
        /// </summary>
        /// <param name="sampleTimeSeconds">Unity 单调时间，单位秒。</param>
        /// <param name="reason">暂停原因。</param>
        public abstract void NotifyPause(double sampleTimeSeconds, string reason);

        /// <summary>
        /// 恢复本地 anchor policy。
        /// </summary>
        /// <param name="sampleTimeSeconds">Unity 单调时间，单位秒。</param>
        /// <param name="reason">恢复原因。</param>
        public abstract void NotifyResume(double sampleTimeSeconds, string reason);

        /// <summary>
        /// 清空 policy 内部 stable pose 和状态机。
        /// </summary>
        /// <param name="sampleTimeSeconds">Unity 单调时间，单位秒。</param>
        /// <param name="reason">清空原因。</param>
        public abstract void Clear(double sampleTimeSeconds, string reason);
    }
}

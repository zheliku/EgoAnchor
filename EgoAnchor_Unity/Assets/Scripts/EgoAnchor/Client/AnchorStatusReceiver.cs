using EgoAnchor.Runtime;
using EgoAnchor.Protocol.Generated;
using Google.Protobuf;
using UnityEngine;

namespace EgoAnchor.Client
{
    /// <summary>
    /// AnchorStatusEvent 接收器。
    ///
    /// 本类从 NatsControlClient 取出 status event bytes，在 Unity 主线程解析后
    /// 交给 AnchorRuntimeHub 广播给一个或多个 PoseToAnchorRuntime。它不直接修改 Transform。
    /// </summary>
    public sealed class AnchorStatusReceiver : NatsTypedReceiver<AnchorStatusEvent>
    {
        /// <summary>统一 anchor runtime 分发中心。</summary>
        [Header("Runtime")]
        [Tooltip("统一 anchor runtime 分发中心。应与 PoseResultReceiver 使用同一个 AnchorRuntimeHub。")]
        [SerializeField] private AnchorRuntimeHub runtimeHub;

        /// <summary>单帧最多处理多少条 status event。</summary>
        [Header("Drain")]
        [Tooltip("单帧最多处理多少条 AnchorStatusEvent，避免状态事件暴发时阻塞 Unity 主线程。")]
        [Min(1)]
        [SerializeField] private int maxEventsPerFrame = 8;

        /// <summary>累计分发给 runtime 的事件次数。</summary>
        private int dispatched;

        /// <summary>接收器日志名称。</summary>
        protected override string ReceiverName => nameof(AnchorStatusReceiver);

        /// <summary>AnchorStatusEvent Protobuf parser。</summary>
        protected override MessageParser<AnchorStatusEvent> Parser => AnchorStatusEvent.Parser;

        /// <summary>事件流单帧 drain 上限。</summary>
        protected override int MaxMessagesPerFrame => maxEventsPerFrame;

        /// <summary>runtime hub 未绑定时不消费 payload。</summary>
        protected override bool CanReceive => runtimeHub != null;

        /// <summary>聚合日志附加分发数量。</summary>
        protected override string ExtraStats => $"dispatched={dispatched}, hubRuntimes={runtimeHub.RuntimeCount}";

        /// <summary>
        /// 从 status event queue 取出一条 payload。
        /// </summary>
        protected override bool TryDequeueRaw(out byte[] payload, out int skippedOlderPayloads)
        {
            skippedOlderPayloads = 0;
            return NatsClient.TryDequeueStatusEvent(out payload);
        }

        /// <summary>
        /// 处理已解析 status event。
        /// </summary>
        protected override void OnParsed(AnchorStatusEvent message)
        {
            dispatched += runtimeHub.PublishStatus(message);
        }
    }
}

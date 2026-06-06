using EgoAnchor.Runtime;
using EgoAnchor.Protocol.Generated;
using Google.Protobuf;
using UnityEngine;

namespace EgoAnchor.Client
{
    /// <summary>
    /// ServerHeartbeat 接收器。
    ///
    /// 本类从 NatsControlClient 取出 latest-only heartbeat bytes，在 Unity 主线程解析后
    /// 交给 AnchorRuntimeHub 广播给 PoseToAnchorRuntime。它只处理链路健康状态。
    /// </summary>
    public sealed class ServerHeartbeatReceiver : NatsTypedReceiver<ServerHeartbeat>
    {
        /// <summary>统一 anchor runtime 分发中心。</summary>
        [Header("Runtime")]
        [Tooltip("统一 anchor runtime 分发中心。应与 PoseResultReceiver 使用同一个 AnchorRuntimeHub。")]
        [SerializeField] private AnchorRuntimeHub runtimeHub;

        /// <summary>累计分发给 runtime 的 heartbeat 次数。</summary>
        private int dispatched;

        /// <summary>接收器日志名称。</summary>
        protected override string ReceiverName => nameof(ServerHeartbeatReceiver);

        /// <summary>ServerHeartbeat Protobuf parser。</summary>
        protected override MessageParser<ServerHeartbeat> Parser => ServerHeartbeat.Parser;

        /// <summary>runtime hub 未绑定时不消费 payload。</summary>
        protected override bool CanReceive => runtimeHub != null;

        /// <summary>聚合日志附加分发数量。</summary>
        protected override string ExtraStats => $"dispatched={dispatched}, hubRuntimes={runtimeHub.RuntimeCount}";

        /// <summary>
        /// 从 latest-only heartbeat queue 取出最新 payload。
        /// </summary>
        protected override bool TryDequeueRaw(out byte[] payload, out int skippedOlderPayloads)
        {
            return NatsClient.TryDequeueLatestHeartbeat(out payload, out skippedOlderPayloads);
        }

        /// <summary>
        /// 处理已解析 heartbeat。
        /// </summary>
        protected override void OnParsed(ServerHeartbeat message)
        {
            dispatched += runtimeHub.PublishHeartbeat(message);
        }
    }
}

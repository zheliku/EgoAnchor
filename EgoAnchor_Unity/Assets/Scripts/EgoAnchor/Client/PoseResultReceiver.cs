using EgoAnchor.Runtime;
using EgoAnchor.Protocol.Generated;
using Google.Protobuf;
using UnityEngine;

namespace EgoAnchor.Client
{
    /// <summary>
    /// PoseResult 接收器。
    ///
    /// 本类属于 Client 层：它从 NatsControlClient 取出后台线程收到的 bytes，
    /// 在 Unity 主线程解析 Protobuf PoseResult，再交给 AnchorRuntimeHub 分发给
    /// 一个或多个 PoseToAnchorRuntime。本类不直接修改 Transform。
    /// </summary>
    public sealed class PoseResultReceiver : NatsTypedReceiver<PoseResult>
    {
        /// <summary>PoseResult 分发中心。</summary>
        [Header("Runtime")]
        [Tooltip("Anchor runtime 分发中心。负责把同一条 PoseResult 广播给一个或多个 PoseToAnchorRuntime。")]
        [SerializeField] private AnchorRuntimeHub runtimeHub;

        /// <summary>PoseResult Protobuf parser。</summary>
        protected override MessageParser<PoseResult> Parser => PoseResult.Parser;

        /// <summary>runtime hub 未绑定时不消费 payload。</summary>
        protected override bool CanReceive => runtimeHub != null;

        /// <summary>聚合日志附加 runtime 数量。</summary>
        protected override string ExtraStats => $"hubRuntimes={(runtimeHub == null ? 0 : runtimeHub.RuntimeCount)}";

        /// <summary>
        /// 从 latest-only pose queue 取出最新 payload。
        /// </summary>
        protected override bool TryDequeueRaw(out byte[] payload, out int skippedOlderPayloads)
        {
            return NatsClient.TryDequeueLatestPoseResult(out payload, out skippedOlderPayloads);
        }

        /// <summary>
        /// 把 PoseResult 广播给所有 runtime。
        /// </summary>
        protected override void OnParsed(PoseResult message)
        {
            runtimeHub.Publish(message);
        }
    }
}

using EgoAnchor.Anchor;
using EgoAnchor.Protocol.Generated;
using EgoAnchor.Transport;
using Google.Protobuf;
using UnityEngine;

namespace EgoAnchor.Client
{
    /// <summary>
    /// ServerHeartbeat 接收器。
    ///
    /// 本类从 NatsControlClient 取出 latest-only heartbeat bytes，在 Unity 主线程解析后
    /// 交给 AnchorRuntimeHub 广播给 PoseToAnchorRuntime。它只处理链路健康状态，不修改 Transform，也不发送命令。
    /// </summary>
    public sealed class ServerHeartbeatReceiver : MonoBehaviour
    {
        /// <summary>NATS 消息面客户端。</summary>
        [Header("Inputs")]
        [Tooltip("NATS 消息面客户端。只负责连接和 heartbeat payload 队列，不直接解码 Protobuf。")]
        [SerializeField] private NatsControlClient natsClient;

        /// <summary>统一 anchor runtime 分发中心。</summary>
        [Tooltip("统一 anchor runtime 分发中心。应与 PoseResultReceiver 使用同一个 AnchorRuntimeHub，保持 pose/status/heartbeat 广播目标一致。")]
        [SerializeField] private AnchorRuntimeHub runtimeHub;

        /// <summary>是否输出聚合统计。</summary>
        [Header("Debug")]
        [Tooltip("是否输出 ServerHeartbeat 解码/分发统计。")]
        [SerializeField] private bool logStats = true;

        /// <summary>统计输出间隔。</summary>
        [Tooltip("每处理多少条 heartbeat 打印一次统计。")]
        [Min(1)]
        [SerializeField] private int statsIntervalMessages = 30;

        /// <summary>累计成功解码 heartbeat 数。</summary>
        private int decoded;

        /// <summary>累计 Protobuf 解码失败数。</summary>
        private int parseFailed;

        /// <summary>latest-only 消费跳过的旧 heartbeat 数。</summary>
        private int skippedOlder;

        /// <summary>累计分发给 runtime 的 heartbeat 次数。</summary>
        private int dispatched;

        /// <summary>上次打印统计时的总处理数。</summary>
        private int lastLoggedTotal;

        /// <summary>
        /// Unity Update：主线程 latest-drain、解析 heartbeat 并广播。
        /// </summary>
        private void Update()
        {
            if (natsClient == null || runtimeHub == null)
            {
                return;
            }

            if (!natsClient.TryDequeueLatestHeartbeat(out byte[] payload, out int skippedOlderPayloads))
            {
                return;
            }

            skippedOlder += skippedOlderPayloads;
            try
            {
                ServerHeartbeat heartbeat = ServerHeartbeat.Parser.ParseFrom(payload);
                decoded++;
                Publish(heartbeat);
            }
            catch (InvalidProtocolBufferException ex)
            {
                parseFailed++;
                Debug.LogWarning($"[ServerHeartbeatReceiver] ServerHeartbeat Protobuf 解码失败：{ex.Message}", this);
            }

            MaybeLogStats();
        }

        /// <summary>
        /// 把一条 heartbeat 广播给所有 runtime。
        /// </summary>
        /// <param name="heartbeat">Python 发布的 ServerHeartbeat。</param>
        public void Publish(ServerHeartbeat heartbeat)
        {
            dispatched += runtimeHub.PublishHeartbeat(heartbeat);
        }

        /// <summary>
        /// 周期性输出接收和分发统计。
        /// </summary>
        private void MaybeLogStats()
        {
            if (!logStats)
            {
                return;
            }

            int total = decoded + parseFailed;
            if (total > 0 && total - lastLoggedTotal >= statsIntervalMessages)
            {
                lastLoggedTotal = total;
                Debug.Log(
                    $"[ServerHeartbeatReceiver] decoded={decoded}, parseFailed={parseFailed}, skippedOlder={skippedOlder}, " +
                    $"dispatched={dispatched}, hubRuntimes={runtimeHub.RuntimeCount}",
                    this
                );
            }
        }
    }
}

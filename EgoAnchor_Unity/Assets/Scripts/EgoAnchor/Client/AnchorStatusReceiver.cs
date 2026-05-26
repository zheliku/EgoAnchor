using EgoAnchor.Anchor;
using EgoAnchor.Protocol.Generated;
using EgoAnchor.Transport;
using Google.Protobuf;
using UnityEngine;

namespace EgoAnchor.Client
{
    /// <summary>
    /// AnchorStatusEvent 接收器。
    ///
    /// 本类属于 Client 层：它从 NatsControlClient 取出 status event bytes，
    /// 在 Unity 主线程解析 Protobuf，再交给 AnchorRuntimeHub 广播给一个或多个 PoseToAnchorRuntime。
    /// 它不直接修改 Transform，不执行网络请求，也不运行滤波算法。
    /// </summary>
    public sealed class AnchorStatusReceiver : MonoBehaviour
    {
        /// <summary>NATS 消息面客户端。</summary>
        [Header("Inputs")]
        [Tooltip("NATS 消息面客户端。只负责连接和 payload 队列，不直接解码 Protobuf。")]
        [SerializeField] private NatsControlClient natsClient;

        /// <summary>统一 anchor runtime 分发中心。</summary>
        [Tooltip("统一 anchor runtime 分发中心。应与 PoseResultReceiver 使用同一个 AnchorRuntimeHub，保持 pose/status/heartbeat 广播目标一致。")]
        [SerializeField] private AnchorRuntimeHub runtimeHub;

        /// <summary>单帧最多处理多少条 status event。</summary>
        [Header("Drain")]
        [Tooltip("单帧最多处理多少条 AnchorStatusEvent，避免状态事件暴发时阻塞 Unity 主线程。")]
        [Min(1)]
        [SerializeField] private int maxEventsPerFrame = 8;

        /// <summary>是否输出聚合统计。</summary>
        [Header("Debug")]
        [Tooltip("是否输出 AnchorStatusEvent 解码/分发统计。")]
        [SerializeField] private bool logStats = true;

        /// <summary>统计输出间隔。</summary>
        [Tooltip("每处理多少条 status event 打印一次统计。")]
        [Min(1)]
        [SerializeField] private int statsIntervalMessages = 30;

        /// <summary>累计成功解码事件数。</summary>
        private int decoded;

        /// <summary>累计 Protobuf 解码失败数。</summary>
        private int parseFailed;

        /// <summary>累计分发给 runtime 的事件次数。</summary>
        private int dispatched;

        /// <summary>上次打印统计时的处理数量。</summary>
        private int lastLoggedTotal;

        /// <summary>
        /// Unity Update：主线程 drain status event、解析并广播。
        /// </summary>
        private void Update()
        {
            if (natsClient == null || runtimeHub == null)
            {
                return;
            }

            int processedThisFrame = 0;
            while (processedThisFrame < maxEventsPerFrame && natsClient.TryDequeueStatusEvent(out byte[] payload))
            {
                processedThisFrame++;
                try
                {
                    AnchorStatusEvent status = AnchorStatusEvent.Parser.ParseFrom(payload);
                    decoded++;
                    Publish(status);
                }
                catch (InvalidProtocolBufferException ex)
                {
                    parseFailed++;
                    Debug.LogWarning($"[AnchorStatusReceiver] AnchorStatusEvent Protobuf 解码失败：{ex.Message}", this);
                }
            }

            if (processedThisFrame > 0)
            {
                MaybeLogStats();
            }
        }

        /// <summary>
        /// 把一条 status event 广播给所有 runtime。
        /// </summary>
        /// <param name="status">Python 发布的 AnchorStatusEvent。</param>
        public void Publish(AnchorStatusEvent status)
        {
            dispatched += runtimeHub.PublishStatus(status);
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
                    $"[AnchorStatusReceiver] decoded={decoded}, parseFailed={parseFailed}, dispatched={dispatched}, " +
                    $"hubRuntimes={runtimeHub.RuntimeCount}",
                    this
                );
            }
        }
    }
}

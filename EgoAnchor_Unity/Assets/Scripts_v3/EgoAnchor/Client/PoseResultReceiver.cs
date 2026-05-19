using EgoAnchor.V3.Anchor;
using EgoAnchor.V3.Protocol.Generated;
using EgoAnchor.V3.Transport;
using Google.Protobuf;
using UnityEngine;

namespace EgoAnchor.V3.Client
{
    /// <summary>
    /// v3 PoseResult 接收器。
    ///
    /// 本类属于 Client 层：它从 NatsControlClient 取出后台线程收到的 bytes，
    /// 在 Unity 主线程解析 Protobuf PoseResult，再交给 Anchor/PoseResultHub 分发给
    /// 一个或多个 PoseToAnchorRuntime。
    ///
    /// 本类不直接修改 Transform，也不持有滤波/状态机；Transform 应用由 DynamicObjectAnchor 完成。
    /// baseline 对照时，场景中只需要一个 PoseResultReceiver，一个 PoseResultHub 可以广播到
    /// raw runtime 与 smoothed runtime。
    /// </summary>
    public sealed class PoseResultReceiver : MonoBehaviour
    {
        /// <summary>NATS 消息面客户端。</summary>
        [Header("Inputs")]
        [Tooltip("NATS 消息面客户端。只负责连接和 payload 队列，不直接解码 Protobuf。")]
        [SerializeField] private NatsControlClient natsClient;

        /// <summary>PoseResult 分发中心。</summary>
        [Tooltip("PoseResult 分发中心。负责把同一条 PoseResult 广播给一个或多个 PoseToAnchorRuntime。")]
        [SerializeField] private PoseResultHub poseResultHub;

        /// <summary>是否输出聚合统计。</summary>
        [Header("Debug")]
        [Tooltip("是否输出 PoseResult 解码/对齐统计。默认只输出聚合统计。")]
        [SerializeField] private bool logStats = true;

        /// <summary>统计输出间隔。</summary>
        [Tooltip("每处理多少条 payload 打印一次统计。")]
        [Min(1)]
        [SerializeField] private int statsIntervalMessages = 120;

        /// <summary>累计成功解码 PoseResult 数。</summary>
        private int decoded;

        /// <summary>累计 Protobuf 解码失败数。</summary>
        private int parseFailed;

        /// <summary>latest-only 消费跳过的旧 payload 数。</summary>
        private int skippedOlder;

        /// <summary>上次打印统计时的总处理数。</summary>
        private int lastLoggedTotal;

        /// <summary>
        /// Unity Update：主线程 latest-drain、解析 PoseResult 并交给 anchor runtime。
        /// </summary>
        private void Update()
        {
            if (natsClient == null || poseResultHub == null)
            {
                return;
            }

            if (!natsClient.TryDequeueLatestPoseResult(out byte[] payload, out int skippedOlderPayloads))
            {
                return;
            }

            skippedOlder += skippedOlderPayloads;
            try
            {
                PoseResult result = PoseResult.Parser.ParseFrom(payload);
                decoded++;
                poseResultHub.Publish(result);
            }
            catch (InvalidProtocolBufferException ex)
            {
                parseFailed++;
                Debug.LogWarning($"[PoseResultReceiver:v3] PoseResult Protobuf 解码失败：{ex.Message}", this);
            }

            MaybeLogStats();
        }

        /// <summary>
        /// 周期性输出 PoseResult 接收和对齐统计。
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
                    $"[PoseResultReceiver:v3] decoded={decoded}, parseFailed={parseFailed}, " +
                    $"skippedOlder={skippedOlder}, hubRuntimes={poseResultHub.RuntimeCount}",
                    this
                );
            }
        }
    }
}

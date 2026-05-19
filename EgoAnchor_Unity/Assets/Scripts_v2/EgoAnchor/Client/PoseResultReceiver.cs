using EgoAnchor.Protocol.V1;
using EgoAnchor.V2.Anchor;
using EgoAnchor.V2.Transport;
using Google.Protobuf;
using UnityEngine;

namespace EgoAnchor.V2.Client
{
    /// <summary>
    /// v2 PoseResult 接收器。
    ///
    /// 本类属于 Client 层：后续负责把 NATS control plane 收到的 PoseResult 转成 Unity 主线程事件，
    /// 再交给 Anchor/PoseToAnchorRuntime。它不应直接修改场景 Transform，也不应自己持有滤波/状态机。
    ///
    /// 当前职责：
    /// - 从 NatsControlClient 取出后台线程收到的 PoseResult payload。
    /// - 在 Unity 主线程解码 Protobuf PoseResult。
    /// - 把 pose observation 交给 PoseToAnchorRuntime 做 frame-aligned anchor 对齐。
    /// - has_pose=false 时不应用 transform，但仍应把状态/失败原因交给 anchor runtime。
    ///
    /// 当前视频流 demo 不启用该组件，避免把数据面验证和 anchor runtime 混在一起。
    /// </summary>
    public sealed class PoseResultReceiver : MonoBehaviour
    {
        [Header("Inputs")]
        [Tooltip("NATS 控制面客户端。只负责连接和 payload 队列，不直接解码 Protobuf。")]
        [SerializeField] private NatsControlClient natsClient;

        [Tooltip("Pose-to-Anchor runtime。负责 frame_id 对齐、OpenCV->Unity 坐标转换、raw/smoothed pose 维护。")]
        [SerializeField] private PoseToAnchorRuntime anchorRuntime;

        [Header("Debug")]
        [Tooltip("是否输出 PoseResult 解码/对齐统计。默认只输出聚合统计。")]
        [SerializeField] private bool logStats = true;

        [Tooltip("每处理多少条 payload 打印一次统计。")]
        [Min(1)]
        [SerializeField] private int statsIntervalMessages = 120;

        private int _decoded;
        private int _parseFailed;
        private int _noPose;
        private int _aligned;
        private int _alignFailed;
        private int _skippedOlder;
        private int _lastLoggedTotal;

        private void Update()
        {
            if (natsClient == null || anchorRuntime == null)
            {
                return;
            }

            if (!natsClient.TryDequeueLatestPoseResult(out byte[] payload, out int skippedOlderPayloads))
            {
                return;
            }

            _skippedOlder += skippedOlderPayloads;
            try
            {
                PoseResult result = PoseResult.Parser.ParseFrom(payload);
                _decoded++;

                PoseToAnchorRuntime.AcceptResult acceptResult = anchorRuntime.AcceptPoseResult(result);
                switch (acceptResult)
                {
                    case PoseToAnchorRuntime.AcceptResult.Aligned:
                        _aligned++;
                        break;
                    case PoseToAnchorRuntime.AcceptResult.NoPose:
                        _noPose++;
                        break;
                    case PoseToAnchorRuntime.AcceptResult.AlignFailed:
                    case PoseToAnchorRuntime.AcceptResult.InvalidMatrix:
                        _alignFailed++;
                        break;
                }
            }
            catch (InvalidProtocolBufferException ex)
            {
                _parseFailed++;
                Debug.LogWarning($"[PoseResultReceiver] PoseResult Protobuf 解码失败：{ex.Message}", this);
            }

            MaybeLogStats();
        }

        private void MaybeLogStats()
        {
            if (!logStats)
            {
                return;
            }

            int total = _decoded + _parseFailed;
            if (total > 0 && total - _lastLoggedTotal >= statsIntervalMessages)
            {
                _lastLoggedTotal = total;
                Debug.Log(
                    $"[PoseResultReceiver] decoded={_decoded}, parseFailed={_parseFailed}, noPose={_noPose}, " +
                    $"aligned={_aligned}, alignFailed={_alignFailed}, skippedOlder={_skippedOlder}",
                    this
                );
            }
        }
    }
}

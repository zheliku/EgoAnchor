using System;
using System.Threading;
using System.Threading.Tasks;
using EgoAnchor.Protocol.V1;
using EgoAnchor.V2.Protocol;
using EgoAnchor.V2.Transport;
using Google.Protobuf;
using UnityEngine;

namespace EgoAnchor.V2.Client
{
    /// <summary>
    /// Unity 侧 anchor 控制 API。
    ///
    /// 这是给交互层/UI/ContextMenu 使用的业务组件，负责把“重置/重新获取/控制”
    /// 这类操作封装成 v2 Protobuf command，并通过 NatsConnection 发送 request/reply。
    ///
    /// 注意：CommandAck 只代表 Python server 已接受或拒绝该命令，不代表 tracking 已完成。
    /// 后续真正状态变化应通过 AnchorStatusEvent 或 PoseResult 观察。
    /// </summary>
    public class AnchorControlApi : MonoBehaviour
    {
        [SerializeField] private NatsConnection connection;
        [SerializeField] private string clientId = "unity";
        [SerializeField] private string defaultAnchorId = "main";
        [SerializeField] private float requestTimeoutSeconds = 2f;

        public async Task<CommandAck> ResetTrackingAsync(string anchorId, CancellationToken cancellationToken)
        {
            // reset 的第一版语义：清空当前 tracking/filter/anchor pose，等待后续帧重新 register。
            ResetTrackingRequest request = new ResetTrackingRequest
            {
                Header = CreateHeader(anchorId),
                ClearFilters = true,
                ClearAnchorPose = true,
                Reason = "unity-api",
            };
            return await SendCommandAsync(SubjectNames.ResetTracking, request.ToByteArray(), cancellationToken);
        }

        public async Task<CommandAck> ReacquireAsync(string anchorId, ReacquireAnchorRequest.Types.ReacquireMode mode, CancellationToken cancellationToken)
        {
            // reacquire 比 reset 更面向用户交互；当前 Python 侧第一版会先等价映射为 reset。
            ReacquireAnchorRequest request = new ReacquireAnchorRequest
            {
                Header = CreateHeader(anchorId),
                Mode = mode,
                ClearTrackingFirst = true,
                TimeoutMs = requestTimeoutSeconds * 1000.0,
            };
            return await SendCommandAsync(SubjectNames.ReacquireAnchor, request.ToByteArray(), cancellationToken);
        }

        public async Task<CommandAck> SetAnchorControlAsync(AnchorControlRequest request, CancellationToken cancellationToken)
        {
            // 外部传入自定义 control request 时，补齐幂等所需 request_id。
            if (request.Header == null)
            {
                request.Header = CreateHeader(defaultAnchorId);
            }
            else if (string.IsNullOrEmpty(request.Header.RequestId))
            {
                request.Header.RequestId = Guid.NewGuid().ToString("N");
            }

            return await SendCommandAsync(SubjectNames.AnchorControl, request.ToByteArray(), cancellationToken);
        }

        [ContextMenu("V2 Reset Tracking")]
        public async void ResetTrackingFromContextMenu()
        {
            // 手动 smoke test 入口：在 Inspector 右键组件即可发一个 reset request。
            try
            {
                using CancellationTokenSource cts = new CancellationTokenSource(TimeSpan.FromSeconds(requestTimeoutSeconds));
                CommandAck ack = await ResetTrackingAsync(defaultAnchorId, cts.Token);
                Debug.Log($"[EgoAnchorV2] Reset ack accepted={ack.Accepted} duplicate={ack.Duplicate} status={ack.Status} requestId={ack.Header.RequestId}", this);
            }
            catch (Exception e)
            {
                Debug.LogError($"[EgoAnchorV2] Reset request failed: {e.Message}", this);
            }
        }

        private MessageHeader CreateHeader(string anchorId)
        {
            // 每个命令必须有 request_id。重试同一命令时应该复用 request_id；
            // 这里 ContextMenu/API 默认每次调用创建新的 request_id。
            double nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            return new MessageHeader
            {
                MessageId = Guid.NewGuid().ToString("N"),
                RequestId = Guid.NewGuid().ToString("N"),
                ClientId = clientId,
                AnchorId = string.IsNullOrEmpty(anchorId) ? defaultAnchorId : anchorId,
                CreatedUnixMs = nowMs,
                SenderMonoMs = Time.realtimeSinceStartupAsDouble * 1000.0,
                SchemaVersion = "v1",
            };
        }

        private async Task<CommandAck> SendCommandAsync(string subject, byte[] payload, CancellationToken cancellationToken)
        {
            // 统一处理 command timeout 与 protobuf ack 解析。
            if (connection == null)
            {
                throw new InvalidOperationException("NatsConnection is not assigned.");
            }

            using CancellationTokenSource timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            timeout.CancelAfter(TimeSpan.FromSeconds(requestTimeoutSeconds));
            byte[] response = await connection.RequestAsync(subject, payload, timeout.Token);
            return CommandAck.Parser.ParseFrom(response);
        }
    }
}

using System;
using System.Threading;
using System.Threading.Tasks;
using EgoAnchor.V3.Anchor;
using EgoAnchor.V3.Protocol;
using EgoAnchor.V3.Protocol.Generated;
using EgoAnchor.V3.Transport;
using Google.Protobuf;
using UnityEngine;

namespace EgoAnchor.V3.Client
{
    /// <summary>
    /// v3 Anchor 命令客户端。
    ///
    /// 本类是 Unity 侧控制 pose 估计流程的公开 API 层：
    /// - ResetTracking：让 Python runtime 在主循环边界重置 FoundationPose/Cutie 跟踪状态。
    /// - Reacquire：请求 Python 主动重新获取目标，必要时先清空旧 tracking 状态。
    /// - Pause/Resume：暂停或恢复 Python pipeline 处理新帧。
    /// - SetStage：远程切换 Python debug stage，替代只能在 Python OpenCV 窗口按 1/2/3/4。
    ///
    /// 本类只构造 typed Protobuf command，并通过 NatsControlClient 发送 request/reply；
    /// 它不直接操作 Python 模型，也不直接解析 PoseResult。
    /// </summary>
    public sealed class AnchorCommandClient : MonoBehaviour
    {
        /// <summary>NATS 消息面客户端。</summary>
        [Header("Transport")]
        [Tooltip("NATS 消息面客户端。必须与 PoseResultReceiver 使用同一个 NATS server。")]
        [SerializeField] private NatsControlClient natsClient;

        /// <summary>Unity command client id。</summary>
        [Tooltip("写入 MessageHeader.client_id 的 Unity 客户端标识，便于 Python/NATS 日志排查。")]
        [SerializeField] private string clientId = "egoanchor-unity-v3";

        /// <summary>目标 anchor id。</summary>
        [Tooltip("写入 MessageHeader.anchor_id 的目标 anchor 标识。当前单目标链路默认 default。")]
        [SerializeField] private string anchorId = "default";

        /// <summary>命令 request/reply 超时时间。</summary>
        [Header("Command")]
        [Tooltip("等待 NATS 连接和 Python CommandAck 的超时时间，单位秒。ack 只表示命令已接受或拒绝，不表示重定位已经完成。")]
        [Min(0.1f)]
        [SerializeField] private float requestTimeoutSeconds = 1.5f;

        /// <summary>Unity 默认 reset 是否清理本地 anchor processor。</summary>
        [Tooltip("ResetTracking() 默认是否在 Python ack accepted 后清理本地 anchor processor。Python 只重置 pose 估计；Unity 本地滤波状态需要在本侧清理。")]
        [SerializeField] private bool resetLocalFiltersOnAccepted = true;

        /// <summary>Unity 默认 reset 是否清空本地 anchor pose。</summary>
        [Tooltip("ResetTracking() 默认是否在 Python ack accepted 后清空本地 raw/stable anchor pose，避免旧 anchor 在重新检测期间继续显示。")]
        [SerializeField] private bool clearLocalAnchorPoseOnAccepted = false;

        /// <summary>可选本地 anchor runtime 列表。</summary>
        [Tooltip("可选本地 PoseToAnchorRuntime 列表。Python ack accepted 后，可按 reset request 字段同步清理本地滤波/pose 状态。")]
        [SerializeField] private PoseToAnchorRuntime[] localAnchorRuntimes;

        /// <summary>是否输出每条命令的 ack 日志。</summary>
        [Header("Debug")]
        [Tooltip("是否输出每条 command ack。调试 UI 按钮时建议开启；正式高频操作时可关闭。")]
        [SerializeField] private bool logCommandAck = true;

        /// <summary>本次 Unity command session id。</summary>
        [Tooltip("本次 Unity command session id，只用于 Inspector 诊断。")]
        [SerializeField] private string sessionId = "";

        /// <summary>最近一次 request_id。</summary>
        [Tooltip("最近一次 command request_id，只用于 Inspector 诊断。")]
        [SerializeField] private string lastRequestId = "";

        /// <summary>最近一次 command subject。</summary>
        [Tooltip("最近一次 command subject，只用于 Inspector 诊断。")]
        [SerializeField] private string lastSubject = "";

        /// <summary>最近一次 ack accepted。</summary>
        [Tooltip("最近一次 CommandAck.accepted，只用于 Inspector 诊断。")]
        [SerializeField] private bool lastAccepted;

        /// <summary>最近一次 ack duplicate。</summary>
        [Tooltip("最近一次 CommandAck.duplicate，只用于 Inspector 诊断。")]
        [SerializeField] private bool lastDuplicate;

        /// <summary>最近一次 ack status。</summary>
        [Tooltip("最近一次 CommandAck.status，只用于 Inspector 诊断。")]
        [SerializeField] private string lastStatus = "";

        /// <summary>最近一次 ack message 或异常文本。</summary>
        [Tooltip("最近一次 CommandAck.message 或异常文本，只用于 Inspector 诊断。")]
        [SerializeField] private string lastMessage = "";

        /// <summary>累计发送命令数。</summary>
        private int sentCommands;

        /// <summary>累计 accepted ack 数。</summary>
        private int acceptedAcks;

        /// <summary>累计 rejected ack 数。</summary>
        private int rejectedAcks;

        /// <summary>累计异常/超时数。</summary>
        private int failedCommands;

        /// <summary>最近一次 reset request；收到 ack 后用于决定是否清理本地 anchor 状态。</summary>
        private ResetTrackingRequest pendingResetForLocalApply;

        /// <summary>最近一次 request 取消源。</summary>
        private CancellationTokenSource requestCts;

        /// <summary>累计发送命令数。</summary>
        public int SentCommands => sentCommands;

        /// <summary>累计 accepted ack 数。</summary>
        public int AcceptedAcks => acceptedAcks;

        /// <summary>累计 rejected ack 数。</summary>
        public int RejectedAcks => rejectedAcks;

        /// <summary>累计异常/超时数。</summary>
        public int FailedCommands => failedCommands;

        /// <summary>最近一次 ack status。</summary>
        public string LastStatus => lastStatus;

        /// <summary>最近一次 ack message 或异常文本。</summary>
        public string LastMessage => lastMessage;

        /// <summary>
        /// Unity Awake：补齐 session id 与默认 NatsControlClient 引用。
        /// </summary>
        private void Awake()
        {
            if (string.IsNullOrWhiteSpace(sessionId))
            {
                sessionId = Guid.NewGuid().ToString("N");
            }

            if (natsClient == null)
            {
                natsClient = GetComponent<NatsControlClient>();
            }
        }

        /// <summary>
        /// Inspector 修改时保持数组非空，避免审阅诊断时出现 null。
        /// </summary>
        private void OnValidate()
        {
            if (localAnchorRuntimes == null)
            {
                localAnchorRuntimes = Array.Empty<PoseToAnchorRuntime>();
            }
        }

        /// <summary>
        /// UnityEvent/Button 入口：按默认配置请求 Python 重置 pose 估计。
        /// </summary>
        public void ResetTracking()
        {
            _ = ResetTrackingAsync(resetLocalFiltersOnAccepted, clearLocalAnchorPoseOnAccepted, "unity_reset_button");
        }

        /// <summary>
        /// UnityEvent/Button 入口：请求 Python 清空旧 tracking 后强制重新检测/register。
        /// </summary>
        public void ForceReacquire()
        {
            _ = ReacquireAsync(ReacquireAnchorRequest.Types.ReacquireMode.ForceDetect, true, string.Empty, 0.0, "unity_force_reacquire_button");
        }

        /// <summary>
        /// UnityEvent/Button 入口：请求 Python 使用下一帧有效输入重新获取目标。
        /// </summary>
        public void ReacquireNextValidFrame()
        {
            _ = ReacquireAsync(ReacquireAnchorRequest.Types.ReacquireMode.NextValidFrame, false, string.Empty, 0.0, "unity_reacquire_next_button");
        }

        /// <summary>
        /// UnityEvent/Button 入口：暂停 Python pose pipeline 处理新图像。
        /// </summary>
        public void PauseTracking()
        {
            _ = ControlAsync(AnchorControlRequest.Types.ControlAction.Pause, 0, "unity_pause_button");
        }

        /// <summary>
        /// UnityEvent/Button 入口：恢复 Python pose pipeline 处理新图像。
        /// </summary>
        public void ResumeTracking()
        {
            _ = ControlAsync(AnchorControlRequest.Types.ControlAction.Resume, 0, "unity_resume_button");
        }

        /// <summary>
        /// UnityEvent/Button 入口：切换 Python debug stage。
        /// </summary>
        /// <param name="stage">目标 stage，合法范围 1..4。</param>
        public void SetStage(int stage)
        {
            _ = ControlAsync(AnchorControlRequest.Types.ControlAction.SetStage, stage, $"unity_set_stage_{stage}");
        }

        /// <summary>UnityEvent/Button 入口：切换到 stage 1 输入视图。</summary>
        public void SetStage1()
        {
            SetStage(1);
        }

        /// <summary>UnityEvent/Button 入口：切换到 stage 2 mask 视图。</summary>
        public void SetStage2()
        {
            SetStage(2);
        }

        /// <summary>UnityEvent/Button 入口：切换到 stage 3 depth 视图。</summary>
        public void SetStage3()
        {
            SetStage(3);
        }

        /// <summary>UnityEvent/Button 入口：切换到 stage 4 完整 pose 视图。</summary>
        public void SetStage4()
        {
            SetStage(4);
        }

        /// <summary>
        /// 发送 ResetTrackingRequest，并等待 Python CommandAck。
        /// </summary>
        /// <param name="clearFilters">ack accepted 后是否清理 Unity 本地 processor。</param>
        /// <param name="clearAnchorPose">ack accepted 后是否清空 Unity 本地 anchor pose。</param>
        /// <param name="reason">命令原因，写入 request.reason 便于日志排查。</param>
        /// <param name="token">外部取消信号。</param>
        /// <returns>Python 返回的 CommandAck；异常时返回 null。</returns>
        public async Task<CommandAck> ResetTrackingAsync(bool clearFilters, bool clearAnchorPose, string reason = "unity_api", CancellationToken token = default)
        {
            ResetTrackingRequest request = new ResetTrackingRequest
            {
                Header = BuildHeader("reset"),
                ClearFilters = clearFilters,
                ClearAnchorPose = clearAnchorPose,
                Reason = reason ?? string.Empty,
            };
            pendingResetForLocalApply = request;
            return await SendCommandAsync(SubjectNames.ResetTracking, request, token);
        }

        /// <summary>
        /// 发送 ReacquireAnchorRequest，并等待 Python CommandAck。
        /// </summary>
        /// <param name="mode">重获取模式。</param>
        /// <param name="clearTrackingFirst">Python 执行 reacquire 前是否先清空旧 tracking 状态。</param>
        /// <param name="promptOverride">可选 prompt 覆盖；当前 Python v3 仅透传保留，不动态改 YOLOE prompt。</param>
        /// <param name="timeoutMs">重获取超时语义预留；当前 ack 不等待执行完成。</param>
        /// <param name="reason">命令原因，写入 header/message 日志。</param>
        /// <param name="token">外部取消信号。</param>
        /// <returns>Python 返回的 CommandAck；异常时返回 null。</returns>
        public async Task<CommandAck> ReacquireAsync(
            ReacquireAnchorRequest.Types.ReacquireMode mode,
            bool clearTrackingFirst,
            string promptOverride = "",
            double timeoutMs = 0.0,
            string reason = "unity_api",
            CancellationToken token = default)
        {
            ReacquireAnchorRequest request = new ReacquireAnchorRequest
            {
                Header = BuildHeader("reacquire"),
                Mode = mode,
                ClearTrackingFirst = clearTrackingFirst,
                PromptOverride = promptOverride ?? string.Empty,
                TimeoutMs = timeoutMs,
            };
            request.Header.MessageId = $"{request.Header.MessageId}_{reason ?? string.Empty}";
            return await SendCommandAsync(SubjectNames.ReacquireAnchor, request, token);
        }

        /// <summary>
        /// 发送 AnchorControlRequest，并等待 Python CommandAck。
        /// </summary>
        /// <param name="action">控制动作：SET_STAGE/PAUSE/RESUME。</param>
        /// <param name="stage">SET_STAGE 时使用的目标 stage；其它 action 可传 0。</param>
        /// <param name="reason">命令原因。</param>
        /// <param name="token">外部取消信号。</param>
        /// <returns>Python 返回的 CommandAck；异常时返回 null。</returns>
        public async Task<CommandAck> ControlAsync(
            AnchorControlRequest.Types.ControlAction action,
            int stage = 0,
            string reason = "unity_api",
            CancellationToken token = default)
        {
            AnchorControlRequest request = new AnchorControlRequest
            {
                Header = BuildHeader("control"),
                Action = action,
                Stage = stage,
                Reason = reason ?? string.Empty,
            };
            return await SendCommandAsync(SubjectNames.AnchorControl, request, token);
        }

        /// <summary>
        /// 取消最近一次仍在等待的 command request。
        /// </summary>
        public void CancelPendingCommand()
        {
            try
            {
                requestCts?.Cancel();
            }
            catch
            {
                // 取消路径不应影响 Unity 主循环。
            }
        }

        /// <summary>
        /// 统一发送 typed protobuf command，并解析 CommandAck。
        /// </summary>
        /// <param name="subject">NATS command subject。</param>
        /// <param name="request">typed protobuf request。</param>
        /// <param name="token">外部取消信号。</param>
        /// <returns>CommandAck；发送失败时返回 null。</returns>
        private async Task<CommandAck> SendCommandAsync(string subject, IMessage request, CancellationToken token)
        {
            if (natsClient == null)
            {
                RecordFailure(subject, "missing_nats_control_client");
                return null;
            }

            using CancellationTokenSource linkedCts = CancellationTokenSource.CreateLinkedTokenSource(token);
            requestCts = linkedCts;
            MessageHeader header = ExtractHeader(request);
            lastRequestId = header?.RequestId ?? string.Empty;
            lastSubject = subject;
            sentCommands++;

            try
            {
                byte[] replyPayload = await natsClient.RequestAsync(subject, request.ToByteArray(), requestTimeoutSeconds, linkedCts.Token);
                CommandAck ack = CommandAck.Parser.ParseFrom(replyPayload);
                ApplyAck(subject, ack);
                return ack;
            }
            catch (Exception ex)
            {
                RecordFailure(subject, ex.Message);
                return null;
            }
            finally
            {
                if (ReferenceEquals(requestCts, linkedCts))
                {
                    requestCts = null;
                }
            }
        }

        /// <summary>
        /// 构造统一 MessageHeader。
        /// </summary>
        /// <param name="commandName">命令名，用于 request_id 前缀。</param>
        /// <returns>带 message_id/request_id/session/client/anchor/time 的 header。</returns>
        private MessageHeader BuildHeader(string commandName)
        {
            string id = Guid.NewGuid().ToString("N");
            return new MessageHeader
            {
                MessageId = id,
                RequestId = $"unity-{commandName}-{id}",
                SessionId = sessionId,
                ClientId = clientId,
                AnchorId = anchorId,
                UnityFrame = Time.frameCount,
                SenderMonoMs = Time.realtimeSinceStartupAsDouble * 1000.0,
                CreatedUnixMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                SchemaVersion = "v1",
            };
        }

        /// <summary>
        /// 从 protobuf request 中读取 header，便于统一诊断。
        /// </summary>
        /// <param name="request">typed protobuf request。</param>
        /// <returns>request.header；没有 header 时返回 null。</returns>
        private static MessageHeader ExtractHeader(IMessage request)
        {
            switch (request)
            {
                case ResetTrackingRequest reset:
                    return reset.Header;
                case ReacquireAnchorRequest reacquire:
                    return reacquire.Header;
                case AnchorControlRequest control:
                    return control.Header;
                default:
                    return null;
            }
        }

        /// <summary>
        /// 记录 Python CommandAck，并按需同步清理本地 anchor 状态。
        /// </summary>
        /// <param name="subject">对应 command subject。</param>
        /// <param name="ack">Python 返回的 ack。</param>
        private void ApplyAck(string subject, CommandAck ack)
        {
            lastAccepted = ack != null && ack.Accepted;
            lastDuplicate = ack != null && ack.Duplicate;
            lastStatus = ack?.Status ?? "EMPTY_ACK";
            lastMessage = ack?.Message ?? string.Empty;

            if (lastAccepted)
            {
                acceptedAcks++;
                if (subject == SubjectNames.ResetTracking)
                {
                    ApplyAcceptedResetLocally(pendingResetForLocalApply);
                }
            }
            else
            {
                rejectedAcks++;
            }

            if (logCommandAck)
            {
                Debug.Log(
                    $"[AnchorCommandClient:v3] subject={subject}, request_id={lastRequestId}, " +
                    $"accepted={lastAccepted}, duplicate={lastDuplicate}, status={lastStatus}, message={lastMessage}",
                    this
                );
            }
        }

        /// <summary>
        /// 记录命令发送异常或超时。
        /// </summary>
        /// <param name="subject">对应 command subject。</param>
        /// <param name="message">异常文本。</param>
        private void RecordFailure(string subject, string message)
        {
            failedCommands++;
            lastSubject = subject;
            lastAccepted = false;
            lastDuplicate = false;
            lastStatus = "REQUEST_FAILED";
            lastMessage = message ?? string.Empty;
            if (logCommandAck)
            {
                Debug.LogWarning($"[AnchorCommandClient:v3] command failed subject={subject}, request_id={lastRequestId}, error={lastMessage}", this);
            }
        }

        /// <summary>
        /// Python accepted reset 后，同步清理 Unity 本地 anchor runtime。
        ///
        /// 注意：CommandAck 只表示 Python 已接受重置命令；本地清理是为了避免视觉端继续持有旧滤波/旧 pose。
        /// 真正重新定位是否成功仍由后续 PoseResult/状态事件决定。
        /// </summary>
        /// <param name="request">对应 reset request。</param>
        private void ApplyAcceptedResetLocally(ResetTrackingRequest request)
        {
            if (request == null || localAnchorRuntimes == null)
            {
                return;
            }

            foreach (PoseToAnchorRuntime runtime in localAnchorRuntimes)
            {
                if (runtime == null)
                {
                    continue;
                }

                if (request.ClearFilters)
                {
                    runtime.ResetProcessors();
                }

                if (request.ClearAnchorPose)
                {
                    runtime.ClearPoseState(clearProcessors: false);
                }
            }
        }

        /// <summary>
        /// Unity 销毁组件时取消仍在等待的 request。
        /// </summary>
        private void OnDestroy()
        {
            CancelPendingCommand();
            requestCts?.Dispose();
            requestCts = null;
        }
    }
}
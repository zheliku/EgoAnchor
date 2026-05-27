using System;
using System.Threading;
using System.Threading.Tasks;
using EgoAnchor.Protocol;
using EgoAnchor.Transport;
using UnityEngine;

namespace EgoAnchor.Client
{
    /// <summary>
    /// NATS 消息面客户端组件。
    ///
    /// 消息面与 ZMQ 高频数据面相对：它只承载低频、小 payload、需要状态语义的消息，
    /// 当前阶段同时承载 Python -> Unity 的 PoseResult/status/heartbeat 订阅链路，以及 Unity -> Python 的
    /// reset/reacquire/control request-reply 命令链路。
    ///
    /// 本类只负责：
    /// - 连接 NATS。
    /// - 订阅 PoseResult、AnchorStatusEvent、ServerHeartbeat subject。
    /// - 把收到的 Protobuf payload 放入线程安全队列，等待 Unity 主线程消费。
    /// - 提供 bytes request/reply 方法，供上层 AnchorCommandClient 发送 typed command。
    ///
    /// 注意：NATS 后台回调不应直接修改 Transform，也不应运行 anchor 状态机。
    /// </summary>
    public sealed class NatsControlClient : MonoBehaviour
    {
        /// <summary>NATS server URL。</summary>
        [Header("Network / NATS")]
        [Tooltip("NATS server URL。开发机默认 nats://127.0.0.1:4222；Quest 真机部署时应通过 UI/PlayerPrefs 注入开发机 IP。")]
        [SerializeField] private string natsUrl = "nats://127.0.0.1:4222";

        /// <summary>是否启动时从 PlayerPrefs 读取 NATS URL。</summary>
        [Tooltip("是否在启动时从 PlayerPrefs 读取 NATS URL。用于后续 UI 配置注入，避免长期写死 IP。")]
        [SerializeField] private bool loadUrlFromPlayerPrefs = true;

        /// <summary>保存 NATS URL 的 PlayerPrefs key。</summary>
        [Tooltip("保存 NATS URL 的 PlayerPrefs key。UI 设置面板应写入同一个 key。")]
        [SerializeField] private string natsUrlPlayerPrefsKey = "EgoAnchor.NatsUrl";

        /// <summary>是否在 Start 时自动连接。</summary>
        [Tooltip("是否在 Start 时自动连接 NATS 并订阅 PoseResult、AnchorStatusEvent 与 ServerHeartbeat。关闭后可由外部脚本显式调用 StartClient。")]
        [SerializeField] private bool connectOnStart = true;

        /// <summary>订阅端 pending channel 容量。</summary>
        [Tooltip("订阅端内部 pending channel 容量。PoseResult/Heartbeat 是 latest-only 小消息，容量不宜过大，避免旧消息排队。")]
        [Min(1)]
        [SerializeField] private int pendingCapacity = 8;

        /// <summary>初次连接失败时是否继续重试。</summary>
        [Tooltip("是否在初次连接失败时持续重试。开发时 NATS server 可能晚于 Unity 启动，建议保持开启。")]
        [SerializeField] private bool retryOnInitialConnect = false;

        /// <summary>初次连接重试间隔下限秒数。</summary>
        [Tooltip("NATS 初次连接失败后的最小重试间隔。只在 Retry On Initial Connect 开启时生效；保持较小可避免长时间卡住退出。")]
        [Min(0.1f)]
        [SerializeField] private float reconnectWaitMinSeconds = 0.25f;

        /// <summary>初次连接重试间隔上限秒数。</summary>
        [Tooltip("NATS 初次连接失败后的最大重试间隔。只在 Retry On Initial Connect 开启时生效。")]
        [Min(0.1f)]
        [SerializeField] private float reconnectWaitMaxSeconds = 1.0f;

        /// <summary>是否输出聚合统计。</summary>
        [Header("Debug")]
        [Tooltip("是否周期性输出消息面统计。只打印聚合统计，避免每条 pose 刷屏。")]
        [SerializeField] private bool logStats = true;

        /// <summary>统计输出间隔。</summary>
        [Tooltip("收到多少条 PoseResult 后打印一次 NATS 接收统计。")]
        [Min(1)]
        [SerializeField] private int statsIntervalMessages = 120;

        /// <summary>后台线程收到、等待主线程消费的 PoseResult payload 队列。</summary>
        private LatestOnlyQueue<byte[]> poseResultPayloads;

        /// <summary>后台线程收到、等待主线程消费的 AnchorStatusEvent payload 队列。</summary>
        private EventQueue<byte[]> statusPayloads;

        /// <summary>后台线程收到、等待主线程消费的 ServerHeartbeat payload 队列。</summary>
        private LatestOnlyQueue<byte[]> heartbeatPayloads;

        /// <summary>纯 bytes NATS 客户端。</summary>
        private NatsBytesClient bytesClient;

        /// <summary>累计收到的 PoseResult 数量。</summary>
        private int receivedPoseResults;

        /// <summary>累计收到的 AnchorStatusEvent 数量。</summary>
        private int receivedStatusEvents;

        /// <summary>累计收到的 ServerHeartbeat 数量。</summary>
        private int receivedHeartbeats;

        /// <summary>上次打印统计时的接收数量。</summary>
        private int lastLoggedReceived;

        /// <summary>累计发送的 request/reply 命令数量。</summary>
        private int sentRequests;

        /// <summary>累计收到 reply 的 request/reply 命令数量。</summary>
        private int repliedRequests;

        /// <summary>累计 request/reply 失败数量。</summary>
        private int failedRequests;

        /// <summary>当前配置的 NATS 服务地址。</summary>
        public string NatsUrl => natsUrl;

        /// <summary>收到但尚未被主线程消费的 PoseResult payload 数量。</summary>
        public int PendingPoseResultCount => poseResultPayloads?.Count ?? 0;

        /// <summary>收到但尚未被主线程消费的 AnchorStatusEvent payload 数量。</summary>
        public int PendingStatusEventCount => statusPayloads?.Count ?? 0;

        /// <summary>收到但尚未被主线程消费的 ServerHeartbeat payload 数量。</summary>
        public int PendingHeartbeatCount => heartbeatPayloads?.Count ?? 0;

        /// <summary>累计收到的 PoseResult 数量。</summary>
        public int ReceivedPoseResultCount => receivedPoseResults;

        /// <summary>累计收到的 AnchorStatusEvent 数量。</summary>
        public int ReceivedStatusEventCount => receivedStatusEvents;

        /// <summary>累计收到的 ServerHeartbeat 数量。</summary>
        public int ReceivedHeartbeatCount => receivedHeartbeats;

        /// <summary>Unity 侧 latest queue 因容量限制丢弃的旧 payload 数量。</summary>
        public int DroppedInUnityQueueCount => (poseResultPayloads?.DroppedCount ?? 0) + (heartbeatPayloads?.DroppedCount ?? 0);

        /// <summary>Unity 侧 status event 队列因容量限制丢弃的旧 payload 数量。</summary>
        public int DroppedStatusEventCount => statusPayloads?.DroppedCount ?? 0;

        /// <summary>累计发送的 request/reply 命令数量。</summary>
        public int SentRequestCount => sentRequests;

        /// <summary>累计收到 reply 的 request/reply 命令数量。</summary>
        public int RepliedRequestCount => repliedRequests;

        /// <summary>累计 request/reply 失败数量。</summary>
        public int FailedRequestCount => failedRequests;

        /// <summary>
        /// Unity Awake：初始化纯 C# 队列。
        ///
        /// 不在 MonoBehaviour 字段初始化器中 new 队列，避免脚本导入/Domain Reload 时
        /// Unity 通过反射构造默认实例并打印 “MonoBehaviour using new keyword” 警告。
        /// </summary>
        private void Awake()
        {
            EnsureQueue();
        }

        /// <summary>
        /// 更新 NATS URL，并可选择写入 PlayerPrefs 供下次启动复用。
        /// </summary>
        /// <param name="url">新的 NATS URL。</param>
        /// <param name="persistToPlayerPrefs">是否持久化到 PlayerPrefs。</param>
        public void SetNatsUrl(string url, bool persistToPlayerPrefs)
        {
            if (string.IsNullOrWhiteSpace(url))
            {
                return;
            }

            natsUrl = url.Trim();
            if (persistToPlayerPrefs && !string.IsNullOrEmpty(natsUrlPlayerPrefsKey))
            {
                PlayerPrefs.SetString(natsUrlPlayerPrefsKey, natsUrl);
                PlayerPrefs.Save();
            }
        }

        /// <summary>
        /// Unity Start：加载持久化配置并按需启动 NATS。
        /// </summary>
        private void Start()
        {
            LoadConfiguredUrlFromPlayerPrefs();
            if (connectOnStart)
            {
                StartClient();
            }
        }

        /// <summary>
        /// 启动 NATS 连接和 PoseResult 订阅。
        ///
        /// 订阅循环运行在后台 Task 中，只能写线程安全队列；
        /// Protobuf 解码和 Transform 修改必须由其它组件在 Unity 主线程执行。
        /// </summary>
        public void StartClient()
        {
            if (bytesClient != null && bytesClient.IsRunning)
            {
                return;
            }

            EnsureQueue();
            NatsBytesClient.Settings settings = new NatsBytesClient.Settings(
                natsUrl,
                pendingCapacity,
                retryOnInitialConnect,
                reconnectWaitMinSeconds,
                reconnectWaitMaxSeconds
            );
            bytesClient = new NatsBytesClient(settings, this);
            bytesClient.Subscribe(SubjectNames.PoseResult, EnqueuePoseResult);
            bytesClient.Subscribe(SubjectNames.AnchorStatus, EnqueueStatusEvent);
            bytesClient.Subscribe(SubjectNames.ServerHeartbeat, EnqueueHeartbeat);
            bytesClient.Start();
            Debug.Log(
                $"[NatsControlClient] subscribing pose={SubjectNames.PoseResult}, " +
                $"status={SubjectNames.AnchorStatus}, heartbeat={SubjectNames.ServerHeartbeat}",
                this
            );
        }

        /// <summary>
        /// 发送一次 NATS request/reply bytes 请求。
        ///
        /// 本方法属于 transport 层，只认识 subject 与 bytes，不解析 Protobuf，也不理解 reset/reacquire/control 语义。
        /// 上层 AnchorCommandClient 负责构造具体 Protobuf request，并解析 CommandAck。
        /// </summary>
        /// <param name="subject">NATS request subject，必须来自 SubjectNames。</param>
        /// <param name="payload">已经序列化的 Protobuf request bytes。</param>
        /// <param name="timeoutSeconds">等待连接和等待 reply 的超时时间，单位秒。</param>
        /// <param name="token">外部取消信号。</param>
        /// <returns>reply payload bytes。</returns>
        public async Task<byte[]> RequestAsync(string subject, byte[] payload, float timeoutSeconds, CancellationToken token = default)
        {
            if (string.IsNullOrWhiteSpace(subject))
            {
                throw new ArgumentException("NATS request subject 不能为空。", nameof(subject));
            }

            if (payload == null || payload.Length == 0)
            {
                throw new ArgumentException("NATS request payload 不能为空。", nameof(payload));
            }

            if (bytesClient == null || !bytesClient.IsRunning)
            {
                StartClient();
            }

            try
            {
                Interlocked.Increment(ref sentRequests);
                byte[] data = await bytesClient.RequestAsync(subject, payload, timeoutSeconds, token);
                Interlocked.Increment(ref repliedRequests);
                return data;
            }
            catch
            {
                Interlocked.Increment(ref failedRequests);
                throw;
            }
        }

        /// <summary>
        /// 尝试从线程安全队列中取出最新 PoseResult payload。
        ///
        /// 队列语义是 latest-only：若后台短时间收到多条 pose，主线程只处理最新一条，
        /// 从而避免推理/网络抖动时把过期 anchor 逐条补应用到场景里。
        /// </summary>
        /// <param name="payload">最新 payload。</param>
        /// <param name="skippedOlderPayloads">本次消费跳过的旧 payload 数量。</param>
        /// <returns>是否取到 payload。</returns>
        public bool TryDequeueLatestPoseResult(out byte[] payload, out int skippedOlderPayloads)
        {
            EnsureQueue();
            return poseResultPayloads.TryDequeueLatest(out payload, out skippedOlderPayloads);
        }

        /// <summary>
        /// 尝试取出一条 AnchorStatusEvent payload。
        ///
        /// 状态事件不是 latest-only：reset/reacquire/lost 等事件需要按顺序被 UI 或 runtime 消费，
        /// 因此这里一次只取一条，由上层 receiver 在主线程逐帧 drain。
        /// </summary>
        /// <param name="payload">最早尚未处理的 status event payload。</param>
        /// <returns>是否取到 payload。</returns>
        public bool TryDequeueStatusEvent(out byte[] payload)
        {
            EnsureQueue();
            return statusPayloads.TryDequeue(out payload);
        }

        /// <summary>
        /// 尝试从线程安全队列中取出最新 ServerHeartbeat payload。
        /// </summary>
        /// <param name="payload">最新 heartbeat payload。</param>
        /// <param name="skippedOlderPayloads">本次消费跳过的旧 heartbeat payload 数量。</param>
        /// <returns>是否取到 payload。</returns>
        public bool TryDequeueLatestHeartbeat(out byte[] payload, out int skippedOlderPayloads)
        {
            EnsureQueue();
            return heartbeatPayloads.TryDequeueLatest(out payload, out skippedOlderPayloads);
        }

        /// <summary>
        /// 写入 latest-only PoseResult 队列。
        /// </summary>
        private void EnqueuePoseResult(byte[] data)
        {
            EnsureQueue();
            poseResultPayloads.Enqueue(data);
            Interlocked.Increment(ref receivedPoseResults);
            MaybeLogReceiveStats();
        }

        /// <summary>
        /// 写入 AnchorStatusEvent 事件队列。
        /// </summary>
        private void EnqueueStatusEvent(byte[] data)
        {
            EnsureQueue();
            statusPayloads.Enqueue(data);
            Interlocked.Increment(ref receivedStatusEvents);
            MaybeLogReceiveStats();
        }

        /// <summary>
        /// 写入 latest-only ServerHeartbeat 队列。
        /// </summary>
        private void EnqueueHeartbeat(byte[] data)
        {
            EnsureQueue();
            heartbeatPayloads.Enqueue(data);
            Interlocked.Increment(ref receivedHeartbeats);
            MaybeLogReceiveStats();
        }

        /// <summary>
        /// 周期性输出 NATS 接收统计。
        /// </summary>
        private void MaybeLogReceiveStats()
        {
            if (!logStats)
            {
                return;
            }

            int received = receivedPoseResults + receivedStatusEvents + receivedHeartbeats;
            if (received > 0 && received - lastLoggedReceived >= statsIntervalMessages)
            {
                lastLoggedReceived = received;
                Debug.Log(
                    $"[NatsControlClient] pose={receivedPoseResults}, status={receivedStatusEvents}, heartbeat={receivedHeartbeats}, " +
                    $"pendingPose={poseResultPayloads.Count}, pendingStatus={statusPayloads.Count}, pendingHeartbeat={heartbeatPayloads.Count}, " +
                    $"droppedLatest={DroppedInUnityQueueCount}, droppedStatus={DroppedStatusEventCount}",
                    this
                );
            }
        }

        /// <summary>
        /// 确保 latest-only payload 队列已创建。
        /// </summary>
        private void EnsureQueue()
        {
            if (poseResultPayloads == null)
            {
                poseResultPayloads = new LatestOnlyQueue<byte[]>(pendingCapacity);
            }
            if (statusPayloads == null)
            {
                statusPayloads = new EventQueue<byte[]>(pendingCapacity);
            }
            if (heartbeatPayloads == null)
            {
                heartbeatPayloads = new LatestOnlyQueue<byte[]>(pendingCapacity);
            }
        }

        /// <summary>
        /// 从 PlayerPrefs 读取 NATS URL。
        /// </summary>
        private void LoadConfiguredUrlFromPlayerPrefs()
        {
            if (!loadUrlFromPlayerPrefs || string.IsNullOrEmpty(natsUrlPlayerPrefsKey))
            {
                return;
            }

            string storedUrl = PlayerPrefs.GetString(natsUrlPlayerPrefsKey, string.Empty);
            if (!string.IsNullOrWhiteSpace(storedUrl))
            {
                natsUrl = storedUrl.Trim();
            }
        }

        /// <summary>
        /// Unity 销毁组件时关闭 NATS。
        /// </summary>
        private void OnDestroy()
        {
            StopClient();
        }

        /// <summary>
        /// 应用退出时关闭 NATS。
        /// </summary>
        private void OnApplicationQuit()
        {
            StopClient();
        }

        /// <summary>
        /// 停止后台订阅并释放 NATS 客户端。
        /// </summary>
        public void StopClient()
        {
            if (bytesClient == null)
            {
                return;
            }

            bytesClient.Stop();
            bytesClient = null;
        }
    }
}



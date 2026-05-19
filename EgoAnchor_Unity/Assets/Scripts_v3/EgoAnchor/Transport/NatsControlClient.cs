using System;
using System.Collections.Concurrent;
using System.Threading;
using System.Threading.Channels;
using System.Threading.Tasks;
using EgoAnchor.V3.Protocol;
using NATS.Client.Core;
using NATS.Net;
using UnityEngine;

namespace EgoAnchor.V3.Transport
{
    /// <summary>
    /// v3 NATS 消息面客户端组件。
    ///
    /// 消息面与 ZMQ 高频数据面相对：它只承载低频、小 payload、需要状态语义的消息，
    /// 当前阶段先实现 Python -> Unity 的 PoseResult 订阅链路，用于验证实时 anchor 显示。
    ///
    /// 本类只负责：
    /// - 连接 NATS。
    /// - 订阅 PoseResult subject。
    /// - 把收到的 Protobuf payload 放入线程安全 latest-only 队列，等待 Unity 主线程消费。
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
        [SerializeField] private string natsUrlPlayerPrefsKey = "EgoAnchor.V3.NatsUrl";

        /// <summary>是否在 Start 时自动连接。</summary>
        [Tooltip("是否在 Start 时自动连接 NATS 并订阅 PoseResult。关闭后可由外部脚本显式调用 StartClient。")]
        [SerializeField] private bool connectOnStart = true;

        /// <summary>订阅端 pending channel 容量。</summary>
        [Tooltip("订阅端内部 pending channel 容量。PoseResult 是 latest-only 小消息，容量不宜过大，避免旧 pose 排队。")]
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
        private ConcurrentQueue<byte[]> poseResultPayloads;

        /// <summary>后台接收循环取消源。</summary>
        private CancellationTokenSource cts;

        /// <summary>后台接收 Task。</summary>
        private Task receiveTask;

        /// <summary>NATS.Net 客户端。</summary>
        private NatsClient client;

        /// <summary>累计收到的 PoseResult 数量。</summary>
        private int receivedPoseResults;

        /// <summary>Unity 侧 latest queue 因容量限制丢弃的旧 payload 数量。</summary>
        private int droppedInUnityQueue;

        /// <summary>上次打印统计时的接收数量。</summary>
        private int lastLoggedReceived;

        /// <summary>接收循环是否运行中。</summary>
        private volatile bool isRunning;

        /// <summary>当前配置的 NATS 服务地址。</summary>
        public string NatsUrl => natsUrl;

        /// <summary>收到但尚未被主线程消费的 PoseResult payload 数量。</summary>
        public int PendingPoseResultCount => poseResultPayloads?.Count ?? 0;

        /// <summary>累计收到的 PoseResult 数量。</summary>
        public int ReceivedPoseResultCount => receivedPoseResults;

        /// <summary>Unity 侧 latest queue 因容量限制丢弃的旧 payload 数量。</summary>
        public int DroppedInUnityQueueCount => droppedInUnityQueue;

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
            if (isRunning)
            {
                return;
            }

            EnsureQueue();
            isRunning = true;
            cts = new CancellationTokenSource();
            receiveTask = Task.Run(() => ReceiveLoopAsync(cts.Token));
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
            payload = null;
            skippedOlderPayloads = 0;
            EnsureQueue();
            while (poseResultPayloads.TryDequeue(out byte[] candidate))
            {
                if (payload != null)
                {
                    skippedOlderPayloads++;
                }

                payload = candidate;
            }

            return payload != null;
        }

        /// <summary>
        /// 后台 NATS 订阅循环。
        /// </summary>
        private async Task ReceiveLoopAsync(CancellationToken token)
        {
            try
            {
                NatsOpts opts = new NatsOpts
                {
                    Url = natsUrl,
                    RetryOnInitialConnect = retryOnInitialConnect,
                    ReconnectWaitMin = TimeSpan.FromSeconds(Mathf.Max(0.1f, reconnectWaitMinSeconds)),
                    ReconnectWaitMax = TimeSpan.FromSeconds(Mathf.Max(reconnectWaitMinSeconds, reconnectWaitMaxSeconds)),
                    DrainSubscriptionsOnDispose = false,
                    SubPendingChannelCapacity = Mathf.Max(1, pendingCapacity),
                    SubPendingChannelFullMode = BoundedChannelFullMode.DropOldest,
                };

                NatsClient localClient = new NatsClient(opts, BoundedChannelFullMode.DropOldest);
                client = localClient;
                await localClient.ConnectAsync();
                Debug.Log($"[NatsControlClient:v3] connected url={natsUrl}, subject={SubjectNames.PoseResult}", this);

                await foreach (NatsMsg<byte[]> msg in localClient.SubscribeAsync<byte[]>(SubjectNames.PoseResult, cancellationToken: token))
                {
                    if (token.IsCancellationRequested)
                    {
                        break;
                    }

                    byte[] data = msg.Data;
                    if (data == null || data.Length == 0)
                    {
                        continue;
                    }

                    EnsureQueue();
                    poseResultPayloads.Enqueue(data);
                    Interlocked.Increment(ref receivedPoseResults);
                    TrimPendingQueueToLatestCapacity();
                    MaybeLogReceiveStats();
                }
            }
            catch (OperationCanceledException)
            {
                // Play Mode 退出或组件销毁时的正常路径。
            }
            catch (Exception ex)
            {
                Debug.LogError($"[NatsControlClient:v3] NATS receive loop failed: {ex}", this);
            }
            finally
            {
                isRunning = false;
            }
        }

        /// <summary>
        /// 将主线程队列裁剪到配置容量，保持 latest-only。
        /// </summary>
        private void TrimPendingQueueToLatestCapacity()
        {
            EnsureQueue();
            int safeCapacity = Mathf.Max(1, pendingCapacity);
            while (poseResultPayloads.Count > safeCapacity && poseResultPayloads.TryDequeue(out _))
            {
                Interlocked.Increment(ref droppedInUnityQueue);
            }
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

            int received = receivedPoseResults;
            if (received > 0 && received - lastLoggedReceived >= statsIntervalMessages)
            {
                lastLoggedReceived = received;
                Debug.Log(
                    $"[NatsControlClient:v3] pose_result received={received}, pending={poseResultPayloads.Count}, " +
                    $"droppedInUnityQueue={droppedInUnityQueue}, subject={SubjectNames.PoseResult}",
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
                poseResultPayloads = new ConcurrentQueue<byte[]>();
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
            if (!isRunning && cts == null && client == null)
            {
                return;
            }

            NatsClient clientToDispose = client;
            CancellationTokenSource ctsToDispose = cts;
            Task receiveTaskToObserve = receiveTask;

            client = null;
            cts = null;
            receiveTask = null;
            isRunning = false;

            try
            {
                ctsToDispose?.Cancel();
            }
            catch
            {
                // ignored
            }

            DisposeClientWithoutBlocking(clientToDispose);
            ObserveReceiveTaskAndDisposeCts(receiveTaskToObserve, ctsToDispose);
        }

        private static async void DisposeClientWithoutBlocking(NatsClient clientToDispose)
        {
            if (clientToDispose == null)
            {
                return;
            }

            try
            {
                await clientToDispose.DisposeAsync();
            }
            catch
            {
                // Play Mode/Domain Reload 退出时不因关闭异常打断 Unity。
            }
        }

        private static async void ObserveReceiveTaskAndDisposeCts(Task receiveTaskToObserve, CancellationTokenSource ctsToDispose)
        {
            try
            {
                if (receiveTaskToObserve != null)
                {
                    await receiveTaskToObserve;
                }
            }
            catch
            {
                // 关闭路径忽略后台任务异常。
            }
            finally
            {
                ctsToDispose?.Dispose();
            }
        }
    }
}

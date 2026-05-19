using System;
using System.Collections.Concurrent;
using System.Threading;
using System.Threading.Channels;
using System.Threading.Tasks;
using EgoAnchor.V2.Protocol;
using NATS.Client.Core;
using NATS.Net;
using UnityEngine;

namespace EgoAnchor.V2.Transport
{
    /// <summary>
    /// v2 NATS 控制面客户端组件。
    ///
    /// control plane（控制面）与 ZMQ 高频数据面相对：它只承载低频、小 payload、需要状态语义的消息，
    /// 例如 PoseResult、AnchorStatus、ServerHeartbeat 以及 reset/reacquire/control request。
    /// 当前阶段先实现 Python -> Unity 的 PoseResult 订阅链路，用于验证实时 anchor 显示。
    ///
    /// 当前本类负责：
    /// - 连接 NATS。
    /// - 订阅 PoseResult。
    /// - 把收到的 Protobuf payload 放入线程安全 latest 队列，等待 Unity 主线程消费。
    ///
    /// 注意：NATS handler 不应直接修改 Transform，也不应直接运行复杂状态机。
    /// </summary>
    public sealed class NatsControlClient : MonoBehaviour
    {
        [Tooltip("NATS server URL。开发机默认 nats://127.0.0.1:4222；Quest 真机部署时应通过 UI/PlayerPrefs 等配置注入。")]
        [SerializeField] private string natsUrl = "nats://127.0.0.1:4222";

        [Tooltip("是否在启动时从 PlayerPrefs 读取 NATS URL。用于后续 UI 配置注入，避免长期写死 IP。")]
        [SerializeField] private bool loadUrlFromPlayerPrefs = true;

        [Tooltip("保存 NATS URL 的 PlayerPrefs key。UI 设置面板应写入同一个 key。")]
        [SerializeField] private string natsUrlPlayerPrefsKey = "EgoAnchor.V2.NatsUrl";

        [Tooltip("是否在 Start 时自动连接 NATS 并订阅 PoseResult。关闭后可由外部脚本显式调用 StartClient。")]
        [SerializeField] private bool connectOnStart = true;

        [Tooltip("订阅端内部 pending channel 容量。PoseResult 是 latest-only 小消息，容量不宜过大，避免旧 pose 排队。")]
        [Min(1)]
        [SerializeField] private int pendingCapacity = 8;

        [Tooltip("是否在初次连接失败时持续重试。开发时 NATS server 可能晚于 Unity 启动，建议保持开启。")]
        [SerializeField] private bool retryOnInitialConnect = true;

        [Tooltip("是否周期性输出控制面统计。只打印聚合统计，避免每条 pose 刷屏。")]
        [SerializeField] private bool logStats = true;

        [Tooltip("收到多少条 PoseResult 后打印一次 NATS 接收统计。")]
        [Min(1)]
        [SerializeField] private int statsIntervalMessages = 120;

        private readonly ConcurrentQueue<byte[]> _poseResultPayloads = new ConcurrentQueue<byte[]>();
        private CancellationTokenSource _cts;
        private Task _receiveTask;
        private NatsClient _client;
        private int _receivedPoseResults;
        private int _droppedInUnityQueue;
        private int _lastLoggedReceived;
        private volatile bool _isRunning;

        /// <summary>当前配置的 NATS 服务地址。</summary>
        public string NatsUrl => natsUrl;

        /// <summary>更新 NATS URL，并可选择写入 PlayerPrefs 供下次启动复用。</summary>
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

        /// <summary>收到但尚未被主线程消费的 PoseResult payload 数量。</summary>
        public int PendingPoseResultCount => _poseResultPayloads.Count;

        /// <summary>累计收到的 PoseResult 数量。</summary>
        public int ReceivedPoseResultCount => _receivedPoseResults;

        /// <summary>Unity 侧 latest queue 因容量限制丢弃的旧 payload 数量。</summary>
        public int DroppedInUnityQueueCount => _droppedInUnityQueue;

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
        /// 注意：订阅循环运行在后台 Task 中，只能写线程安全队列；
        /// Protobuf 解码和 Transform 修改必须由其它组件在 Unity 主线程执行。
        /// </summary>
        public void StartClient()
        {
            if (_isRunning)
            {
                return;
            }

            _isRunning = true;
            _cts = new CancellationTokenSource();
            _receiveTask = Task.Run(() => ReceiveLoopAsync(_cts.Token));
        }

        /// <summary>
        /// 尝试从线程安全队列中取出最新 PoseResult payload。
        ///
        /// 队列语义是 latest-only：若后台短时间收到多条 pose，主线程只处理最新一条，
        /// 从而避免推理/网络抖动时把过期 anchor 逐条补应用到场景里。
        /// </summary>
        public bool TryDequeueLatestPoseResult(out byte[] payload, out int skippedOlderPayloads)
        {
            payload = null;
            skippedOlderPayloads = 0;
            while (_poseResultPayloads.TryDequeue(out byte[] candidate))
            {
                if (payload != null)
                {
                    skippedOlderPayloads++;
                }

                payload = candidate;
            }

            return payload != null;
        }

        private async Task ReceiveLoopAsync(CancellationToken token)
        {
            try
            {
                NatsOpts opts = new NatsOpts
                {
                    Url = natsUrl,
                    RetryOnInitialConnect = retryOnInitialConnect,
                    SubPendingChannelCapacity = Mathf.Max(1, pendingCapacity),
                    SubPendingChannelFullMode = BoundedChannelFullMode.DropOldest,
                };

                _client = new NatsClient(opts, BoundedChannelFullMode.DropOldest);
                await _client.ConnectAsync();
                Debug.Log($"[NatsControlClient] connected url={natsUrl}, subject={SubjectNames.PoseResult}", this);

                await foreach (NatsMsg<byte[]> msg in _client.SubscribeAsync<byte[]>(SubjectNames.PoseResult, cancellationToken: token))
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

                    _poseResultPayloads.Enqueue(data);
                    Interlocked.Increment(ref _receivedPoseResults);
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
                Debug.LogError($"[NatsControlClient] NATS receive loop failed: {ex}", this);
            }
            finally
            {
                _isRunning = false;
            }
        }

        private void TrimPendingQueueToLatestCapacity()
        {
            int safeCapacity = Mathf.Max(1, pendingCapacity);
            while (_poseResultPayloads.Count > safeCapacity && _poseResultPayloads.TryDequeue(out _))
            {
                Interlocked.Increment(ref _droppedInUnityQueue);
            }
        }

        private void MaybeLogReceiveStats()
        {
            if (!logStats)
            {
                return;
            }

            int received = _receivedPoseResults;
            if (received > 0 && received - _lastLoggedReceived >= statsIntervalMessages)
            {
                _lastLoggedReceived = received;
                Debug.Log(
                    $"[NatsControlClient] pose_result received={received}, pending={_poseResultPayloads.Count}, " +
                    $"droppedInUnityQueue={_droppedInUnityQueue}, subject={SubjectNames.PoseResult}",
                    this
                );
            }
        }

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

        private void OnDestroy()
        {
            StopClient();
        }

        private void OnApplicationQuit()
        {
            StopClient();
        }

        private void StopClient()
        {
            if (!_isRunning && _cts == null && _client == null)
            {
                return;
            }

            try
            {
                _cts?.Cancel();
            }
            catch
            {
                // ignored
            }

            try
            {
                _client?.DisposeAsync().AsTask().Wait(500);
            }
            catch
            {
                // Play Mode 退出时不因关闭异常打断 Unity。
            }

            _client = null;
            _cts?.Dispose();
            _cts = null;
            _receiveTask = null;
            _isRunning = false;
        }
    }
}

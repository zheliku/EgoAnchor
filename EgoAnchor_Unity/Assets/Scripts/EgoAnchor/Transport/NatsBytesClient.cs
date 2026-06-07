using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Channels;
using System.Threading.Tasks;
using EgoAnchor.Diagnostics;
using NATS.Client.Core;
using NATS.Net;
using UnityEngine;

namespace EgoAnchor.Transport
{
    /// <summary>
    /// 纯 bytes NATS 客户端。
    ///
    /// 本类只负责连接、订阅 bytes payload 和 request/reply bytes；不理解 EgoAnchor subject、
    /// 不解析 Protobuf，也不接触 Unity Transform。
    /// </summary>
    public sealed class NatsBytesClient
    {
        /// <summary>统一日志通道。</summary>
        private static readonly EgoAnchorLog.Channel Log = EgoAnchorLog.For<NatsBytesClient>();

        /// <summary>bytes payload 回调。</summary>
        /// <param name="payload">收到的非空 payload。</param>
        public delegate void PayloadHandler(byte[] payload);

        /// <summary>连接配置。</summary>
        public readonly struct Settings
        {
            /// <summary>NATS server URL。</summary>
            public readonly string Url;

            /// <summary>订阅端 pending channel 容量。</summary>
            public readonly int PendingCapacity;

            /// <summary>初次连接失败时是否继续重试。</summary>
            public readonly bool RetryOnInitialConnect;

            /// <summary>初次连接重试间隔下限秒数。</summary>
            public readonly float ReconnectWaitMinSeconds;

            /// <summary>初次连接重试间隔上限秒数。</summary>
            public readonly float ReconnectWaitMaxSeconds;

            /// <summary>
            /// 构造 NATS bytes 连接配置。
            /// </summary>
            public Settings(string url, int pendingCapacity, bool retryOnInitialConnect, float reconnectWaitMinSeconds, float reconnectWaitMaxSeconds)
            {
                Url = string.IsNullOrWhiteSpace(url) ? "nats://127.0.0.1:4222" : url.Trim();
                PendingCapacity = Mathf.Max(1, pendingCapacity);
                RetryOnInitialConnect = retryOnInitialConnect;
                ReconnectWaitMinSeconds = Mathf.Max(0.1f, reconnectWaitMinSeconds);
                ReconnectWaitMaxSeconds = Mathf.Max(ReconnectWaitMinSeconds, reconnectWaitMaxSeconds);
            }
        }

        /// <summary>NATS 连接配置。</summary>
        private readonly Settings settings;

        /// <summary>Unity 日志上下文对象。</summary>
        private readonly UnityEngine.Object logContext;

        /// <summary>subject -> payload callback 列表。</summary>
        private readonly List<(string Subject, PayloadHandler Handler)> subscriptions = new List<(string, PayloadHandler)>();

        /// <summary>后台接收循环取消源。</summary>
        private CancellationTokenSource cts;

        /// <summary>后台接收 Task。</summary>
        private Task receiveTask;

        /// <summary>NATS.Net 客户端。</summary>
        private NatsClient client;

        /// <summary>连接完成信号；request/reply 发送前会等待它完成。</summary>
        private TaskCompletionSource<bool> connectReady;

        /// <summary>接收循环是否运行中。</summary>
        private volatile bool isRunning;

        /// <summary>
        /// 创建 NATS bytes client。
        /// </summary>
        /// <param name="settings">连接配置。</param>
        /// <param name="logContext">Unity 日志上下文。</param>
        public NatsBytesClient(Settings settings, UnityEngine.Object logContext)
        {
            this.settings = settings;
            this.logContext = logContext;
        }

        /// <summary>接收循环是否运行中。</summary>
        public bool IsRunning => isRunning;

        /// <summary>当前 NATS server URL。</summary>
        public string Url => settings.Url;

        /// <summary>
        /// 注册一个 bytes 订阅；应在 Start 前调用。
        /// </summary>
        public void Subscribe(string subject, PayloadHandler handler)
        {
            if (string.IsNullOrWhiteSpace(subject))
            {
                throw new ArgumentException("NATS subject 不能为空。", nameof(subject));
            }

            if (handler == null)
            {
                throw new ArgumentNullException(nameof(handler));
            }

            subscriptions.Add((subject, handler));
        }

        /// <summary>
        /// 启动 NATS 连接和订阅循环。
        /// </summary>
        public void Start()
        {
            if (isRunning)
            {
                return;
            }

            isRunning = true;
            connectReady = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            cts = new CancellationTokenSource();
            receiveTask = Task.Run(() => ReceiveLoopAsync(cts.Token));
        }

        /// <summary>
        /// 发送一次 request/reply bytes 请求。
        /// </summary>
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

            if (!isRunning)
            {
                Start();
            }

            using CancellationTokenSource timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(token);
            timeoutCts.CancelAfter(TimeSpan.FromSeconds(Mathf.Max(0.1f, timeoutSeconds)));

            Task readyTask = connectReady?.Task;
            if (readyTask != null)
            {
                await WaitWithCancellationAsync(readyTask, timeoutCts.Token);
            }

            NatsClient activeClient = client;
            if (activeClient == null)
            {
                throw new InvalidOperationException("NATS client 尚未连接，无法发送 command request。");
            }

            NatsMsg<byte[]> reply = await activeClient.RequestAsync<byte[], byte[]>(subject, payload, cancellationToken: timeoutCts.Token);
            return reply.Data ?? Array.Empty<byte>();
        }

        /// <summary>
        /// 停止后台订阅并释放 NATS 客户端。
        /// </summary>
        public void Stop()
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
            connectReady?.TrySetCanceled();
            isRunning = false;

            try
            {
                ctsToDispose?.Cancel();
            }
            catch
            {
                // 取消路径不应影响 Unity 主循环。
            }

            DisposeClientWithoutBlocking(clientToDispose);
            ObserveReceiveTaskAndDisposeCts(receiveTaskToObserve, ctsToDispose);
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
                    Url = settings.Url,
                    RetryOnInitialConnect = settings.RetryOnInitialConnect,
                    ReconnectWaitMin = TimeSpan.FromSeconds(settings.ReconnectWaitMinSeconds),
                    ReconnectWaitMax = TimeSpan.FromSeconds(settings.ReconnectWaitMaxSeconds),
                    DrainSubscriptionsOnDispose = false,
                    SubPendingChannelCapacity = settings.PendingCapacity,
                    SubPendingChannelFullMode = BoundedChannelFullMode.DropOldest,
                };

                NatsClient localClient = new NatsClient(opts, BoundedChannelFullMode.DropOldest);
                client = localClient;
                await localClient.ConnectAsync();
                connectReady?.TrySetResult(true);
                Log.Info($"connected url={settings.Url}", logContext);

                List<Task> tasks = new List<Task>(subscriptions.Count);
                foreach ((string subject, PayloadHandler handler) in subscriptions)
                {
                    tasks.Add(ReceiveSubscriptionAsync(localClient, subject, handler, token));
                }

                await Task.WhenAll(tasks);
            }
            catch (OperationCanceledException)
            {
                connectReady?.TrySetCanceled();
            }
            catch (Exception ex)
            {
                connectReady?.TrySetException(ex);
                Log.Error($"receive loop failed: {ex}", logContext);
            }
            finally
            {
                isRunning = false;
            }
        }

        /// <summary>
        /// 后台订阅单个 subject，并把非空 payload 交给回调。
        /// </summary>
        private static async Task ReceiveSubscriptionAsync(NatsClient localClient, string subject, PayloadHandler handler, CancellationToken token)
        {
            await foreach (NatsMsg<byte[]> msg in localClient.SubscribeAsync<byte[]>(subject, cancellationToken: token))
            {
                if (token.IsCancellationRequested)
                {
                    return;
                }

                byte[] data = msg.Data;
                if (data != null && data.Length > 0)
                {
                    handler(data);
                }
            }
        }

        /// <summary>
        /// 等待任务完成，同时支持旧 Unity/.NET Standard 环境中没有 Task.WaitAsync 的情况。
        /// </summary>
        private static async Task WaitWithCancellationAsync(Task task, CancellationToken token)
        {
            if (task.IsCompleted)
            {
                await task;
                return;
            }

            TaskCompletionSource<bool> cancelled = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            using CancellationTokenRegistration registration = token.Register(state =>
            {
                TaskCompletionSource<bool> source = (TaskCompletionSource<bool>)state;
                source.TrySetResult(true);
            }, cancelled);

            Task finished = await Task.WhenAny(task, cancelled.Task);
            if (finished != task)
            {
                throw new OperationCanceledException(token);
            }

            await task;
        }

        /// <summary>
        /// 异步释放 NATS client，避免阻塞 Unity 退出。
        /// </summary>
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

        /// <summary>
        /// 观察后台任务并释放取消源。
        /// </summary>
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

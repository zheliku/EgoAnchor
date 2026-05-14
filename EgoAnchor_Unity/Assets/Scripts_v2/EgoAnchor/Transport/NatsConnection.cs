using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using NATS.Net;
using UnityEngine;

namespace EgoAnchor.V2.Transport
{
    /// <summary>
    /// EgoAnchor v2 的 NATS 连接组件。
    ///
    /// 职责边界：
    /// - 只负责连接 NATS server、发布 bytes、发送 request/reply、释放连接。
    /// - 不理解 EgoAnchor 的 subject、pose、anchor、camera_info、pipeline 等业务含义。
    /// - 业务组件通过组合方式持有本组件引用，而不是继承它。
    ///
    /// 为什么用组合而不是继承：
    /// - QuestStreamPublisher、AnchorControlApi、PoseResultReceiver 都需要同一条连接。
    /// - 它们的业务职责不同，如果都继承连接类，会把网络生命周期和业务逻辑耦合在一起。
    /// - 组合能让一个场景里只有一个 NatsConnection，多个 client 组件复用它。
    /// </summary>
    public class NatsConnection : MonoBehaviour
    {
        [SerializeField] private string natsUrl = "nats://127.0.0.1:4222";
        [SerializeField] private string clientName = "EgoAnchor Unity v2";
        [SerializeField] private bool connectOnStart = true;
        [Header("Realtime Publish")]
        [SerializeField] private float latestPublishTimeoutSeconds = 0.25f;

        private NatsClient _client;
        private readonly SemaphoreSlim _connectLock = new SemaphoreSlim(1, 1);
        private readonly object _latestPublishersLock = new object();
        private readonly Dictionary<string, LatestPublisher> _latestPublishers = new Dictionary<string, LatestPublisher>();

        public NatsClient Client => _client;
        public bool IsConnected => _client != null;

        private async void Start()
        {
            if (connectOnStart)
            {
                await ConnectAsync(CancellationToken.None);
            }
        }

        public async Task<NatsClient> ConnectAsync(CancellationToken cancellationToken)
        {
            // 懒连接：首次调用时连接；已经连接时直接复用。
            if (_client != null)
            {
                return _client;
            }

            await _connectLock.WaitAsync(cancellationToken);
            try
            {
                if (_client != null)
                {
                    return _client;
                }

                NatsClient client = new NatsClient(natsUrl, clientName);
                await client.ConnectAsync();
                _client = client;
                Debug.Log($"[EgoAnchorV2] NATS connected: {natsUrl}", this);
                return _client;
            }
            finally
            {
                _connectLock.Release();
            }
        }

        public async Task PublishAsync(string subject, byte[] payload, CancellationToken cancellationToken)
        {
            // 传输层只处理 bytes，不关心 payload 是哪个 protobuf 类型。
            NatsClient client = await ConnectAsync(cancellationToken);
            await client.PublishAsync(subject, payload, cancellationToken: cancellationToken);
        }

        public bool PublishLatest(string subject, byte[] payload)
        {
            // 高频实时流只保留每个 subject 的最新 payload。发送泵忙时，新帧覆盖旧帧，避免排队积压。
            if (string.IsNullOrWhiteSpace(subject) || payload == null || payload.Length == 0)
            {
                return false;
            }

            LatestPublisher publisher;
            lock (_latestPublishersLock)
            {
                if (!_latestPublishers.TryGetValue(subject, out publisher))
                {
                    publisher = new LatestPublisher(this, subject);
                    _latestPublishers.Add(subject, publisher);
                }
            }

            publisher.Enqueue(payload);
            return true;
        }

        public LatestPublishStats GetLatestPublishStats(string subject, bool reset)
        {
            lock (_latestPublishersLock)
            {
                return _latestPublishers.TryGetValue(subject, out LatestPublisher publisher)
                    ? publisher.GetStats(reset)
                    : LatestPublishStats.Empty;
            }
        }

        public async Task<byte[]> RequestAsync(string subject, byte[] payload, CancellationToken cancellationToken)
        {
            // request/reply 用于 reset/reacquire/control 等需要 ack 的命令。
            NatsClient client = await ConnectAsync(cancellationToken);
            var reply = await client.RequestAsync<byte[], byte[]>(subject, payload, cancellationToken: cancellationToken);
            return reply.Data;
        }

        private async void OnDestroy()
        {
            LatestPublisher[] publishers;
            lock (_latestPublishersLock)
            {
                publishers = new LatestPublisher[_latestPublishers.Count];
                _latestPublishers.Values.CopyTo(publishers, 0);
                _latestPublishers.Clear();
            }

            foreach (LatestPublisher publisher in publishers)
            {
                publisher.Dispose();
            }

            if (_client == null)
            {
                return;
            }

            try
            {
                await _client.DisposeAsync();
            }
            catch (Exception e)
            {
                Debug.LogWarning($"[EgoAnchorV2] NATS dispose failed: {e.Message}", this);
            }
            finally
            {
                _client = null;
            }
        }

        private TimeSpan LatestPublishTimeout => TimeSpan.FromSeconds(Mathf.Max(0.01f, latestPublishTimeoutSeconds));

        public readonly struct LatestPublishStats
        {
            public static LatestPublishStats Empty => new LatestPublishStats(0, 0, 0, 0, 0, 0, null);

            public readonly long Enqueued;
            public readonly long Sent;
            public readonly long Overwritten;
            public readonly long Failed;
            public readonly long TimedOut;
            public readonly long SentBytes;
            public readonly string LastError;

            public LatestPublishStats(long enqueued, long sent, long overwritten, long failed, long timedOut, long sentBytes, string lastError)
            {
                Enqueued = enqueued;
                Sent = sent;
                Overwritten = overwritten;
                Failed = failed;
                TimedOut = timedOut;
                SentBytes = sentBytes;
                LastError = lastError;
            }
        }

        private sealed class LatestPublisher : IDisposable
        {
            private readonly NatsConnection _owner;
            private readonly string _subject;
            private readonly object _gate = new object();
            private byte[] _latestPayload;
            private bool _hasLatest;
            private bool _running;
            private bool _disposed;
            private long _enqueued;
            private long _sent;
            private long _overwritten;
            private long _failed;
            private long _timedOut;
            private long _sentBytes;
            private string _lastError;

            public LatestPublisher(NatsConnection owner, string subject)
            {
                _owner = owner;
                _subject = subject;
            }

            public void Enqueue(byte[] payload)
            {
                bool startWorker = false;
                lock (_gate)
                {
                    if (_disposed)
                    {
                        return;
                    }

                    if (_hasLatest)
                    {
                        _overwritten++;
                    }

                    _latestPayload = payload;
                    _hasLatest = true;
                    _enqueued++;
                    if (!_running)
                    {
                        _running = true;
                        startWorker = true;
                    }
                }

                if (startWorker)
                {
                    _ = Task.Run(RunAsync);
                }
            }

            public LatestPublishStats GetStats(bool reset)
            {
                lock (_gate)
                {
                    LatestPublishStats stats = new LatestPublishStats(_enqueued, _sent, _overwritten, _failed, _timedOut, _sentBytes, _lastError);
                    if (reset)
                    {
                        _enqueued = 0;
                        _sent = 0;
                        _overwritten = 0;
                        _failed = 0;
                        _timedOut = 0;
                        _sentBytes = 0;
                        _lastError = null;
                    }
                    return stats;
                }
            }

            public void Dispose()
            {
                lock (_gate)
                {
                    _disposed = true;
                    _hasLatest = false;
                    _latestPayload = null;
                }
            }

            private async Task RunAsync()
            {
                while (true)
                {
                    byte[] payload;
                    lock (_gate)
                    {
                        if (_disposed || !_hasLatest)
                        {
                            _running = false;
                            return;
                        }

                        payload = _latestPayload;
                        _latestPayload = null;
                        _hasLatest = false;
                    }

                    try
                    {
                        using CancellationTokenSource timeout = new CancellationTokenSource(_owner.LatestPublishTimeout);
                        await _owner.PublishAsync(_subject, payload, timeout.Token).ConfigureAwait(false);
                        lock (_gate)
                        {
                            _sent++;
                            _sentBytes += payload.Length;
                            _lastError = null;
                        }
                    }
                    catch (OperationCanceledException e)
                    {
                        lock (_gate)
                        {
                            _timedOut++;
                            _lastError = e.Message;
                        }
                    }
                    catch (Exception e)
                    {
                        lock (_gate)
                        {
                            _failed++;
                            _lastError = e.Message;
                        }
                    }
                }
            }
        }
    }
}

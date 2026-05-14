using System;
using System.Collections.Concurrent;
using System.Threading;
using System.Threading.Tasks;
using EgoAnchor.Protocol.V1;
using EgoAnchor.V2.Protocol;
using EgoAnchor.V2.Transport;
using NATS.Net;
using UnityEngine;
using UnityEngine.Events;

namespace EgoAnchor.V2.Client
{
    /// <summary>
    /// Anchor 状态事件 UnityEvent。
    /// 事件内容保留完整 protobuf，方便 UI/调试面板按需读取 state/event/message/error。
    /// </summary>
    [Serializable]
    public class AnchorStatusEventReceived : UnityEvent<AnchorStatusEvent> { }

    /// <summary>
    /// 订阅 Python -> Unity 的 `egoanchor.v1.anchor.status`。
    ///
    /// 它负责接收领域状态变化，例如 RESET_APPLIED、REACQUIRE_STARTED、ERROR 等。
    /// 当前 Python smoke server 还没有发布状态事件；接入 TrackingRuntime 后会使用。
    /// </summary>
    public class AnchorStatusReceiver : MonoBehaviour
    {
        [SerializeField] private NatsConnection connection;
        public AnchorStatusEventReceived OnStatusReceived = new AnchorStatusEventReceived();

        private CancellationTokenSource _cts;
        private readonly ConcurrentQueue<AnchorStatusEvent> _mainThreadEvents = new ConcurrentQueue<AnchorStatusEvent>();

        private async void OnEnable()
        {
            _cts = new CancellationTokenSource();
            await ReceiveLoop(_cts.Token);
        }

        private void OnDisable()
        {
            _cts?.Cancel();
            _cts?.Dispose();
            _cts = null;
        }

        private void Update()
        {
            // NATS 接收循环可能不在 Unity 主线程；所有 UnityEvent 统一在 Update 中触发。
            while (_mainThreadEvents.TryDequeue(out AnchorStatusEvent statusEvent))
            {
                OnStatusReceived?.Invoke(statusEvent);
            }
        }

        private async Task ReceiveLoop(CancellationToken cancellationToken)
        {
            if (connection == null)
            {
                return;
            }

            try
            {
                NatsClient client = await connection.ConnectAsync(cancellationToken);
                // NATS.Net 的 SubscribeAsync 是异步流；OnDisable cancel 后循环退出。
                await foreach (var msg in client.SubscribeAsync<byte[]>(SubjectNames.AnchorStatus, cancellationToken: cancellationToken))
                {
                    _mainThreadEvents.Enqueue(AnchorStatusEvent.Parser.ParseFrom(msg.Data));
                }
            }
            catch (OperationCanceledException)
            {
            }
            catch (Exception e)
            {
                Debug.LogError($"[EgoAnchorV2] Anchor status receive failed: {e.Message}", this);
            }
        }
    }
}

using EgoAnchor.Diagnostics;
using Google.Protobuf;
using UnityEngine;

namespace EgoAnchor.Client
{
    /// <summary>
    /// NATS typed Protobuf 接收器基类。
    ///
    /// 子类只提供 payload 出队策略、Protobuf parser 和解析后的广播逻辑；
    /// 本基类统一处理 Unity 主线程 Update、Protobuf 异常统计和聚合日志。
    /// </summary>
    /// <typeparam name="TMessage">Protobuf 消息类型。</typeparam>
    public abstract class NatsTypedReceiver<TMessage> : MonoBehaviour where TMessage : class, IMessage<TMessage>
    {
        /// <summary>统一日志通道。</summary>
        private readonly EgoAnchorLog.Channel log;

        /// <summary>NATS 消息面客户端。</summary>
        [Header("Inputs")]
        [Tooltip("NATS 消息面客户端。只负责连接和 payload 队列，不直接解码 Protobuf。")]
        [SerializeField] private NatsControlClient natsClient;

        /// <summary>是否输出聚合统计。</summary>
        [Header("Debug")]
        [Tooltip("是否输出 Protobuf 解码/分发统计。")]
        [SerializeField] private bool logStats = true;

        /// <summary>统计输出间隔。</summary>
        [Tooltip("每处理多少条 payload 打印一次统计。")]
        [Min(1)]
        [SerializeField] private int statsIntervalMessages = 30;

        /// <summary>累计成功解码消息数。</summary>
        private int decoded;

        /// <summary>累计 Protobuf 解码失败数。</summary>
        private int parseFailed;

        /// <summary>latest-only 消费跳过的旧 payload 数。</summary>
        private int skippedOlder;

        /// <summary>上次打印统计时的总处理数。</summary>
        private int lastLoggedTotal;

        /// <summary>接收器日志名称。</summary>
        protected abstract string ReceiverName { get; }

        /// <summary>当前消息类型的 Protobuf parser。</summary>
        protected abstract MessageParser<TMessage> Parser { get; }

        /// <summary>单帧最多处理 payload 数量；latest-only 消息通常为 1，事件流可提高。</summary>
        protected virtual int MaxMessagesPerFrame => 1;

        /// <summary>NATS 消息面客户端，供子类选择具体队列。</summary>
        protected NatsControlClient NatsClient => natsClient;

        /// <summary>聚合日志中的附加统计文本。</summary>
        protected virtual string ExtraStats => string.Empty;

        /// <summary>
        /// 创建 typed receiver，并用具体子类名作为日志 component。
        /// </summary>
        protected NatsTypedReceiver()
        {
            log = EgoAnchorLog.For(GetType().Name);
        }

        /// <summary>
        /// Unity Update：主线程 drain payload、解析 Protobuf，并交给子类处理。
        /// </summary>
        private void Update()
        {
            if (natsClient == null || !CanReceive)
            {
                return;
            }

            int processedThisFrame = 0;
            int maxMessages = Mathf.Max(1, MaxMessagesPerFrame);
            while (processedThisFrame < maxMessages && TryDequeueRaw(out byte[] payload, out int skippedOlderPayloads))
            {
                processedThisFrame++;
                skippedOlder += skippedOlderPayloads;
                try
                {
                    TMessage message = Parser.ParseFrom(payload);
                    decoded++;
                    OnParsed(message);
                }
                catch (InvalidProtocolBufferException ex)
                {
                    parseFailed++;
                    log.Warning($"Protobuf 解码失败：{ex.Message}", this);
                }
            }

            if (processedThisFrame > 0)
            {
                MaybeLogStats();
            }
        }

        /// <summary>子类是否已具备分发依赖。</summary>
        protected virtual bool CanReceive => true;

        /// <summary>
        /// 从 NatsControlClient 中取出一条 raw payload。
        /// </summary>
        /// <param name="payload">待解析的 payload。</param>
        /// <param name="skippedOlderPayloads">latest-only 队列本次跳过旧 payload 数。</param>
        /// <returns>是否取到 payload。</returns>
        protected abstract bool TryDequeueRaw(out byte[] payload, out int skippedOlderPayloads);

        /// <summary>
        /// 处理已解析的 typed Protobuf 消息。
        /// </summary>
        /// <param name="message">已解析消息。</param>
        protected abstract void OnParsed(TMessage message);

        /// <summary>
        /// 周期性输出接收和分发统计。
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
                string extra = ExtraStats;
                log.Info(
                    $"decoded={decoded}, parseFailed={parseFailed}, skippedOlder={skippedOlder}" +
                    (string.IsNullOrEmpty(extra) ? string.Empty : $", {extra}"),
                    this
                );
            }
        }
    }
}

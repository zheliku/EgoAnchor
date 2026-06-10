using System.Collections.Concurrent;
using System.Threading;

namespace EgoAnchor.Client
{
    /// <summary>
    /// 线程安全有界事件队列。
    ///
    /// 事件流按 FIFO 消费，但容量满时丢弃最旧事件，避免后台回调无限堆积。
    /// </summary>
    /// <typeparam name="T">队列元素类型。</typeparam>
    public sealed class EventQueue<T>
    {
        /// <summary>内部线程安全队列。</summary>
        private readonly ConcurrentQueue<T> queue = new ConcurrentQueue<T>();

        /// <summary>队列容量上限。</summary>
        private readonly int capacity;

        /// <summary>因容量限制丢弃的旧事件数量。</summary>
        private int dropped;

        /// <summary>
        /// 创建事件队列。
        /// </summary>
        /// <param name="capacity">后台积压容量，至少为 1。</param>
        public EventQueue(int capacity)
        {
            this.capacity = capacity < 1 ? 1 : capacity;
        }

        /// <summary>当前待消费事件数量。</summary>
        public int Count => queue.Count;

        /// <summary>因容量限制丢弃的旧事件数量。</summary>
        public int DroppedCount => dropped;

        /// <summary>
        /// 写入一条事件，并按容量丢弃最旧事件。
        /// </summary>
        public void Enqueue(T value)
        {
            queue.Enqueue(value);
            while (queue.Count > capacity && queue.TryDequeue(out _))
            {
                Interlocked.Increment(ref dropped);
            }
        }

        /// <summary>
        /// 按 FIFO 取出一条事件。
        /// </summary>
        public bool TryDequeue(out T value)
        {
            return queue.TryDequeue(out value);
        }

        /// <summary>
        /// 清空当前积压事件；用于 NATS Stop/Start 时避免旧 status event 跨连接重放。
        /// </summary>
        public void Clear()
        {
            while (queue.TryDequeue(out _))
            {
            }
        }
    }
}

using System.Collections.Concurrent;
using System.Threading;

namespace EgoAnchor.Client
{
    /// <summary>
    /// 线程安全 latest-only 队列。
    ///
    /// 后台线程可以连续 Enqueue，Unity 主线程调用 TryDequeueLatest 时只取最新值，
    /// 并返回本次跳过的旧值数量，适合 PoseResult 和 ServerHeartbeat。
    /// </summary>
    /// <typeparam name="T">队列元素类型。</typeparam>
    public sealed class LatestOnlyQueue<T>
    {
        /// <summary>内部线程安全队列。</summary>
        private readonly ConcurrentQueue<T> queue = new ConcurrentQueue<T>();

        /// <summary>队列容量上限。</summary>
        private readonly int capacity;

        /// <summary>因容量限制丢弃的旧元素数量。</summary>
        private int dropped;

        /// <summary>
        /// 创建 latest-only 队列。
        /// </summary>
        /// <param name="capacity">后台积压容量，至少为 1。</param>
        public LatestOnlyQueue(int capacity)
        {
            this.capacity = capacity < 1 ? 1 : capacity;
        }

        /// <summary>当前待消费元素数量。</summary>
        public int Count => queue.Count;

        /// <summary>因容量限制丢弃的旧元素数量。</summary>
        public int DroppedCount => dropped;

        /// <summary>
        /// 写入一条新元素，并按容量丢弃旧元素。
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
        /// 取出最新元素，并丢弃本次 drain 中更旧的元素。
        /// </summary>
        public bool TryDequeueLatest(out T value, out int skippedOlder)
        {
            value = default;
            skippedOlder = 0;
            bool hasValue = false;
            while (queue.TryDequeue(out T candidate))
            {
                if (hasValue)
                {
                    skippedOlder++;
                }

                value = candidate;
                hasValue = true;
            }

            return hasValue;
        }
    }

}

using System;
using System.Collections.Concurrent;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading;

namespace EgoAnchor.Eval
{
    /// <summary>一次评估日志写入器的最终队列统计。</summary>
    internal readonly struct EvalLogStats
    {
        /// <summary>因有界队列已满或后台写入失败而丢弃的行数。</summary>
        public readonly long DroppedRows;

        /// <summary>录制期间观察到的最大待写队列深度。</summary>
        public readonly int PeakQueueDepth;

        /// <summary>后台写入异常摘要；正常完成时为空。</summary>
        public readonly string Error;

        /// <summary>构造最终日志队列统计。</summary>
        public EvalLogStats(long droppedRows, int peakQueueDepth, string error)
        {
            DroppedRows = droppedRows;
            PeakQueueDepth = peakQueueDepth;
            Error = error ?? string.Empty;
        }
    }

    /// <summary>
    /// 评估 JSONL 后台写入器。主线程只做有界非阻塞入队，后台线程批量写入并定期 flush。
    /// </summary>
    internal sealed class EvalLog : IDisposable
    {
        /// <summary>生产环境默认最多缓存的 JSONL 行数。</summary>
        private const int DefaultCapacity = 4096;

        /// <summary>生产环境单次 flush 前最多累计的行数。</summary>
        private const int DefaultBatchSize = 64;

        /// <summary>生产环境最长 flush 间隔，单位毫秒。</summary>
        private const int DefaultFlushIntervalMs = 250;

        /// <summary>主线程与后台线程之间的有界行队列。</summary>
        private readonly BlockingCollection<string> _queue;

        /// <summary>唯一访问文件写入器的后台线程。</summary>
        private readonly Thread _worker;

        /// <summary>后台线程独占的 UTF-8 JSONL 写入器。</summary>
        private readonly StreamWriter _writer;

        /// <summary>单批最大行数。</summary>
        private readonly int _batchSize;

        /// <summary>最长 flush 间隔，单位毫秒。</summary>
        private readonly int _flushIntervalMs;

        /// <summary>因队列饱和或写入异常而丢弃的累计行数。</summary>
        private long _droppedRows;

        /// <summary>观察到的最大待写队列深度。</summary>
        private int _peakQueueDepth;

        /// <summary>已入队但尚未由后台线程取走的行数。</summary>
        private int _queuedRows;

        /// <summary>后台线程遇到的首个写入异常。</summary>
        private Exception _writerException;

        /// <summary>0 表示可写，1 表示正在或已经关闭。</summary>
        private int _disposed;

        /// <summary>当前日志写入统计快照。</summary>
        public EvalLogStats Stats => new EvalLogStats(
            Interlocked.Read(ref _droppedRows),
            Volatile.Read(ref _peakQueueDepth),
            _writerException?.ToString());

        /// <summary>打开（或创建）指定路径的 JSONL 文件。</summary>
        public EvalLog(string path)
            : this(path, DefaultCapacity, DefaultBatchSize, DefaultFlushIntervalMs)
        {
        }

        /// <summary>按指定队列和批量参数创建后台写入器，供小容量测试验证饱和行为。</summary>
        internal EvalLog(string path, int capacity, int batchSize, int flushIntervalMs)
            : this(path, capacity, batchSize, flushIntervalMs, true)
        {
        }

        /// <summary>创建可选择延迟启动消费者的写入器；关闭自动启动仅供有界队列单元测试使用。</summary>
        internal EvalLog(string path, int capacity, int batchSize, int flushIntervalMs, bool startWorker)
        {
            if (capacity <= 0) throw new ArgumentOutOfRangeException(nameof(capacity));
            if (batchSize <= 0) throw new ArgumentOutOfRangeException(nameof(batchSize));
            if (flushIntervalMs <= 0) throw new ArgumentOutOfRangeException(nameof(flushIntervalMs));

            string dir = Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(dir))
            {
                Directory.CreateDirectory(dir);
            }
            _writer = new StreamWriter(path, false, new UTF8Encoding(false));
            _queue = new BlockingCollection<string>(new ConcurrentQueue<string>(), capacity);
            _batchSize = batchSize;
            _flushIntervalMs = flushIntervalMs;
            if (!startWorker) return;

            _worker = new Thread(WriteLoop)
            {
                IsBackground = true,
                Name = $"EvalLog:{Path.GetFileName(path)}",
            };
            _worker.Start();
        }

        /// <summary>非阻塞入队一行 JSON；队列饱和时丢弃该行并累计诊断计数。</summary>
        public void Write(string json)
        {
            if (Volatile.Read(ref _disposed) != 0 || json == null)
            {
                return;
            }

            try
            {
                int queueDepth = Interlocked.Increment(ref _queuedRows);
                if (!_queue.TryAdd(json))
                {
                    Interlocked.Decrement(ref _queuedRows);
                    Interlocked.Increment(ref _droppedRows);
                    return;
                }

                UpdatePeakQueueDepth(queueDepth);
            }
            catch (InvalidOperationException)
            {
                Interlocked.Decrement(ref _queuedRows);
                Interlocked.Increment(ref _droppedRows);
            }
        }

        /// <summary>完成队列、等待后台线程写完剩余数据并强制 flush；安全可重入。</summary>
        public void Dispose()
        {
            if (Interlocked.Exchange(ref _disposed, 1) != 0)
            {
                return;
            }

            _queue.CompleteAdding();
            if (_worker != null)
            {
                _worker.Join();
            }
            else
            {
                WriteLoop();
            }
            if (_writerException != null)
            {
                while (_queue.TryTake(out _))
                {
                    Interlocked.Decrement(ref _queuedRows);
                    Interlocked.Increment(ref _droppedRows);
                }
            }
            try
            {
                _writer.Flush();
            }
            catch (Exception exc)
            {
                if (_writerException == null) _writerException = exc;
            }
            finally
            {
                try
                {
                    _writer.Dispose();
                }
                catch (Exception exc)
                {
                    if (_writerException == null) _writerException = exc;
                }
                _queue.Dispose();
            }
        }

        /// <summary>后台线程：按批量大小或最长等待时间写入并 flush。</summary>
        private void WriteLoop()
        {
            int pendingSinceFlush = 0;
            var flushTimer = Stopwatch.StartNew();
            try
            {
                while (!_queue.IsCompleted)
                {
                    if (_queue.TryTake(out string json, _flushIntervalMs))
                    {
                        Interlocked.Decrement(ref _queuedRows);
                        _writer.WriteLine(json);
                        pendingSinceFlush++;
                    }

                    bool reachedBatchSize = pendingSinceFlush >= _batchSize;
                    bool reachedFlushInterval = flushTimer.ElapsedMilliseconds >= _flushIntervalMs;
                    if (pendingSinceFlush <= 0 || (!reachedBatchSize && !reachedFlushInterval))
                    {
                        continue;
                    }

                    _writer.Flush();
                    pendingSinceFlush = 0;
                    flushTimer.Restart();
                }

                if (pendingSinceFlush > 0)
                {
                    _writer.Flush();
                }
            }
            catch (Exception exc)
            {
                _writerException = exc;
                Interlocked.Increment(ref _droppedRows);
                while (_queue.TryTake(out _))
                {
                    Interlocked.Decrement(ref _queuedRows);
                    Interlocked.Increment(ref _droppedRows);
                }
            }
        }

        /// <summary>用无锁比较交换维护队列峰值。</summary>
        private void UpdatePeakQueueDepth(int candidate)
        {
            int observed = Volatile.Read(ref _peakQueueDepth);
            while (candidate > observed)
            {
                int previous = Interlocked.CompareExchange(ref _peakQueueDepth, candidate, observed);
                if (previous == observed) return;
                observed = previous;
            }
        }
    }
}

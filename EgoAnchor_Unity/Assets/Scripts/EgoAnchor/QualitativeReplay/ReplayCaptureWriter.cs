using System;
using System.Collections.Concurrent;
using System.IO;
using System.Threading;
using Google.Protobuf;

namespace EgoAnchor.QualitativeReplay
{
    /// <summary>后台 writer 的只读停止态统计。</summary>
    public readonly struct ReplayWriterStats
    {
        /// <summary>成功写出的完整样本数。</summary>
        public readonly int SamplesWritten;

        /// <summary>队列满时整条丢弃的样本数。</summary>
        public readonly int QueueDropped;

        /// <summary>写文件或追加 JSONL 失败的样本数。</summary>
        public readonly int WriteFailures;

        /// <summary>队列峰值。</summary>
        public readonly int PeakQueueDepth;

        /// <summary>成功写出的 JPEG 总字节数。</summary>
        public readonly long ImageBytesWritten;

        /// <summary>首个后台异常；无异常时为空。</summary>
        public readonly string Error;

        /// <summary>构造一份不可变 writer 统计。</summary>
        public ReplayWriterStats(
            int samplesWritten,
            int queueDropped,
            int writeFailures,
            int peakQueueDepth,
            long imageBytesWritten,
            string error)
        {
            SamplesWritten = samplesWritten;
            QueueDropped = queueDropped;
            WriteFailures = writeFailures;
            PeakQueueDepth = peakQueueDepth;
            ImageBytesWritten = imageBytesWritten;
            Error = error ?? string.Empty;
        }
    }

    /// <summary>后台队列中的一条 JPEG 与对应 JSONL 元数据。</summary>
    internal sealed class ReplayWriteItem
    {
        /// <summary>不可变左目 JPEG。</summary>
        public readonly ByteString Image;

        /// <summary>相对 capture 目录的最终 JPEG 路径。</summary>
        public readonly string RelativeImagePath;

        /// <summary>主线程已经序列化完成的一行 JSON。</summary>
        public readonly string SampleJson;

        /// <summary>构造一条原子写入任务。</summary>
        public ReplayWriteItem(ByteString image, string relativeImagePath, string sampleJson)
        {
            Image = image ?? ByteString.Empty;
            RelativeImagePath = relativeImagePath ?? string.Empty;
            SampleJson = sampleJson ?? string.Empty;
        }

        /// <summary>从普通字节数组构造写入任务，供不引用 Protobuf 的调用方使用。</summary>
        public static ReplayWriteItem FromBytes(byte[] image, string relativeImagePath, string sampleJson)
        {
            return new ReplayWriteItem(
                ByteString.CopyFrom(image ?? Array.Empty<byte>()),
                relativeImagePath,
                sampleJson);
        }
    }

    /// <summary>
    /// 定性 replay 的单线程有界 writer。
    /// 主线程只调用非阻塞 TryEnqueue；worker 先原子发布 JPEG，再追加 samples.jsonl。
    /// </summary>
    internal sealed class ReplayCaptureWriter : IDisposable
    {
        /// <summary>capture 的 .inprogress 目录。</summary>
        private readonly string captureDirectory;

        /// <summary>带目录分隔符的路径边界，防止同前缀兄弟目录误通过。</summary>
        private readonly string captureDirectoryPrefix;

        /// <summary>样本 JSONL 文件路径。</summary>
        private readonly string samplesPath;

        /// <summary>有界写入队列。</summary>
        private readonly BlockingCollection<ReplayWriteItem> queue;

        /// <summary>唯一后台写线程。</summary>
        private readonly Thread worker;

        /// <summary>异常文本锁。</summary>
        private readonly object errorLock = new object();

        /// <summary>是否已经拒绝新任务。</summary>
        private int completing;

        /// <summary>成功样本数。</summary>
        private int samplesWritten;

        /// <summary>队列满丢弃数。</summary>
        private int queueDropped;

        /// <summary>写入失败数。</summary>
        private int writeFailures;

        /// <summary>队列峰值。</summary>
        private int peakQueueDepth;

        /// <summary>JPEG 总字节数。</summary>
        private long imageBytesWritten;

        /// <summary>首个后台异常。</summary>
        private string error = string.Empty;

        /// <summary>构造 writer 并立即启动后台线程。</summary>
        /// <param name="captureDirectory">已创建的 .inprogress capture 目录。</param>
        /// <param name="capacity">最大排队样本数。</param>
        public ReplayCaptureWriter(string captureDirectory, int capacity)
        {
            this.captureDirectory = Path.GetFullPath(captureDirectory);
            captureDirectoryPrefix = this.captureDirectory.TrimEnd(
                Path.DirectorySeparatorChar,
                Path.AltDirectorySeparatorChar) + Path.DirectorySeparatorChar;
            samplesPath = Path.Combine(this.captureDirectory, "samples.jsonl");
            Directory.CreateDirectory(this.captureDirectory);
            Directory.CreateDirectory(Path.Combine(this.captureDirectory, "images"));
            queue = new BlockingCollection<ReplayWriteItem>(Math.Max(1, capacity));
            worker = new Thread(WorkerLoop)
            {
                IsBackground = true,
                Name = "EgoAnchorQualitativeReplayWriter",
            };
            worker.Start();
        }

        /// <summary>当前停止态或运行态统计快照。</summary>
        public ReplayWriterStats Stats
        {
            get
            {
                string currentError;
                lock (errorLock)
                {
                    currentError = error;
                }
                return new ReplayWriterStats(
                    Volatile.Read(ref samplesWritten),
                    Volatile.Read(ref queueDropped),
                    Volatile.Read(ref writeFailures),
                    Volatile.Read(ref peakQueueDepth),
                    Interlocked.Read(ref imageBytesWritten),
                    currentError);
            }
        }

        /// <summary>非阻塞入队；队列满或已经停止时整条样本丢弃。</summary>
        /// <param name="item">JPEG 与 JSON 元数据。</param>
        /// <returns>是否成功进入后台队列。</returns>
        public bool TryEnqueue(ReplayWriteItem item)
        {
            if (item == null || Volatile.Read(ref completing) != 0 || !queue.TryAdd(item))
            {
                Interlocked.Increment(ref queueDropped);
                return false;
            }

            UpdatePeak(queue.Count);
            return true;
        }

        /// <summary>拒绝新样本、排空队列并等待 worker 退出。</summary>
        public void CompleteAndWait()
        {
            if (Interlocked.Exchange(ref completing, 1) == 0)
            {
                queue.CompleteAdding();
            }
            worker.Join();
        }

        /// <summary>按 IDisposable 约定完整排空队列。</summary>
        public void Dispose()
        {
            CompleteAndWait();
            queue.Dispose();
        }

        /// <summary>后台 FIFO 写入循环。</summary>
        private void WorkerLoop()
        {
            try
            {
                using StreamWriter samples = new StreamWriter(samplesPath, append: false);
                foreach (ReplayWriteItem item in queue.GetConsumingEnumerable())
                {
                    WriteOne(samples, item);
                }
                samples.Flush();
                if (samples.BaseStream is FileStream stream)
                {
                    stream.Flush(true);
                }
            }
            catch (Exception exc)
            {
                RecordFailure(exc);
                while (queue.TryTake(out _))
                {
                    Interlocked.Increment(ref writeFailures);
                }
            }
        }

        /// <summary>先原子落图，再追加一行元数据。</summary>
        private void WriteOne(StreamWriter samples, ReplayWriteItem item)
        {
            string finalPath = Path.GetFullPath(Path.Combine(captureDirectory, item.RelativeImagePath));
            if (!finalPath.StartsWith(captureDirectoryPrefix, StringComparison.OrdinalIgnoreCase))
            {
                RecordFailure(new IOException($"replay image path escaped capture directory: {finalPath}"));
                return;
            }

            string temporaryPath = finalPath + ".tmp";
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(finalPath) ?? captureDirectory);
                using (FileStream stream = new FileStream(
                    temporaryPath,
                    FileMode.Create,
                    FileAccess.Write,
                    FileShare.None,
                    64 * 1024,
                    FileOptions.SequentialScan))
                {
                    item.Image.WriteTo(stream);
                }
                File.Move(temporaryPath, finalPath);
                samples.WriteLine(item.SampleJson);
                Interlocked.Increment(ref samplesWritten);
                Interlocked.Add(ref imageBytesWritten, item.Image.Length);
            }
            catch (Exception exc)
            {
                TryDeleteTemporary(temporaryPath);
                RecordFailure(exc);
            }
        }

        /// <summary>只记录首个异常文本，同时累计失败样本数。</summary>
        private void RecordFailure(Exception exc)
        {
            Interlocked.Increment(ref writeFailures);
            lock (errorLock)
            {
                if (string.IsNullOrEmpty(error))
                {
                    error = exc?.ToString() ?? "unknown replay writer error";
                }
            }
        }

        /// <summary>更新队列峰值，避免使用锁阻塞主线程。</summary>
        private void UpdatePeak(int depth)
        {
            int current = Volatile.Read(ref peakQueueDepth);
            while (depth > current)
            {
                int observed = Interlocked.CompareExchange(ref peakQueueDepth, depth, current);
                if (observed == current)
                {
                    return;
                }
                current = observed;
            }
        }

        /// <summary>尽力清理尚未发布的临时 JPEG。</summary>
        private static void TryDeleteTemporary(string path)
        {
            try
            {
                if (File.Exists(path))
                {
                    File.Delete(path);
                }
            }
            catch
            {
                // 保留原始写入异常；临时文件只位于已校验的 capture 目录内。
            }
        }
    }
}

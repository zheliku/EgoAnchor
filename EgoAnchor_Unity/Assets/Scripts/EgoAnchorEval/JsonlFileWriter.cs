using System;
using System.IO;
using System.Text;
using UnityEngine;

namespace EgoAnchorEval
{
    /// <summary>
    /// 线程安全的 JSONL 单行追加写入器，用于评估日志的低开销落盘。
    /// </summary>
    public sealed class JsonlFileWriter : IDisposable
    {
        /// <summary>底层 UTF-8 文本写入器。</summary>
        private readonly StreamWriter writer;

        /// <summary>累计多少行后主动 flush，避免每帧写盘过重。</summary>
        private readonly int flushEveryLines;

        /// <summary>距离上次 flush 后写入的行数。</summary>
        private int sinceFlush;

        /// <summary>保护 writer 与计数器的同步锁。</summary>
        private readonly object syncRoot = new object();

        /// <summary>是否已经释放底层 writer。</summary>
        private bool disposed;

        /// <summary>
        /// 创建 JSONL 写入器，并确保目标目录存在。
        /// </summary>
        /// <param name="filePath">要覆盖写入的 JSONL 文件路径。</param>
        /// <param name="flushEveryLines">每写入多少行自动 flush 一次，最小值为 1。</param>
        public JsonlFileWriter(string filePath, int flushEveryLines = 64)
        {
            string directory = Path.GetDirectoryName(filePath);
            if (!string.IsNullOrEmpty(directory))
            {
                Directory.CreateDirectory(directory);
            }

            writer = new StreamWriter(filePath, append: false, new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
            this.flushEveryLines = Mathf.Max(1, flushEveryLines);
        }

        /// <summary>
        /// 写入一行已经序列化好的 JSON 文本，并追加换行符。
        /// </summary>
        /// <param name="jsonLine">不包含换行符的一行 JSON 文本。</param>
        public void WriteLine(string jsonLine)
        {
            lock (syncRoot)
            {
                ThrowIfDisposed();
                writer.Write(jsonLine);
                writer.Write('\n');
                if (++sinceFlush >= flushEveryLines)
                {
                    writer.Flush();
                    sinceFlush = 0;
                }
            }
        }

        /// <summary>
        /// 立即刷新缓冲区，并重置自动 flush 计数。
        /// </summary>
        public void Flush()
        {
            lock (syncRoot)
            {
                ThrowIfDisposed();
                writer.Flush();
                sinceFlush = 0;
            }
        }

        /// <summary>
        /// 刷新并释放底层文件句柄。
        /// </summary>
        public void Dispose()
        {
            lock (syncRoot)
            {
                if (disposed)
                {
                    return;
                }

                writer.Flush();
                writer.Dispose();
                disposed = true;
            }
        }

        /// <summary>
        /// 防止释放后继续写入导致静默丢数据。
        /// </summary>
        private void ThrowIfDisposed()
        {
            if (disposed)
            {
                throw new ObjectDisposedException(nameof(JsonlFileWriter));
            }
        }
    }
}

using System;
using System.IO;
using System.Text;

namespace EgoAnchor.Eval
{
    /// <summary>
    /// 评估 JSONL 文件写入器。只管文件打开、逐行写入、关闭，不关心内容格式。
    /// </summary>
    internal sealed class EvalLog : IDisposable
    {
        private StreamWriter _writer;
        private bool _disposed;

        /// <summary>打开（或创建）指定路径的 JSONL 文件。</summary>
        public EvalLog(string path)
        {
            string dir = Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(dir))
            {
                Directory.CreateDirectory(dir);
            }
            _writer = new StreamWriter(path, false, new UTF8Encoding(false));
        }

        /// <summary>写入一行 JSON 对象并立即 flush，确保进程中断时数据不丢失。</summary>
        public void Write(string json)
        {
            if (_disposed || _writer == null)
            {
                return;
            }
            _writer.WriteLine(json);
            _writer.Flush();
        }

        /// <summary>关闭文件，安全可重入。</summary>
        public void Dispose()
        {
            if (_disposed)
            {
                return;
            }
            _disposed = true;
            try
            {
                _writer?.Flush();
            }
            finally
            {
                _writer?.Dispose();
                _writer = null;
            }
        }
    }
}

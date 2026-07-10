using System;
using System.Text;

namespace EgoAnchor.Eval
{
    /// <summary>
    /// 评估状态面板的公共文本格式器，统一录制标记、session、时长和活动行样式。
    /// </summary>
    public static class EvalStatusText
    {
        /// <summary>活动行使用的 TextMesh Pro 富文本颜色。</summary>
        private const string SelectionColor = "#FFD700";

        /// <summary>根据录制状态返回带实心或空心标记的文本。</summary>
        public static string Recording(bool recording)
        {
            return recording ? "● Recording" : "○ Not Recording";
        }

        /// <summary>格式化 session id；空值表示尚未建立 session。</summary>
        public static string Session(string sessionId)
        {
            return string.IsNullOrWhiteSpace(sessionId)
                ? "Session: Not Started"
                : $"Session: {sessionId}";
        }

        /// <summary>把秒数格式化为稳定的 mm:ss；负值或非有限值按零处理。</summary>
        public static string Duration(double seconds)
        {
            int totalSeconds = double.IsNaN(seconds)
                || double.IsInfinity(seconds)
                || seconds <= 0.0
                    ? 0
                    : (int)Math.Min(Math.Floor(seconds), int.MaxValue);
            return $"{totalSeconds / 60:00}:{totalSeconds % 60:00}";
        }

        /// <summary>追加一行快捷键文本；活动行使用统一金色粗体和指示符。</summary>
        public static void AppendSelectionRow(
            StringBuilder builder,
            string content,
            bool selected)
        {
            if (builder == null) throw new ArgumentNullException(nameof(builder));

            if (selected)
            {
                builder.Append("<color=")
                    .Append(SelectionColor)
                    .Append("><b>")
                    .Append(content)
                    .Append("  ◀</b></color>\n");
                return;
            }

            builder.Append(content).Append('\n');
        }
    }
}

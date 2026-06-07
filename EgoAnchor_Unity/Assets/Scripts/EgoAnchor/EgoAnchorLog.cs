using System;
using System.Globalization;
using System.IO;
using System.Runtime.CompilerServices;
using UnityEngine;

namespace EgoAnchor.Diagnostics
{
    /// <summary>
    /// EgoAnchor Unity 侧统一日志门面。
    ///
    /// 日志输出采用接近 loguru 的结构化前缀：
    /// time | level | caller - message。
    /// Rich Text 让时间、调用点和等级消息使用接近 loguru 的配色，方便在 Unity Console 中扫描。
    /// </summary>
    public static class EgoAnchorLog
    {
        /// <summary>日志等级；数值越大越严重。</summary>
        public enum Level
        {
            /// <summary>调试日志。</summary>
            Debug = 10,

            /// <summary>普通信息日志。</summary>
            Info = 20,

            /// <summary>警告日志。</summary>
            Warning = 30,

            /// <summary>错误日志。</summary>
            Error = 40,

            /// <summary>严重错误日志。</summary>
            Critical = 50,
        }

        /// <summary>全局日志开关；关闭时所有 EgoAnchorLog 输出都会被抑制。</summary>
        public static bool Enabled { get; set; } = true;

        /// <summary>最小输出等级；默认允许 Debug 及以上。</summary>
        public static Level MinimumLevel { get; set; } = Level.Debug;

        /// <summary>是否启用 Unity Console Rich Text 颜色。</summary>
        public static bool UseRichText { get; set; } = true;

        /// <summary>时间字段颜色；对应 loguru 的绿色。</summary>
        private const string TimeColor = "#259B47";

        /// <summary>调用点字段颜色；对应 loguru 的青色。</summary>
        private const string CallerColor = "#168A9F";

        /// <summary>Debug 等级颜色；对应 loguru 的蓝色。</summary>
        private const string DebugColor = "#3D7FCF";

        /// <summary>Info 等级颜色；空值表示使用 Unity Console 默认前景色，仅加粗。</summary>
        private const string InfoColor = "";

        /// <summary>Warning 等级颜色；对应 loguru 的黄色。</summary>
        private const string WarningColor = "#B58B19";

        /// <summary>Error 等级颜色；对应 loguru 的红色。</summary>
        private const string ErrorColor = "#D45A55";

        /// <summary>Critical 等级颜色；Unity Rich Text 不支持稳定背景色，因此使用更强红色。</summary>
        private const string CriticalColor = "#F04A4A";

        /// <summary>未知等级颜色；使用接近 loguru caller 的青色。</summary>
        private const string FallbackColor = "#168A9F";

        /// <summary>
        /// 绑定组件名后的轻量日志通道。
        /// </summary>
        public readonly struct Channel
        {
            /// <summary>当前通道组件名。</summary>
            private readonly string component;

            /// <summary>
            /// 创建一个日志通道。
            /// </summary>
            /// <param name="component">组件名。</param>
            internal Channel(string component)
            {
                this.component = string.IsNullOrWhiteSpace(component) ? "EgoAnchor" : component.Trim();
            }

            /// <summary>输出 Debug 日志。</summary>
            public void Debug(
                string message,
                UnityEngine.Object context = null,
                [CallerMemberName] string memberName = "",
                [CallerLineNumber] int lineNumber = 0,
                [CallerFilePath] string filePath = "")
            {
                EgoAnchorLog.Debug(component, message, context, memberName, lineNumber, filePath);
            }

            /// <summary>输出 Info 日志。</summary>
            public void Info(
                string message,
                UnityEngine.Object context = null,
                [CallerMemberName] string memberName = "",
                [CallerLineNumber] int lineNumber = 0,
                [CallerFilePath] string filePath = "")
            {
                EgoAnchorLog.Info(component, message, context, memberName, lineNumber, filePath);
            }

            /// <summary>输出 Warning 日志。</summary>
            public void Warning(
                string message,
                UnityEngine.Object context = null,
                [CallerMemberName] string memberName = "",
                [CallerLineNumber] int lineNumber = 0,
                [CallerFilePath] string filePath = "")
            {
                EgoAnchorLog.Warning(component, message, context, memberName, lineNumber, filePath);
            }

            /// <summary>输出 Error 日志。</summary>
            public void Error(
                string message,
                UnityEngine.Object context = null,
                [CallerMemberName] string memberName = "",
                [CallerLineNumber] int lineNumber = 0,
                [CallerFilePath] string filePath = "")
            {
                EgoAnchorLog.Error(component, message, context, memberName, lineNumber, filePath);
            }

            /// <summary>输出 Critical 日志。</summary>
            public void Critical(
                string message,
                UnityEngine.Object context = null,
                [CallerMemberName] string memberName = "",
                [CallerLineNumber] int lineNumber = 0,
                [CallerFilePath] string filePath = "")
            {
                EgoAnchorLog.Critical(component, message, context, memberName, lineNumber, filePath);
            }
        }

        /// <summary>
        /// 根据类型名创建日志通道。
        /// </summary>
        /// <typeparam name="T">组件类型。</typeparam>
        /// <returns>绑定类型名的日志通道。</returns>
        public static Channel For<T>()
        {
            return new Channel(typeof(T).Name);
        }

        /// <summary>
        /// 根据显式组件名创建日志通道。
        /// </summary>
        /// <param name="component">组件名。</param>
        /// <returns>绑定组件名的日志通道。</returns>
        public static Channel For(string component)
        {
            return new Channel(component);
        }

        /// <summary>输出 Debug 日志。</summary>
        public static void Debug(
            string component,
            string message,
            UnityEngine.Object context = null,
            [CallerMemberName] string memberName = "",
            [CallerLineNumber] int lineNumber = 0,
            [CallerFilePath] string filePath = "")
        {
            if (!ShouldLog(Level.Debug))
            {
                return;
            }

            UnityEngine.Debug.Log(Format(Level.Debug, Caller(filePath, memberName, lineNumber), message), context);
        }

        /// <summary>输出 Info 日志。</summary>
        public static void Info(
            string component,
            string message,
            UnityEngine.Object context = null,
            [CallerMemberName] string memberName = "",
            [CallerLineNumber] int lineNumber = 0,
            [CallerFilePath] string filePath = "")
        {
            if (!ShouldLog(Level.Info))
            {
                return;
            }

            UnityEngine.Debug.Log(Format(Level.Info, Caller(filePath, memberName, lineNumber), message), context);
        }

        /// <summary>输出 Warning 日志。</summary>
        public static void Warning(
            string component,
            string message,
            UnityEngine.Object context = null,
            [CallerMemberName] string memberName = "",
            [CallerLineNumber] int lineNumber = 0,
            [CallerFilePath] string filePath = "")
        {
            if (!ShouldLog(Level.Warning))
            {
                return;
            }

            UnityEngine.Debug.LogWarning(Format(Level.Warning, Caller(filePath, memberName, lineNumber), message), context);
        }

        /// <summary>输出 Error 日志。</summary>
        public static void Error(
            string component,
            string message,
            UnityEngine.Object context = null,
            [CallerMemberName] string memberName = "",
            [CallerLineNumber] int lineNumber = 0,
            [CallerFilePath] string filePath = "")
        {
            if (!ShouldLog(Level.Error))
            {
                return;
            }

            UnityEngine.Debug.LogError(Format(Level.Error, Caller(filePath, memberName, lineNumber), message), context);
        }

        /// <summary>输出 Critical 日志。</summary>
        public static void Critical(
            string component,
            string message,
            UnityEngine.Object context = null,
            [CallerMemberName] string memberName = "",
            [CallerLineNumber] int lineNumber = 0,
            [CallerFilePath] string filePath = "")
        {
            if (!ShouldLog(Level.Critical))
            {
                return;
            }

            UnityEngine.Debug.LogError(Format(Level.Critical, Caller(filePath, memberName, lineNumber), message), context);
        }

        /// <summary>
        /// 生成 Unity Console 可读的结构化日志文本。
        /// </summary>
        private static string Format(Level level, string caller, string message)
        {
            string timeText = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff", CultureInfo.InvariantCulture);
            string levelText = Label(level).PadRight(8);
            string callerText = string.IsNullOrWhiteSpace(caller) ? "unknown:<module>:0" : caller.Trim();
            string levelColor = ColorFor(level);
            return $"{Color(timeText, TimeColor)} | {Style(levelText, levelColor, bold: true)} | {Color(callerText, CallerColor)} - {Style(message ?? string.Empty, levelColor, bold: true)}";
        }

        /// <summary>生成与 Python 端一致的 module:function:line 调用点文本。</summary>
        private static string Caller(string filePath, string memberName, int lineNumber)
        {
            string module = string.IsNullOrWhiteSpace(filePath)
                ? "unknown"
                : Path.GetFileNameWithoutExtension(filePath);
            string member = string.IsNullOrWhiteSpace(memberName) ? "<module>" : BracketMember(memberName);
            return $"{module}:{member}:{lineNumber}";
        }

        /// <summary>把成员名统一显示为 &lt;member&gt; 形式。</summary>
        private static string BracketMember(string memberName)
        {
            string value = string.IsNullOrWhiteSpace(memberName) ? "module" : memberName.Trim();
            return value.StartsWith("<", StringComparison.Ordinal) && value.EndsWith(">", StringComparison.Ordinal)
                ? value
                : $"<{value}>";
        }

        /// <summary>判断当前等级是否允许输出。</summary>
        private static bool ShouldLog(Level level)
        {
            return Enabled && level >= MinimumLevel;
        }

        /// <summary>返回日志等级显示文本。</summary>
        private static string Label(Level level)
        {
            switch (level)
            {
                case Level.Debug:
                    return "DEBUG";
                case Level.Info:
                    return "INFO";
                case Level.Warning:
                    return "WARNING";
                case Level.Error:
                    return "ERROR";
                case Level.Critical:
                    return "CRITICAL";
                default:
                    return level.ToString().ToUpperInvariant();
            }
        }

        /// <summary>返回日志等级颜色。</summary>
        private static string ColorFor(Level level)
        {
            switch (level)
            {
                case Level.Debug:
                    return DebugColor;
                case Level.Info:
                    return InfoColor;
                case Level.Warning:
                    return WarningColor;
                case Level.Error:
                    return ErrorColor;
                case Level.Critical:
                    return CriticalColor;
                default:
                    return FallbackColor;
            }
        }

        /// <summary>按需给结构字段添加 Unity Rich Text 颜色。</summary>
        private static string Color(string value, string hex)
        {
            return Style(value, hex, bold: false);
        }

        /// <summary>按需给日志片段添加 Unity Rich Text 颜色和加粗。</summary>
        private static string Style(string value, string hex, bool bold)
        {
            if (!UseRichText)
            {
                return value;
            }

            string output = value;
            if (!string.IsNullOrWhiteSpace(hex))
            {
                output = $"<color={hex}>{output}</color>";
            }
            return bold ? $"<b>{output}</b>" : output;
        }
    }
}

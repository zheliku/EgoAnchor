using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace EgoAnchorEval
{
    /// <summary>
    /// 评估 session 中一个条件区间，时间单位为 Unity 单调毫秒。
    /// </summary>
    public readonly struct EvalConditionSpan
    {
        /// <summary>条件标签，例如 static、slow_head 或 occlusion。</summary>
        public readonly string Label;

        /// <summary>区间开始时间，Unity 单调毫秒。</summary>
        public readonly double StartMonoMs;

        /// <summary>区间结束时间，Unity 单调毫秒。</summary>
        public readonly double EndMonoMs;

        /// <summary>
        /// 构造条件区间。
        /// </summary>
        public EvalConditionSpan(string label, double startMonoMs, double endMonoMs)
        {
            Label = label ?? string.Empty;
            StartMonoMs = startMonoMs;
            EndMonoMs = endMonoMs;
        }
    }

    /// <summary>
    /// 评估 session 中一个瞬时事件标记。
    /// </summary>
    public readonly struct EvalEventMarker
    {
        /// <summary>事件类型，例如 occlusion、out_of_view 或 recovery。</summary>
        public readonly string Type;

        /// <summary>事件发生时间，Unity 单调毫秒。</summary>
        public readonly double MonoMs;

        /// <summary>
        /// 构造事件标记。
        /// </summary>
        public EvalEventMarker(string type, double monoMs)
        {
            Type = type ?? string.Empty;
            MonoMs = monoMs;
        }
    }

    /// <summary>
    /// session_manifest.json 构造工具；保持手写 JSON，避免 Unity JsonUtility 的数组/精度限制。
    /// </summary>
    public static class EvalSessionManifestJson
    {
        /// <summary>
        /// 构造 session manifest JSON 文本。
        /// </summary>
        public static string BuildManifest(
            string sessionId,
            string objectId,
            string unityRunMode,
            string gtSource,
            string gtController,
            double monoToUnixOffsetMs,
            double sessionStartMonoMs,
            double sessionStopMonoMs,
            IReadOnlyList<EvalConditionSpan> conditionSpans,
            IReadOnlyList<EvalEventMarker> eventMarkers,
            IReadOnlyList<string> variantLabels,
            string pythonLogFilename,
            string notes,
            string gtHoldPolicy,
            bool holdLastWhenUntracked,
            double maxHoldAgeMs)
        {
            var builder = new StringBuilder(1024);
            bool first = true;
            builder.Append('{');
            AppendStringProperty(builder, ref first, "session_id", sessionId);
            AppendStringProperty(builder, ref first, "object_id", objectId);
            AppendStringProperty(builder, ref first, "unity_run_mode", unityRunMode);
            AppendStringProperty(builder, ref first, "gt_source", gtSource);
            AppendStringProperty(builder, ref first, "gt_controller", gtController);
            AppendDoubleProperty(builder, ref first, "mono_to_unix_offset_ms", monoToUnixOffsetMs);
            AppendDoubleProperty(builder, ref first, "session_start_mono_ms", sessionStartMonoMs);
            AppendReadableTimeProperties(builder, ref first, "session_start", sessionStartMonoMs + monoToUnixOffsetMs);
            AppendDoubleProperty(builder, ref first, "session_stop_mono_ms", sessionStopMonoMs);
            AppendReadableTimeProperties(builder, ref first, "session_stop", sessionStopMonoMs + monoToUnixOffsetMs);
            AppendStringProperty(builder, ref first, "gt_hold_policy", gtHoldPolicy);
            AppendBoolProperty(builder, ref first, "hold_last_when_untracked", holdLastWhenUntracked);
            AppendDoubleProperty(builder, ref first, "max_hold_age_ms", maxHoldAgeMs);
            AppendConditionSpans(builder, ref first, conditionSpans, monoToUnixOffsetMs);
            AppendEventMarkers(builder, ref first, eventMarkers, monoToUnixOffsetMs);
            AppendStringArray(builder, ref first, "variant_labels", variantLabels);
            AppendStringProperty(builder, ref first, "python_log_filename", pythonLogFilename);
            AppendStringProperty(builder, ref first, "notes", notes);
            builder.Append('}');
            return builder.ToString();
        }

        /// <summary>
        /// 写入 condition_spans 数组。
        /// </summary>
        private static void AppendConditionSpans(StringBuilder builder, ref bool firstProperty, IReadOnlyList<EvalConditionSpan> spans, double monoToUnixOffsetMs)
        {
            AppendName(builder, ref firstProperty, "condition_spans");
            builder.Append('[');
            if (spans != null)
            {
                for (int i = 0; i < spans.Count; i++)
                {
                    if (i > 0)
                    {
                        builder.Append(',');
                    }

                    bool first = true;
                    builder.Append('{');
                    AppendStringProperty(builder, ref first, "label", spans[i].Label);
                    AppendDoubleProperty(builder, ref first, "start_mono_ms", spans[i].StartMonoMs);
                    AppendReadableTimeProperties(builder, ref first, "start", spans[i].StartMonoMs + monoToUnixOffsetMs);
                    AppendDoubleProperty(builder, ref first, "end_mono_ms", spans[i].EndMonoMs);
                    AppendReadableTimeProperties(builder, ref first, "end", spans[i].EndMonoMs + monoToUnixOffsetMs);
                    builder.Append('}');
                }
            }
            builder.Append(']');
        }

        /// <summary>
        /// 写入 event_markers 数组。
        /// </summary>
        private static void AppendEventMarkers(StringBuilder builder, ref bool firstProperty, IReadOnlyList<EvalEventMarker> markers, double monoToUnixOffsetMs)
        {
            AppendName(builder, ref firstProperty, "event_markers");
            builder.Append('[');
            if (markers != null)
            {
                for (int i = 0; i < markers.Count; i++)
                {
                    if (i > 0)
                    {
                        builder.Append(',');
                    }

                    bool first = true;
                    builder.Append('{');
                    AppendStringProperty(builder, ref first, "type", markers[i].Type);
                    AppendDoubleProperty(builder, ref first, "mono_ms", markers[i].MonoMs);
                    AppendReadableTimeProperties(builder, ref first, "marker", markers[i].MonoMs + monoToUnixOffsetMs);
                    builder.Append('}');
                }
            }
            builder.Append(']');
        }

        /// <summary>
        /// 写入字符串数组属性。
        /// </summary>
        private static void AppendStringArray(StringBuilder builder, ref bool firstProperty, string name, IReadOnlyList<string> values)
        {
            AppendName(builder, ref firstProperty, name);
            builder.Append('[');
            if (values != null)
            {
                for (int i = 0; i < values.Count; i++)
                {
                    if (i > 0)
                    {
                        builder.Append(',');
                    }

                    AppendJsonString(builder, values[i] ?? string.Empty);
                }
            }
            builder.Append(']');
        }

        /// <summary>
        /// 写入 UTC 与本地可读时间字符串。
        /// </summary>
        private static void AppendReadableTimeProperties(StringBuilder builder, ref bool first, string prefix, double unixMs)
        {
            AppendDoubleProperty(builder, ref first, $"{prefix}_unix_ms", unixMs);
            AppendStringProperty(builder, ref first, $"{prefix}_utc", FormatUtc(unixMs));
            AppendStringProperty(builder, ref first, $"{prefix}_local", FormatLocal(unixMs));
        }

        /// <summary>
        /// 写入字符串属性。
        /// </summary>
        private static void AppendStringProperty(StringBuilder builder, ref bool first, string name, string value)
        {
            AppendName(builder, ref first, name);
            AppendJsonString(builder, value ?? string.Empty);
        }

        /// <summary>
        /// 写入 double 属性。
        /// </summary>
        private static void AppendDoubleProperty(StringBuilder builder, ref bool first, string name, double value)
        {
            AppendName(builder, ref first, name);
            AppendDouble(builder, value);
        }

        /// <summary>
        /// 写入 bool 属性。
        /// </summary>
        private static void AppendBoolProperty(StringBuilder builder, ref bool first, string name, bool value)
        {
            AppendName(builder, ref first, name);
            builder.Append(value ? "true" : "false");
        }

        /// <summary>
        /// 写入属性名前缀。
        /// </summary>
        private static void AppendName(StringBuilder builder, ref bool first, string name)
        {
            if (!first)
            {
                builder.Append(',');
            }

            first = false;
            AppendJsonString(builder, name);
            builder.Append(':');
        }

        /// <summary>
        /// 按 invariant round-trip 格式写入 double。
        /// </summary>
        private static void AppendDouble(StringBuilder builder, double value)
        {
            if (double.IsNaN(value) || double.IsInfinity(value))
            {
                builder.Append("null");
                return;
            }

            builder.Append(value.ToString("R", CultureInfo.InvariantCulture));
        }

        /// <summary>
        /// 把 Unix 毫秒格式化为 ISO-8601 UTC 字符串。
        /// </summary>
        private static string FormatUtc(double unixMs)
        {
            return FromUnixMs(unixMs).ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss.fff'Z'", CultureInfo.InvariantCulture);
        }

        /// <summary>
        /// 把 Unix 毫秒格式化为本地时区字符串。
        /// </summary>
        private static string FormatLocal(double unixMs)
        {
            return FromUnixMs(unixMs).ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss.fff zzz", CultureInfo.InvariantCulture);
        }

        /// <summary>
        /// 从 double Unix 毫秒安全构造 DateTimeOffset。
        /// </summary>
        private static DateTimeOffset FromUnixMs(double unixMs)
        {
            long rounded = (long)Math.Round(unixMs, MidpointRounding.AwayFromZero);
            return DateTimeOffset.FromUnixTimeMilliseconds(rounded);
        }

        /// <summary>
        /// 写入 JSON 字符串并转义控制字符。
        /// </summary>
        private static void AppendJsonString(StringBuilder builder, string value)
        {
            builder.Append('"');
            if (!string.IsNullOrEmpty(value))
            {
                for (int i = 0; i < value.Length; i++)
                {
                    char c = value[i];
                    switch (c)
                    {
                        case '\\':
                            builder.Append("\\\\");
                            break;
                        case '"':
                            builder.Append("\\\"");
                            break;
                        case '\b':
                            builder.Append("\\b");
                            break;
                        case '\f':
                            builder.Append("\\f");
                            break;
                        case '\n':
                            builder.Append("\\n");
                            break;
                        case '\r':
                            builder.Append("\\r");
                            break;
                        case '\t':
                            builder.Append("\\t");
                            break;
                        default:
                            if (c < ' ')
                            {
                                builder.Append("\\u");
                                builder.Append(((int)c).ToString("x4", CultureInfo.InvariantCulture));
                            }
                            else
                            {
                                builder.Append(c);
                            }
                            break;
                    }
                }
            }
            builder.Append('"');
        }
    }
}

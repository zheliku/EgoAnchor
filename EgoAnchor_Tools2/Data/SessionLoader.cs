using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using EgoAnchor.Tools2.Math;

namespace EgoAnchor.Tools2.Data
{
    /// <summary>
    /// session 数据加载器:从 unity_output.jsonl 提取观测序列与 render 时间轴。
    ///
    /// 观测序列由每个唯一 source_frame_id 的第一条记录构成,取其 is_primary variant 的 aligned_raw
    /// (中性输入,所有策略共享)。render 时间轴取所有 render_mono_ms。
    /// 这样得到的观测 ~5fps、render ~60fps,与真实系统时序一致。
    /// </summary>
    public static class SessionLoader
    {
        /// <summary>
        /// 加载一个 session 的 unity_output.jsonl,返回观测序列、render 时间轴和起始时间。
        /// </summary>
        /// <param name="unityOutputPath">unity_output.jsonl 的完整路径。</param>
        /// <param name="observations">输出:按 capture 时间升序、frame_id 去重后的观测序列。</param>
        /// <param name="renderTicks">输出:按 render 时间升序的 render tick 序列。</param>
        /// <param name="firstRenderSeconds">输出:第一条 render 的时间 (秒),用作绘图零点。</param>
        public static void Load(
            string unityOutputPath,
            out List<PoseObservation> observations,
            out List<RenderTick> renderTicks,
            out double firstRenderSeconds)
        {
            observations = new List<PoseObservation>();
            renderTicks = new List<RenderTick>();

            // frame_id -> index 去重,只保留每个 source_frame_id 第一次出现的 aligned_raw
            Dictionary<long, int> seenFrameIds = new Dictionary<long, int>();
            double firstRender = double.MaxValue;
            bool hasFirst = false;

            foreach (string rawLine in File.ReadLines(unityOutputPath))
            {
                if (string.IsNullOrWhiteSpace(rawLine))
                {
                    continue;
                }

                using JsonDocument doc = JsonDocument.Parse(rawLine);
                JsonElement root = doc.RootElement;

                // 只处理 unity_output 事件
                if (!TryGetString(root, "event", out string evt) || evt != "unity_output")
                {
                    continue;
                }

                double renderMs = TryGetDouble(root, "render_mono_ms", out double rm) ? rm : 0.0;
                if (!hasFirst)
                {
                    firstRender = renderMs;
                    hasFirst = true;
                }

                long sourceFrameId = TryGetLong(root, "source_frame_id", out long sf) ? sf : -1L;
                renderTicks.Add(new RenderTick(renderMs / 1000.0, sourceFrameId));

                // 观测从 primary variant 的 aligned_raw 取
                if (!root.TryGetProperty("variants", out JsonElement variants))
                {
                    continue;
                }

                foreach (JsonElement variant in variants.EnumerateArray())
                {
                    if (!TryGetBool(variant, "is_primary", out bool isPrimary) || !isPrimary)
                    {
                        continue;
                    }

                    // 同一 source_frame_id 只保留第一次出现,避免 5fps 观测被 60fps render 重复采样
                    if (seenFrameIds.ContainsKey(sourceFrameId))
                    {
                        break;
                    }

                    if (!TryGetBool(variant, "has_aligned_raw", out bool hasAligned) || !hasAligned)
                    {
                        break;
                    }

                    if (!variant.TryGetProperty("aligned_raw_pos", out JsonElement posEl)
                        || !variant.TryGetProperty("aligned_raw_rot", out JsonElement rotEl))
                    {
                        break;
                    }

                    Vec3 pos = ReadVec3(posEl);
                    QuaternionM rot = ReadQuat(rotEl);
                    float score = TryGetFloat(variant, "latest_accepted_score", out float s) ? s : 1.0f;

                    // capture 时间:优先 source_capture_mono_ms;缺失则退化用 render 时间
                    double captureSeconds;
                    if (TryGetBool(variant, "has_source_capture_timing", out bool hasSrc) && hasSrc
                        && TryGetDouble(variant, "source_capture_mono_ms", out double capMs))
                    {
                        captureSeconds = capMs / 1000.0;
                    }
                    else
                    {
                        captureSeconds = renderMs / 1000.0;
                    }

                    seenFrameIds[sourceFrameId] = observations.Count;
                    observations.Add(new PoseObservation(sourceFrameId, captureSeconds, pos, rot, score));
                    break; // primary variant 只有一个
                }
            }

            if (!hasFirst)
            {
                firstRender = 0.0;
            }

            // 观测按 capture 时间排序 (一般已有序,但稳妥起见)
            observations.Sort((a, b) => a.CaptureTimeSeconds.CompareTo(b.CaptureTimeSeconds));
            firstRenderSeconds = firstRender / 1000.0;
        }

        /// <summary>从 JsonElement 读取 Vec3 (3 个 float 数组)。</summary>
        private static Vec3 ReadVec3(JsonElement el)
        {
            float[] v = new float[3];
            int i = 0;
            foreach (JsonElement item in el.EnumerateArray())
            {
                if (i < 3) v[i++] = item.GetSingle();
            }
            return new Vec3(v[0], v[1], v[2]);
        }

        /// <summary>从 JsonElement 读取 QuaternionM (4 个 float 数组,x,y,z,w 顺序)。</summary>
        private static QuaternionM ReadQuat(JsonElement el)
        {
            float[] v = new float[4];
            int i = 0;
            foreach (JsonElement item in el.EnumerateArray())
            {
                if (i < 4) v[i++] = item.GetSingle();
            }
            return new QuaternionM(v[0], v[1], v[2], v[3]);
        }

        private static bool TryGetString(JsonElement el, string name, out string value)
        {
            if (el.TryGetProperty(name, out JsonElement p) && p.ValueKind == JsonValueKind.String)
            {
                value = p.GetString();
                return true;
            }
            value = null;
            return false;
        }

        private static bool TryGetBool(JsonElement el, string name, out bool value)
        {
            if (el.TryGetProperty(name, out JsonElement p)
                && (p.ValueKind == JsonValueKind.True || p.ValueKind == JsonValueKind.False))
            {
                value = p.GetBoolean();
                return true;
            }
            value = false;
            return false;
        }

        private static bool TryGetDouble(JsonElement el, string name, out double value)
        {
            if (el.TryGetProperty(name, out JsonElement p) && p.ValueKind == JsonValueKind.Number)
            {
                value = p.GetDouble();
                return true;
            }
            value = 0;
            return false;
        }

        private static bool TryGetLong(JsonElement el, string name, out long value)
        {
            if (el.TryGetProperty(name, out JsonElement p) && p.ValueKind == JsonValueKind.Number)
            {
                value = p.GetInt64();
                return true;
            }
            value = 0;
            return false;
        }

        private static bool TryGetFloat(JsonElement el, string name, out float value)
        {
            if (el.TryGetProperty(name, out JsonElement p) && p.ValueKind == JsonValueKind.Number)
            {
                value = p.GetSingle();
                return true;
            }
            value = 0;
            return false;
        }

        /// <summary>
        /// 从 session_manifest.json 加载 condition_spans,返回各条件分段的时间区间。
        /// 若 manifest 缺失或无 condition_spans,返回空列表 (调用方退化为画整段)。
        /// </summary>
        /// <param name="manifestPath">session_manifest.json 的完整路径。</param>
        /// <returns>条件分段列表 (按 start 时间升序)。</returns>
        public static List<ConditionSpan> LoadConditions(string manifestPath)
        {
            List<ConditionSpan> result = new List<ConditionSpan>();
            if (!File.Exists(manifestPath))
            {
                return result;
            }

            using JsonDocument doc = JsonDocument.Parse(File.ReadAllText(manifestPath));
            JsonElement root = doc.RootElement;
            if (!root.TryGetProperty("condition_spans", out JsonElement spans) || spans.ValueKind != JsonValueKind.Array)
            {
                return result;
            }

            foreach (JsonElement span in spans.EnumerateArray())
            {
                if (!TryGetString(span, "label", out string label))
                {
                    continue;
                }

                // 优先用 mono 时间 (与 render_mono_ms 同基准);缺失时退用 unix_ms
                double startMs = TryGetDouble(span, "start_mono_ms", out double sm) ? sm
                    : (TryGetDouble(span, "start_unix_ms", out double su) ? su : 0.0);
                double endMs = TryGetDouble(span, "end_mono_ms", out double em) ? em
                    : (TryGetDouble(span, "end_unix_ms", out double eu) ? eu : 0.0);
                result.Add(new ConditionSpan(label, startMs / 1000.0, endMs / 1000.0));
            }

            result.Sort((a, b) => a.StartSeconds.CompareTo(b.StartSeconds));
            return result;
        }
    }
}

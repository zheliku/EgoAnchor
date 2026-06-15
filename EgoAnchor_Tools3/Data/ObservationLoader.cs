using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using EgoAnchor.Tools3.Core;

namespace EgoAnchor.Tools3.Data
{
    /// <summary>一帧观测 pose (真实 ~5fps 追踪输出)。时间用 mono 秒。</summary>
    public readonly struct Observation
    {
        public readonly long SourceFrameId;
        public readonly double TimeSeconds; // source_capture_mono_ms / 1000
        public readonly Pose Pose;
        public readonly double Score; // reliability_score (供 egoanchor 用)

        public Observation(long sourceFrameId, double timeSeconds, Pose pose, double score)
        {
            SourceFrameId = sourceFrameId;
            TimeSeconds = timeSeconds;
            Pose = pose;
            Score = score;
        }
    }

    /// <summary>
    /// 从 *_unity_output.jsonl 提取真实观测 pose 序列。
    ///
    /// 约定 (见项目记录 egoanchor-data-format):
    ///   观测 pose = primary 变体 (is_primary, egoanchor) 的 aligned_raw_pos/rot,
    ///   按 source_frame_id 去重, 时间戳用 source_capture_mono_ms。
    ///   该序列的实际帧率约 4.8fps (208ms)。
    /// </summary>
    public static class ObservationLoader
    {
        public static List<Observation> Load(string sessionDir)
        {
            string path = ResolveUniqueLog(sessionDir, "*_unity_output.jsonl");
            var seen = new HashSet<long>();
            var observations = new List<Observation>();

            foreach (string line in File.ReadLines(path))
            {
                if (string.IsNullOrWhiteSpace(line))
                {
                    continue;
                }

                using JsonDocument doc = JsonDocument.Parse(line);
                JsonElement root = doc.RootElement;
                long sourceFrameId = ReadLong(root, "source_frame_id", -1);
                if (sourceFrameId < 0 || seen.Contains(sourceFrameId))
                {
                    continue;
                }

                if (!root.TryGetProperty("variants", out JsonElement variants) || variants.ValueKind != JsonValueKind.Array)
                {
                    continue;
                }

                double renderMonoMs = ReadDouble(root, "render_mono_ms", 0.0);

                foreach (JsonElement variant in variants.EnumerateArray())
                {
                    if (!ReadBool(variant, "is_primary", false))
                    {
                        continue;
                    }

                    if (!ReadBool(variant, "has_aligned_raw", false))
                    {
                        break; // primary 没有 aligned_raw, 这帧跳过
                    }

                    if (!TryReadPose(variant, "aligned_raw_pos", "aligned_raw_rot", out Pose pose))
                    {
                        break;
                    }

                    double captureMs = ReadNullableDouble(variant, "source_capture_mono_ms") ?? renderMonoMs;
                    float score = ReadFloat(variant, "reliability_score", 1.0f);

                    seen.Add(sourceFrameId);
                    observations.Add(new Observation(sourceFrameId, captureMs / 1000.0, pose, score));
                    break;
                }
            }

            // 按时间排序 (source_frame_id 通常已单调, 保险起见)
            observations.Sort((a, b) => a.TimeSeconds.CompareTo(b.TimeSeconds));
            return observations;
        }

        public static string ResolveUniqueLog(string sessionDir, string pattern)
        {
            string[] matches = Directory.GetFiles(sessionDir, pattern, SearchOption.TopDirectoryOnly);
            if (matches.Length != 1)
            {
                throw new InvalidOperationException($"{sessionDir}: 期望唯一 {pattern}, 实际 {matches.Length} 个");
            }

            return matches[0];
        }

        private static bool TryReadPose(JsonElement row, string posName, string rotName, out Pose pose)
        {
            pose = Pose.Identity;
            if (!row.TryGetProperty(posName, out JsonElement pos) || pos.ValueKind != JsonValueKind.Array)
            {
                return false;
            }

            if (!row.TryGetProperty(rotName, out JsonElement rot) || rot.ValueKind != JsonValueKind.Array)
            {
                return false;
            }

            var p = new Vec3(pos[0].GetDouble(), pos[1].GetDouble(), pos[2].GetDouble());
            var q = new Quat(rot[0].GetDouble(), rot[1].GetDouble(), rot[2].GetDouble(), rot[3].GetDouble());
            pose = new Pose(p, q.Normalized());
            return true;
        }

        private static double? ReadNullableDouble(JsonElement row, string name)
        {
            if (!row.TryGetProperty(name, out JsonElement value) || value.ValueKind == JsonValueKind.Null)
            {
                return null;
            }

            return value.GetDouble();
        }

        private static double ReadDouble(JsonElement row, string name, double d)
            => row.TryGetProperty(name, out JsonElement v) && v.ValueKind != JsonValueKind.Null ? v.GetDouble() : d;

        private static float ReadFloat(JsonElement row, string name, float d)
            => row.TryGetProperty(name, out JsonElement v) && v.ValueKind != JsonValueKind.Null ? v.GetSingle() : d;

        private static long ReadLong(JsonElement row, string name, long d)
            => row.TryGetProperty(name, out JsonElement v) && v.ValueKind != JsonValueKind.Null ? v.GetInt64() : d;

        private static bool ReadBool(JsonElement row, string name, bool d)
            => row.TryGetProperty(name, out JsonElement v) && v.ValueKind != JsonValueKind.Null ? v.GetBoolean() : d;
    }
}

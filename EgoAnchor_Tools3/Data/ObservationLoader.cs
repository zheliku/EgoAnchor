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

        // 子分 + flags (来自 python_runtime.jsonl, 按 frame_id join; 无信号时为 -1 / 空)。
        // 用于区分"真实快动"(几何分仍高) vs "坏 pose"(几何分低)。
        public readonly double ScoreDepth;
        public readonly double ScoreReprojection;
        public readonly double ScoreConfidence;
        public readonly string[] ReliabilityFlags; // 永不为 null

        // 头部 (HMD/CenterEye) world pose, 来自 unity_output 根的 head_pos/head_rot。
        // 用于头动感知 static: 头动诱导的 slip 不应被误判成物体真实运动。
        public readonly bool HasHeadPose;
        public readonly Pose HeadPose;

        public Observation(
            long sourceFrameId,
            double timeSeconds,
            Pose pose,
            double score,
            double scoreDepth = -1.0,
            double scoreReprojection = -1.0,
            double scoreConfidence = -1.0,
            string[]? reliabilityFlags = null,
            bool hasHeadPose = false,
            Pose headPose = default)
        {
            SourceFrameId = sourceFrameId;
            TimeSeconds = timeSeconds;
            Pose = pose;
            Score = score;
            ScoreDepth = scoreDepth;
            ScoreReprojection = scoreReprojection;
            ScoreConfidence = scoreConfidence;
            ReliabilityFlags = reliabilityFlags ?? System.Array.Empty<string>();
            HasHeadPose = hasHeadPose;
            HeadPose = headPose;
        }

        /// <summary>是否带某个可靠性 flag (大小写不敏感)。</summary>
        public bool HasFlag(string flag)
        {
            if (ReliabilityFlags == null)
            {
                return false;
            }

            foreach (string f in ReliabilityFlags)
            {
                if (string.Equals(f, flag, StringComparison.OrdinalIgnoreCase))
                {
                    return true;
                }
            }

            return false;
        }

        /// <summary>几何证据是否不可信 (depth/reprojection 类 flag 命中) —— 用于区分坏 pose vs 真实运动。</summary>
        public bool HasGeometryConcern =>
            HasFlag("depth_alignment_low")
            || HasFlag("reprojection_low")
            || HasFlag("depth_coverage_insufficient")
            || HasFlag("no_valid_depth_in_mask");
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

            // 从 python_runtime.jsonl 按 frame_id 预读子分 + flags (unity_output 只有总分)。
            Dictionary<long, PoseScoreDetail> scoreByFrame = LoadScoreDetails(sessionDir);

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

                    scoreByFrame.TryGetValue(sourceFrameId, out PoseScoreDetail detail);

                    // 头部 pose (CenterEyeAnchor) 在 root, 用于头动感知 static (问题3)。无则 hasHead=false。
                    bool hasHead = TryReadPose(root, "head_pos", "head_rot", out Pose headPose);

                    seen.Add(sourceFrameId);
                    observations.Add(new Observation(
                        sourceFrameId,
                        captureMs / 1000.0,
                        pose,
                        score,
                        detail.ScoreDepth,
                        detail.ScoreReprojection,
                        detail.ScoreConfidence,
                        detail.Flags,
                        hasHead,
                        headPose));
                    break;
                }
            }

            // 按时间排序 (source_frame_id 通常已单调, 保险起见)
            observations.Sort((a, b) => a.TimeSeconds.CompareTo(b.TimeSeconds));
            return observations;
        }

        /// <summary>子分 + flags 明细 (来自 python_runtime pose_result, 按 frame_id)。无信号子分为 -1。</summary>
        private readonly struct PoseScoreDetail
        {
            public readonly double ScoreDepth;
            public readonly double ScoreReprojection;
            public readonly double ScoreConfidence;
            public readonly string[] Flags;

            public PoseScoreDetail(double depth, double reproj, double conf, string[] flags)
            {
                ScoreDepth = depth;
                ScoreReprojection = reproj;
                ScoreConfidence = conf;
                Flags = flags ?? System.Array.Empty<string>();
            }
        }

        /// <summary>
        /// 从 *_python_runtime.jsonl 的 pose_result 事件读取每帧子分 + reliability_flags, 按 frame_id 建表。
        /// unity_output 只透传了 reliability_score 总分, 子分/flags 在 python_runtime 里 (见 egoanchor-data-format)。
        /// 文件缺失或无 pose_result 时返回空表 (Observation 子分将为 -1、flags 为空, 算法退化为只用总分)。
        /// </summary>
        private static Dictionary<long, PoseScoreDetail> LoadScoreDetails(string sessionDir)
        {
            var map = new Dictionary<long, PoseScoreDetail>();
            string[] matches = Directory.GetFiles(sessionDir, "*_python_runtime.jsonl", SearchOption.TopDirectoryOnly);
            if (matches.Length != 1)
            {
                return map;
            }

            foreach (string line in File.ReadLines(matches[0]))
            {
                if (string.IsNullOrWhiteSpace(line))
                {
                    continue;
                }

                JsonElement root;
                try
                {
                    using JsonDocument doc = JsonDocument.Parse(line);
                    root = doc.RootElement.Clone();
                }
                catch
                {
                    continue;
                }

                if (root.ValueKind != JsonValueKind.Object
                    || !root.TryGetProperty("event", out JsonElement ev)
                    || ev.ValueKind != JsonValueKind.String
                    || ev.GetString() != "pose_result")
                {
                    continue;
                }

                long frameId = ReadLong(root, "frame_id", -1);
                if (frameId < 0)
                {
                    continue;
                }

                string[] flags = ReadStringArray(root, "reliability_flags");
                map[frameId] = new PoseScoreDetail(
                    ReadDouble(root, "score_depth", -1.0),
                    ReadDouble(root, "score_reprojection", -1.0),
                    ReadDouble(root, "score_confidence", -1.0),
                    flags);
            }

            return map;
        }

        private static string[] ReadStringArray(JsonElement row, string name)
        {
            if (!row.TryGetProperty(name, out JsonElement arr) || arr.ValueKind != JsonValueKind.Array)
            {
                return System.Array.Empty<string>();
            }

            var list = new List<string>();
            foreach (JsonElement e in arr.EnumerateArray())
            {
                if (e.ValueKind == JsonValueKind.String)
                {
                    string? s = e.GetString();
                    if (s != null)
                    {
                        list.Add(s);
                    }
                }
            }

            return list.ToArray();
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

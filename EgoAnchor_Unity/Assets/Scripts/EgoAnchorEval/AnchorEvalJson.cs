using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using UnityEngine;

namespace EgoAnchorEval
{
    /// <summary>
    /// 一条渲染 tick 中某个 runtime 变体的记录快照。
    /// </summary>
    public readonly struct RecordedVariantSnapshot
    {
        /// <summary>变体标签，例如 raw、kalman 或 controller。</summary>
        public readonly string Label;

        /// <summary>该变体当前输出位姿对应的源 frame_id。</summary>
        public readonly long SourceFrameId;

        /// <summary>是否已有 stable pose。</summary>
        public readonly bool HasStablePose;

        /// <summary>当前 stable pose；无位姿时按 identity 写出 null。</summary>
        public readonly Pose StablePose;

        /// <summary>当前 anchor 生命周期状态。</summary>
        public readonly string AnchorState;

        /// <summary>最近一次 policy 动作。</summary>
        public readonly string PolicyAction;

        /// <summary>最近一次 policy 原因。</summary>
        public readonly string PolicyReason;

        /// <summary>最近一次 Python/Unity runtime phase。</summary>
        public readonly string LatestPhase;

        /// <summary>最近一次 runtime 对齐或 pose 失败原因。</summary>
        public readonly string LatestFailure;

        /// <summary>是否是主变体；主变体额外写 aligned raw 与 reliability。</summary>
        public readonly bool IsPrimary;

        /// <summary>主变体是否已有 aligned raw pose。</summary>
        public readonly bool HasAlignedRawPose;

        /// <summary>主变体 aligned raw pose。</summary>
        public readonly Pose AlignedRawPose;

        /// <summary>主变体最近一次 reliability score。</summary>
        public readonly float ReliabilityScore;

        /// <summary>
        /// 构造变体输出快照。
        /// </summary>
        public RecordedVariantSnapshot(
            string label,
            long sourceFrameId,
            bool hasStablePose,
            Pose stablePose,
            string anchorState,
            string policyAction,
            string policyReason,
            string latestPhase,
            string latestFailure,
            bool isPrimary,
            bool hasAlignedRawPose,
            Pose alignedRawPose,
            float reliabilityScore)
        {
            Label = label ?? string.Empty;
            SourceFrameId = sourceFrameId;
            HasStablePose = hasStablePose;
            StablePose = stablePose;
            AnchorState = anchorState ?? string.Empty;
            PolicyAction = policyAction ?? string.Empty;
            PolicyReason = policyReason ?? string.Empty;
            LatestPhase = latestPhase ?? string.Empty;
            LatestFailure = latestFailure ?? string.Empty;
            IsPrimary = isPrimary;
            HasAlignedRawPose = hasAlignedRawPose;
            AlignedRawPose = alignedRawPose;
            ReliabilityScore = reliabilityScore;
        }
    }

    /// <summary>
    /// 评估日志 JSONL 单行构造工具；只做字符串拼接，不引入 JsonUtility。
    /// </summary>
    public static class AnchorEvalJson
    {
        /// <summary>
        /// 构造每个 frame_id 对应的采集记录行。
        /// </summary>
        public static string BuildCaptureLine(
            long frameId,
            double captureMonoMs,
            double captureUnixMs,
            Pose headPose,
            Pose cameraPose,
            Pose groundTruthPose,
            bool gtTracked,
            bool cameraValid = true)
        {
            return BuildCaptureLine(
                frameId,
                captureMonoMs,
                captureUnixMs,
                headPose,
                cameraPose,
                groundTruthPose,
                gtTracked,
                gtPoseValid: true,
                gtPoseSource: gtTracked ? ControllerGroundTruthProvider.SourceLiveTracked : ControllerGroundTruthProvider.SourceOvrUntracked,
                gtHoldAgeMs: 0.0,
                cameraValid);
        }

        /// <summary>
        /// 构造每个 frame_id 对应的采集记录行，并显式写出 GT pose 来源。
        /// </summary>
        public static string BuildCaptureLine(
            long frameId,
            double captureMonoMs,
            double captureUnixMs,
            Pose headPose,
            Pose cameraPose,
            Pose groundTruthPose,
            bool gtTracked,
            bool gtPoseValid,
            string gtPoseSource,
            double gtHoldAgeMs,
            bool cameraValid = true)
        {
            var builder = new StringBuilder(512);
            bool first = true;
            builder.Append('{');
            AppendStringProperty(builder, ref first, "event", "unity_capture");
            AppendLongProperty(builder, ref first, "frame_id", frameId);
            AppendDoubleProperty(builder, ref first, "capture_mono_ms", captureMonoMs);
            AppendDoubleProperty(builder, ref first, "capture_unix_ms", captureUnixMs);
            AppendReadableTimeProperties(builder, ref first, "capture", captureUnixMs);
            AppendPoseProperties(builder, ref first, "head_pos", "head_rot", headPose, hasPose: true);
            AppendBoolProperty(builder, ref first, "cam_valid", cameraValid);
            AppendPoseProperties(builder, ref first, "cam_pos", "cam_rot", cameraPose, cameraValid);
            AppendPoseProperties(builder, ref first, "gt_pos", "gt_rot", groundTruthPose, gtPoseValid);
            AppendBoolProperty(builder, ref first, "gt_tracked", gtTracked);
            AppendBoolProperty(builder, ref first, "gt_pose_valid", gtPoseValid);
            AppendStringProperty(builder, ref first, "gt_pose_source", gtPoseSource);
            AppendDoubleProperty(builder, ref first, "gt_hold_age_ms", gtHoldAgeMs);
            builder.Append('}');
            return builder.ToString();
        }

        /// <summary>
        /// 构造每个渲染 tick 对应的输出记录行。
        /// </summary>
        public static string BuildOutputLine(
            double renderMonoMs,
            double renderUnixMs,
            long sourceFrameId,
            Pose headPose,
            Pose groundTruthPose,
            bool gtTracked,
            IReadOnlyList<RecordedVariantSnapshot> variants)
        {
            return BuildOutputLine(
                renderMonoMs,
                renderUnixMs,
                sourceFrameId,
                headPose,
                groundTruthPose,
                gtTracked,
                gtPoseValid: true,
                gtPoseSource: gtTracked ? ControllerGroundTruthProvider.SourceLiveTracked : ControllerGroundTruthProvider.SourceOvrUntracked,
                gtHoldAgeMs: 0.0,
                variants);
        }

        /// <summary>
        /// 构造每个渲染 tick 对应的输出记录行，并显式写出 GT pose 来源。
        /// </summary>
        public static string BuildOutputLine(
            double renderMonoMs,
            double renderUnixMs,
            long sourceFrameId,
            Pose headPose,
            Pose groundTruthPose,
            bool gtTracked,
            bool gtPoseValid,
            string gtPoseSource,
            double gtHoldAgeMs,
            IReadOnlyList<RecordedVariantSnapshot> variants)
        {
            var builder = new StringBuilder(1024);
            bool first = true;
            builder.Append('{');
            AppendStringProperty(builder, ref first, "event", "unity_output");
            AppendDoubleProperty(builder, ref first, "render_mono_ms", renderMonoMs);
            AppendDoubleProperty(builder, ref first, "render_unix_ms", renderUnixMs);
            AppendReadableTimeProperties(builder, ref first, "render", renderUnixMs);
            AppendLongProperty(builder, ref first, "source_frame_id", sourceFrameId);
            AppendPoseProperties(builder, ref first, "head_pos", "head_rot", headPose, hasPose: true);
            AppendPoseProperties(builder, ref first, "gt_pos", "gt_rot", groundTruthPose, gtPoseValid);
            AppendBoolProperty(builder, ref first, "gt_tracked", gtTracked);
            AppendBoolProperty(builder, ref first, "gt_pose_valid", gtPoseValid);
            AppendStringProperty(builder, ref first, "gt_pose_source", gtPoseSource);
            AppendDoubleProperty(builder, ref first, "gt_hold_age_ms", gtHoldAgeMs);
            AppendVariants(builder, ref first, variants);
            builder.Append('}');
            return builder.ToString();
        }

        /// <summary>
        /// 写入 variants 数组。
        /// </summary>
        private static void AppendVariants(StringBuilder builder, ref bool firstProperty, IReadOnlyList<RecordedVariantSnapshot> variants)
        {
            AppendName(builder, ref firstProperty, "variants");
            builder.Append('[');
            if (variants != null)
            {
                for (int i = 0; i < variants.Count; i++)
                {
                    if (i > 0)
                    {
                        builder.Append(',');
                    }

                    AppendVariant(builder, variants[i]);
                }
            }
            builder.Append(']');
        }

        /// <summary>
        /// 写入单个 runtime 变体对象。
        /// </summary>
        private static void AppendVariant(StringBuilder builder, RecordedVariantSnapshot variant)
        {
            bool first = true;
            builder.Append('{');
            AppendStringProperty(builder, ref first, "label", variant.Label);
            AppendBoolProperty(builder, ref first, "is_primary", variant.IsPrimary);
            AppendLongProperty(builder, ref first, "source_frame_id", variant.SourceFrameId);
            AppendBoolProperty(builder, ref first, "has_stable", variant.HasStablePose);
            AppendPoseProperties(builder, ref first, "stable_pos", "stable_rot", variant.StablePose, variant.HasStablePose);
            AppendStringProperty(builder, ref first, "anchor_state", variant.AnchorState);
            AppendStringProperty(builder, ref first, "policy_action", variant.PolicyAction);
            AppendStringProperty(builder, ref first, "policy_reason", variant.PolicyReason);
            AppendStringProperty(builder, ref first, "latest_phase", variant.LatestPhase);
            AppendStringProperty(builder, ref first, "latest_failure", variant.LatestFailure);
            if (variant.IsPrimary)
            {
                AppendBoolProperty(builder, ref first, "has_aligned_raw", variant.HasAlignedRawPose);
                AppendPoseProperties(builder, ref first, "aligned_raw_pos", "aligned_raw_rot", variant.AlignedRawPose, variant.HasAlignedRawPose);
                AppendFloatProperty(builder, ref first, "reliability_score", variant.ReliabilityScore);
            }
            builder.Append('}');
        }

        /// <summary>
        /// 写入 position/rotation 两个属性；无位姿时写 null。
        /// </summary>
        private static void AppendPoseProperties(StringBuilder builder, ref bool first, string posName, string rotName, Pose pose, bool hasPose)
        {
            AppendName(builder, ref first, posName);
            if (hasPose)
            {
                AppendVector3(builder, pose.position);
            }
            else
            {
                builder.Append("null");
            }

            AppendName(builder, ref first, rotName);
            if (hasPose)
            {
                AppendQuaternion(builder, pose.rotation);
            }
            else
            {
                builder.Append("null");
            }
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
        /// 写入 long 属性。
        /// </summary>
        private static void AppendLongProperty(StringBuilder builder, ref bool first, string name, long value)
        {
            AppendName(builder, ref first, name);
            builder.Append(value.ToString(CultureInfo.InvariantCulture));
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
        /// 写入 float 属性。
        /// </summary>
        private static void AppendFloatProperty(StringBuilder builder, ref bool first, string name, float value)
        {
            AppendName(builder, ref first, name);
            AppendFloat(builder, value);
        }

        /// <summary>
        /// 写入 UTC 与本地可读时间字符串。
        /// </summary>
        private static void AppendReadableTimeProperties(StringBuilder builder, ref bool first, string prefix, double unixMs)
        {
            AppendStringProperty(builder, ref first, $"{prefix}_utc", FormatUtc(unixMs));
            AppendStringProperty(builder, ref first, $"{prefix}_local", FormatLocal(unixMs));
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
        /// 写入 Vector3 数组。
        /// </summary>
        private static void AppendVector3(StringBuilder builder, Vector3 value)
        {
            builder.Append('[');
            AppendFloat(builder, value.x);
            builder.Append(',');
            AppendFloat(builder, value.y);
            builder.Append(',');
            AppendFloat(builder, value.z);
            builder.Append(']');
        }

        /// <summary>
        /// 写入 Quaternion 数组，顺序为 xyzw。
        /// </summary>
        private static void AppendQuaternion(StringBuilder builder, Quaternion value)
        {
            builder.Append('[');
            AppendFloat(builder, value.x);
            builder.Append(',');
            AppendFloat(builder, value.y);
            builder.Append(',');
            AppendFloat(builder, value.z);
            builder.Append(',');
            AppendFloat(builder, value.w);
            builder.Append(']');
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
        /// 按 invariant round-trip 格式写入 float。
        /// </summary>
        private static void AppendFloat(StringBuilder builder, float value)
        {
            if (float.IsNaN(value) || float.IsInfinity(value))
            {
                builder.Append("null");
                return;
            }

            builder.Append(value.ToString("R", CultureInfo.InvariantCulture));
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

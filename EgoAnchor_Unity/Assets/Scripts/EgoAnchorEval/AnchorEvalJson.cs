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

        /// <summary>本帧该变体是否产出了可用的 anchor 输出 pose。</summary>
        public readonly bool HasOutputPose;

        /// <summary>当前 anchor 输出 pose；无位姿时按 identity 写出 null。</summary>
        public readonly Pose OutputPose;

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

        /// <summary>当前运动状态（Unknown/Static/Moving）；非 policy 变体为空字符串。</summary>
        public readonly string MotionState;

        /// <summary>最近一次渲染输出的前推时长，单位毫秒；非 policy 变体写 null。</summary>
        public readonly double PredictAheadMs;

        /// <summary>output_pos/output_rot 的采样来源，例如 transform 或 none。</summary>
        public readonly string AnchorPoseSource;

        /// <summary>是否拿到了 source frame 的采集时间。</summary>
        public readonly bool HasSourceCaptureTiming;

        /// <summary>source frame 在 Unity 发送侧的单调时间，单位毫秒。</summary>
        public readonly double SourceCaptureMonoMs;

        /// <summary>source frame 对应的 Unity Time.frameCount。</summary>
        public readonly int SourceCaptureUnityFrame;

        /// <summary>是否是主变体；主变体额外写 aligned raw 与 reliability。</summary>
        public readonly bool IsPrimary;

        /// <summary>主变体是否已有 aligned raw pose。</summary>
        public readonly bool HasAlignedRawPose;

        /// <summary>主变体 aligned raw pose。</summary>
        public readonly Pose AlignedRawPose;

        /// <summary>主变体是否已有 arrival-time raw 诊断 pose。</summary>
        public readonly bool HasArrivalTimeRawPose;

        /// <summary>主变体 arrival-time raw 诊断 pose。</summary>
        public readonly Pose ArrivalTimeRawPose;

        /// <summary>主变体 arrival-time raw 诊断时间，单位毫秒。</summary>
        public readonly double ArrivalTimeRawMonoMs;

        /// <summary>主变体 arrival-time raw 诊断对应的 Unity frame。</summary>
        public readonly int ArrivalTimeRawUnityFrame;

        /// <summary>主变体 arrival-time raw 诊断使用的参考相机。</summary>
        public readonly string ArrivalTimeCameraReference;

        /// <summary>主变体最近一次 reliability score。</summary>
        public readonly float ReliabilityScore;

        /// <summary>策略 label，通常等于 pipeline strategy label。</summary>
        public readonly string StrategyLabel;

        /// <summary>gate 名称 (score_jump_gate / null_gate)。</summary>
        public readonly string GateName;

        /// <summary>运动模型名称 (cv / kalman / oneeuro)。</summary>
        public readonly string MotionModelName;

        /// <summary>平滑策略名称 (blend / interp_hermite / raw_passthrough)。</summary>
        public readonly string SmoothingStrategyName;

        /// <summary>本次策略配置的稳定摘要。</summary>
        public readonly string ConfigHash;

        /// <summary>最近一次 output stage 平移残差，单位米。</summary>
        public readonly float LatestResidualMeters;

        /// <summary>最近一次 output stage 旋转残差，单位度。</summary>
        public readonly float LatestResidualDegrees;

        /// <summary>最近一次 pipeline 接受的可靠性分数。</summary>
        public readonly float LatestAcceptedScore;

        /// <summary>最近一次 output stage 是否静止锁定。</summary>
        public readonly bool LatestStaticLocked;

        /// <summary>
        /// 构造变体输出快照。
        /// </summary>
        public RecordedVariantSnapshot(
            string label,
            long sourceFrameId,
            bool hasOutputPose,
            Pose outputPose,
            string anchorState,
            string policyAction,
            string policyReason,
            string latestPhase,
            string latestFailure,
            string anchorPoseSource,
            bool hasSourceCaptureTiming,
            double sourceCaptureMonoMs,
            int sourceCaptureUnityFrame,
            bool isPrimary,
            bool hasAlignedRawPose,
            Pose alignedRawPose,
            bool hasArrivalTimeRawPose,
            Pose arrivalTimeRawPose,
            double arrivalTimeRawMonoMs,
            int arrivalTimeRawUnityFrame,
            string arrivalTimeCameraReference,
            float reliabilityScore,
            string motionState,
            double predictAheadMs,
            string strategyLabel,
            string gateName,
            string motionModelName,
            string smoothingStrategyName,
            string configHash,
            float latestResidualMeters,
            float latestResidualDegrees,
            float latestAcceptedScore,
            bool latestStaticLocked)
        {
            Label = label ?? string.Empty;
            SourceFrameId = sourceFrameId;
            HasOutputPose = hasOutputPose;
            OutputPose = outputPose;
            AnchorState = anchorState ?? string.Empty;
            PolicyAction = policyAction ?? string.Empty;
            PolicyReason = policyReason ?? string.Empty;
            LatestPhase = latestPhase ?? string.Empty;
            LatestFailure = latestFailure ?? string.Empty;
            AnchorPoseSource = anchorPoseSource ?? string.Empty;
            HasSourceCaptureTiming = hasSourceCaptureTiming;
            SourceCaptureMonoMs = sourceCaptureMonoMs;
            SourceCaptureUnityFrame = sourceCaptureUnityFrame;
            IsPrimary = isPrimary;
            HasAlignedRawPose = hasAlignedRawPose;
            AlignedRawPose = alignedRawPose;
            HasArrivalTimeRawPose = hasArrivalTimeRawPose;
            ArrivalTimeRawPose = arrivalTimeRawPose;
            ArrivalTimeRawMonoMs = arrivalTimeRawMonoMs;
            ArrivalTimeRawUnityFrame = arrivalTimeRawUnityFrame;
            ArrivalTimeCameraReference = arrivalTimeCameraReference ?? string.Empty;
            ReliabilityScore = reliabilityScore;
            MotionState = motionState ?? string.Empty;
            PredictAheadMs = predictAheadMs;
            StrategyLabel = strategyLabel ?? string.Empty;
            GateName = gateName ?? string.Empty;
            MotionModelName = motionModelName ?? string.Empty;
            SmoothingStrategyName = smoothingStrategyName ?? string.Empty;
            ConfigHash = configHash ?? string.Empty;
            LatestResidualMeters = latestResidualMeters;
            LatestResidualDegrees = latestResidualDegrees;
            LatestAcceptedScore = latestAcceptedScore;
            LatestStaticLocked = latestStaticLocked;
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
            bool gtPoseValid,
            string gtPoseSource,
            bool cameraValid = true,
            int captureUnityFrame = -1,
            string cameraReference = "")
        {
            var builder = new StringBuilder(512);
            bool first = true;
            builder.Append('{');
            AppendStringProperty(builder, ref first, "event", "unity_capture");
            AppendLongProperty(builder, ref first, "frame_id", frameId);
            AppendDoubleProperty(builder, ref first, "capture_mono_ms", captureMonoMs);
            AppendDoubleProperty(builder, ref first, "capture_unix_ms", captureUnixMs);
            AppendReadableTimeProperties(builder, ref first, "capture", captureUnixMs);
            AppendLongProperty(builder, ref first, "capture_unity_frame", captureUnityFrame);
            AppendPoseProperties(builder, ref first, "head_pos", "head_rot", headPose, hasPose: true);
            AppendBoolProperty(builder, ref first, "cam_valid", cameraValid);
            AppendStringProperty(builder, ref first, "camera_reference", cameraReference);
            AppendPoseProperties(builder, ref first, "cam_pos", "cam_rot", cameraPose, cameraValid);
            AppendPoseProperties(builder, ref first, "gt_pos", "gt_rot", groundTruthPose, gtPoseValid);
            AppendBoolProperty(builder, ref first, "gt_pose_valid", gtPoseValid);
            AppendStringProperty(builder, ref first, "gt_pose_source", gtPoseSource);
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
            bool gtPoseValid,
            string gtPoseSource,
            IReadOnlyList<RecordedVariantSnapshot> variants,
            int renderUnityFrame = -1)
        {
            var builder = new StringBuilder(1024);
            bool first = true;
            builder.Append('{');
            AppendStringProperty(builder, ref first, "event", "unity_output");
            AppendDoubleProperty(builder, ref first, "render_mono_ms", renderMonoMs);
            AppendDoubleProperty(builder, ref first, "render_unix_ms", renderUnixMs);
            AppendReadableTimeProperties(builder, ref first, "render", renderUnixMs);
            AppendLongProperty(builder, ref first, "render_unity_frame", renderUnityFrame);
            AppendLongProperty(builder, ref first, "source_frame_id", sourceFrameId);
            AppendPoseProperties(builder, ref first, "head_pos", "head_rot", headPose, hasPose: true);
            AppendPoseProperties(builder, ref first, "gt_pos", "gt_rot", groundTruthPose, gtPoseValid);
            AppendBoolProperty(builder, ref first, "gt_pose_valid", gtPoseValid);
            AppendStringProperty(builder, ref first, "gt_pose_source", gtPoseSource);
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
            AppendBoolProperty(builder, ref first, "has_output_pose", variant.HasOutputPose);
            AppendPoseProperties(builder, ref first, "output_pos", "output_rot", variant.OutputPose, variant.HasOutputPose);
            AppendStringProperty(builder, ref first, "anchor_pose_source", variant.AnchorPoseSource);
            AppendBoolProperty(builder, ref first, "has_source_capture_timing", variant.HasSourceCaptureTiming);
            AppendDoubleProperty(
                builder,
                ref first,
                "source_capture_mono_ms",
                variant.HasSourceCaptureTiming ? variant.SourceCaptureMonoMs : double.NaN);
            AppendLongProperty(
                builder,
                ref first,
                "source_capture_unity_frame",
                variant.HasSourceCaptureTiming ? variant.SourceCaptureUnityFrame : -1);
            AppendStringProperty(builder, ref first, "anchor_state", variant.AnchorState);
            AppendStringProperty(builder, ref first, "policy_action", variant.PolicyAction);
            AppendStringProperty(builder, ref first, "policy_reason", variant.PolicyReason);
            AppendStringProperty(builder, ref first, "latest_phase", variant.LatestPhase);
            AppendStringProperty(builder, ref first, "latest_failure", variant.LatestFailure);
            AppendStringProperty(builder, ref first, "motion_state", variant.MotionState);
            AppendDoubleProperty(builder, ref first, "predict_ahead_ms", variant.PredictAheadMs);
            AppendStringProperty(builder, ref first, "strategy_label", variant.StrategyLabel);
            AppendStringProperty(builder, ref first, "gate", variant.GateName);
            AppendStringProperty(builder, ref first, "motion_model", variant.MotionModelName);
            AppendStringProperty(builder, ref first, "smoothing_strategy", variant.SmoothingStrategyName);
            AppendStringProperty(builder, ref first, "config_hash", variant.ConfigHash);
            AppendFloatProperty(builder, ref first, "latest_residual_meters", variant.LatestResidualMeters);
            AppendFloatProperty(builder, ref first, "latest_residual_degrees", variant.LatestResidualDegrees);
            AppendFloatProperty(builder, ref first, "latest_accepted_score", variant.LatestAcceptedScore);
            AppendBoolProperty(builder, ref first, "latest_static_locked", variant.LatestStaticLocked);
            if (variant.IsPrimary)
            {
                AppendBoolProperty(builder, ref first, "has_aligned_raw", variant.HasAlignedRawPose);
                AppendPoseProperties(builder, ref first, "aligned_raw_pos", "aligned_raw_rot", variant.AlignedRawPose, variant.HasAlignedRawPose);
                AppendBoolProperty(builder, ref first, "has_arrival_time_raw", variant.HasArrivalTimeRawPose);
                AppendPoseProperties(builder, ref first, "arrival_time_raw_pos", "arrival_time_raw_rot", variant.ArrivalTimeRawPose, variant.HasArrivalTimeRawPose);
                AppendDoubleProperty(builder, ref first, "arrival_time_raw_mono_ms", variant.HasArrivalTimeRawPose ? variant.ArrivalTimeRawMonoMs : double.NaN);
                AppendLongProperty(builder, ref first, "arrival_time_raw_unity_frame", variant.HasArrivalTimeRawPose ? variant.ArrivalTimeRawUnityFrame : -1);
                AppendStringProperty(builder, ref first, "arrival_time_camera_reference", variant.ArrivalTimeCameraReference);
                AppendFloatProperty(builder, ref first, "reliability_score", variant.ReliabilityScore);
            }
            builder.Append('}');
        }

        /// <summary>
        /// 写入 position、rotation 四元数和 0-360 欧拉角三个属性；无位姿时写 null。
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

            AppendName(builder, ref first, EulerNameFromRotName(rotName));
            if (hasPose)
            {
                AppendVector3(builder, ToEuler360(pose.rotation));
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
        /// 根据 `*_rot` 字段名生成对应的 `*_euler_deg` 字段名。
        /// </summary>
        private static string EulerNameFromRotName(string rotName)
        {
            const string suffix = "_rot";
            if (!string.IsNullOrEmpty(rotName) && rotName.EndsWith(suffix, StringComparison.Ordinal))
            {
                return rotName.Substring(0, rotName.Length - suffix.Length) + "_euler_deg";
            }

            return (rotName ?? string.Empty) + "_euler_deg";
        }

        /// <summary>
        /// 把 Unity Quaternion 转为 Inspector 风格欧拉角，并规范到 [0, 360)。
        /// </summary>
        private static Vector3 ToEuler360(Quaternion value)
        {
            double x = value.x;
            double y = value.y;
            double z = value.z;
            double w = value.w;
            double norm = Math.Sqrt(x * x + y * y + z * z + w * w);
            if (norm <= double.Epsilon)
            {
                return Vector3.zero;
            }

            x /= norm;
            y /= norm;
            z /= norm;
            w /= norm;

            double sinX = 2.0 * (w * x + y * z);
            double cosX = 1.0 - 2.0 * (x * x + y * y);
            double eulerX = Math.Atan2(sinX, cosX) * 57.29577951308232;

            double sinY = 2.0 * (w * y - z * x);
            sinY = Math.Max(-1.0, Math.Min(1.0, sinY));
            double eulerY = Math.Asin(sinY) * 57.29577951308232;

            double sinZ = 2.0 * (w * z + x * y);
            double cosZ = 1.0 - 2.0 * (y * y + z * z);
            double eulerZ = Math.Atan2(sinZ, cosZ) * 57.29577951308232;

            return new Vector3(
                NormalizeAngle360((float)eulerX),
                NormalizeAngle360((float)eulerY),
                NormalizeAngle360((float)eulerZ));
        }

        /// <summary>
        /// 把角度规范到 [0, 360)，避免日志中出现负角度。
        /// </summary>
        private static float NormalizeAngle360(float value)
        {
            float normalized = value % 360.0f;
            if (normalized < 0.0f)
            {
                normalized += 360.0f;
            }

            return Math.Abs(normalized - 360.0f) <= 1e-5f ? 0.0f : normalized;
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

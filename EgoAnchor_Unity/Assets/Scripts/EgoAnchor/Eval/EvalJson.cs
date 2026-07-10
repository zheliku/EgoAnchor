using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using UnityEngine;

namespace EgoAnchor.Eval
{
    /// <summary>
    /// 评估 JSONL 单行构建工具；只做字符串拼接，不依赖 JsonUtility。
    /// 输出字段名与 Python eval/io/schemas.py 保持一致，不得擅自更改。
    /// </summary>
    public static class EvalJson
    {
        // ─────────────── 公共构建入口 ───────────────

        /// <summary>
        /// 构建每个 frame_id 采集瞬间的 unity_capture 行。
        /// </summary>
        /// <param name="frameId">协议帧号。</param>
        /// <param name="captureMonoMs">图像时间代理对应的 Unity 单调时钟毫秒。</param>
        /// <param name="captureUnixMs">写入采集行时的 Unix 时钟毫秒。</param>
        /// <param name="captureUnityFrame">图像时间代理对应的 Unity 帧号。</param>
        /// <param name="senderMonoMs">JPEG 编码完成后的 payload-ready 单调时钟毫秒；不代表 ZMQ 实际发包时刻。</param>
        /// <param name="senderUnityFrame">payload-ready 时的 Unity 帧号。</param>
        /// <param name="gtSampleMonoMs">回调中实际读取 GT 的 Unity 单调时钟毫秒。</param>
        /// <param name="imageTimeOffsetFrames">图像时间代理回退的成功采集样本数。</param>
        /// <param name="publishAttemptMonoMs">紧邻 ZMQ TrySend 前的 Unity 单调时钟毫秒。</param>
        /// <param name="publishSucceeded">NetMQ 是否立即接受该 multipart 消息。</param>
        /// <param name="headPose">回调时刻头部 world pose。</param>
        /// <param name="cameraValid">图像时刻参考相机 pose 是否有效。</param>
        /// <param name="cameraPose">图像时刻参考相机 world pose。</param>
        /// <param name="gtValid">GT pose 是否有效。</param>
        /// <param name="gtPose">回调实际采样的 GT world pose。</param>
        /// <param name="cameraReference">参考相机名称。</param>
        /// <returns>可写入 JSONL 的单行 JSON。</returns>
        public static string BuildCaptureLine(
            long frameId,
            double captureMonoMs,
            double captureUnixMs,
            int captureUnityFrame,
            double senderMonoMs,
            int senderUnityFrame,
            double gtSampleMonoMs,
            int imageTimeOffsetFrames,
            double publishAttemptMonoMs,
            bool publishSucceeded,
            Pose headPose,
            bool cameraValid,
            Pose cameraPose,
            bool gtValid,
            Pose gtPose,
            string cameraReference)
        {
            var b = new Builder(512);
            b.Str("event", "unity_capture");
            b.Long("frame_id", frameId);
            b.Dbl("capture_mono_ms", captureMonoMs);
            b.Dbl("capture_unix_ms", captureUnixMs);
            b.TimeStr("capture", captureUnixMs);
            b.Long("capture_unity_frame", captureUnityFrame);
            b.Dbl("sender_mono_ms", senderMonoMs);
            b.Long("sender_unity_frame", senderUnityFrame);
            b.Dbl("gt_sample_mono_ms", gtSampleMonoMs);
            b.Str("image_time_basis", "camera_pose_history_proxy");
            b.Long("image_time_offset_frames", imageTimeOffsetFrames);
            b.Dbl("publish_attempt_mono_ms", publishAttemptMonoMs);
            b.Bool("publish_succeeded", publishSucceeded);
            b.Pose("head_pos", "head_rot", headPose, true);
            b.Bool("cam_valid", cameraValid);
            b.Str("camera_reference", cameraReference ?? string.Empty);
            b.Pose("cam_pos", "cam_rot", cameraPose, cameraValid);
            b.Pose("gt_pos", "gt_rot", gtPose, gtValid);
            b.Bool("gt_pose_valid", gtValid);
            b.Str("gt_pose_source", gtValid ? "transform" : "none");
            return b.Finish();
        }

        /// <summary>
        /// 构建每个渲染 tick 的 unity_output 行。
        /// </summary>
        /// <param name="renderMonoMs">渲染 tick 的 Unity 单调时钟毫秒。</param>
        /// <param name="renderUnixMs">渲染 tick 的 Unix 时钟毫秒。</param>
        /// <param name="renderUnityFrame">渲染 tick 的 Unity 帧号。</param>
        /// <param name="sourceFrameId">主变体当前输出对应的源帧号。</param>
        /// <param name="headPose">渲染时刻的头部 world pose。</param>
        /// <param name="gtValid">渲染时刻参考 pose 是否有效。</param>
        /// <param name="gtPose">渲染时刻的平台参考 world pose。</param>
        /// <param name="gtLinearSpeedMs">平台参考 pose 的线速度，单位 m/s。</param>
        /// <param name="gtAngularSpeedDegS">平台参考 pose 的角速度，单位 deg/s。</param>
        /// <param name="variants">同一渲染 tick 的系统变体快照。</param>
        /// <param name="rq1Metric">可选的 RQ1 场景标签。</param>
        /// <param name="rq1MetricDuration">RQ1 场景标签持续时间，单位秒。</param>
        /// <param name="rq2Condition">可选的 RQ2 运动场景标签。</param>
        /// <param name="rq2TrialId">RQ2 session 内试次编号；空闲时为 -1。</param>
        /// <param name="rq2TargetLinearSpeedMs">RQ2 目标线速度，单位 m/s；不适用时为 NaN。</param>
        /// <param name="rq2TargetAngularSpeedDegS">RQ2 目标角速度，单位 deg/s；不适用时为 NaN。</param>
        /// <returns>可写入 JSONL 的单行 JSON。</returns>
        public static string BuildOutputLine(
            double renderMonoMs,
            double renderUnixMs,
            int renderUnityFrame,
            long sourceFrameId,
            Pose headPose,
            bool gtValid,
            Pose gtPose,
            float gtLinearSpeedMs,
            float gtAngularSpeedDegS,
            IReadOnlyList<EvalVariantSnapshot> variants,
            string rq1Metric = null,
            double rq1MetricDuration = 0.0,
            string rq2Condition = null,
            long rq2TrialId = -1,
            float rq2TargetLinearSpeedMs = float.NaN,
            float rq2TargetAngularSpeedDegS = float.NaN)
        {
            var b = new Builder(1024);
            b.Str("event", "unity_output");
            b.Dbl("render_mono_ms", renderMonoMs);
            b.Dbl("render_unix_ms", renderUnixMs);
            b.TimeStr("render", renderUnixMs);
            b.Long("render_unity_frame", renderUnityFrame);
            b.Long("source_frame_id", sourceFrameId);
            b.Pose("head_pos", "head_rot", headPose, true);
            b.Pose("gt_pos", "gt_rot", gtPose, gtValid);
            b.Bool("gt_pose_valid", gtValid);
            b.Str("gt_pose_source", gtValid ? "transform" : "none");
            b.Flt("gt_linear_speed_m_s", gtLinearSpeedMs);
            b.Flt("gt_angular_speed_deg_s", gtAngularSpeedDegS);
            // RQ1 手动标记字段（可选）
            b.Str("rq1_metric", rq1Metric ?? "none");
            b.Dbl("rq1_metric_duration", rq1MetricDuration);
            // RQ2 试次上下文字段（可选）
            b.Str("rq2_condition", rq2Condition ?? "none");
            b.Long("rq2_trial_id", rq2TrialId);
            b.Flt("rq2_target_linear_speed_m_s", rq2TargetLinearSpeedMs);
            b.Flt("rq2_target_angular_speed_deg_s", rq2TargetAngularSpeedDegS);
            b.Variants(variants);
            return b.Finish();
        }

        /// <summary>
        /// 构建 session_manifest.json 内容。
        /// </summary>
        public static string BuildManifest(
            string sessionId,
            string objectId,
            string unityRunMode,
            string pythonLogFilename,
            IReadOnlyList<string> variantLabels,
            IReadOnlyList<EvalVariantConfig> variantConfigs,
            string notes)
        {
            var sb = new StringBuilder(512);
            sb.Append('{');
            sb.Append($"\"session_id\":{JStr(sessionId)},");
            sb.Append($"\"object_id\":{JStr(objectId)},");
            sb.Append($"\"unity_run_mode\":{JStr(unityRunMode)},");
            sb.Append($"\"python_log_filename\":{JStr(pythonLogFilename)},");
            sb.Append($"\"notes\":{JStr(notes ?? string.Empty)},");

            // variant_labels 数组
            sb.Append("\"variant_labels\":[");
            if (variantLabels != null)
            {
                for (int i = 0; i < variantLabels.Count; i++)
                {
                    if (i > 0) sb.Append(',');
                    sb.Append(JStr(variantLabels[i]));
                }
            }
            sb.Append("],");

            // variant_configs 数组
            sb.Append("\"variant_configs\":[");
            if (variantConfigs != null)
            {
                for (int i = 0; i < variantConfigs.Count; i++)
                {
                    if (i > 0) sb.Append(',');
                    EvalVariantConfig c = variantConfigs[i];
                    sb.Append('{');
                    sb.Append($"\"label\":{JStr(c.Label)},");
                    sb.Append($"\"motion_model\":{JStr(c.MotionModel)},");
                    sb.Append($"\"smoothing_strategy\":{JStr(c.SmoothingStrategy)},");
                    sb.Append($"\"quality_gate\":{JStr(c.QualityGate)},");
                    sb.Append($"\"config_hash\":{JStr(c.ConfigHash)}");
                    sb.Append('}');
                }
            }
            sb.Append("],");

            // condition_spans/event_markers 留空（RQ1 使用自动场景检测）
            sb.Append("\"condition_spans\":[],");
            sb.Append("\"event_markers\":[]");
            sb.Append('}');
            return sb.ToString();
        }

        // ─────────────── 内部工具 ───────────────

        /// <summary>把字符串序列化为带转义的 JSON 字符串字面量。</summary>
        private static string JStr(string value)
        {
            if (string.IsNullOrEmpty(value))
            {
                return "\"\"";
            }
            var sb = new StringBuilder(value.Length + 2);
            sb.Append('"');
            foreach (char c in value)
            {
                switch (c)
                {
                    case '\\': sb.Append("\\\\"); break;
                    case '"':  sb.Append("\\\""); break;
                    case '\n': sb.Append("\\n");  break;
                    case '\r': sb.Append("\\r");  break;
                    case '\t': sb.Append("\\t");  break;
                    default:
                        if (c < ' ')
                            sb.AppendFormat("\\u{0:x4}", (int)c);
                        else
                            sb.Append(c);
                        break;
                }
            }
            sb.Append('"');
            return sb.ToString();
        }

        // ─────────────── 流式 Builder ───────────────

        /// <summary>轻量 JSON object 构建器，避免反复分配中间字符串。</summary>
        private struct Builder
        {
            private readonly StringBuilder _sb;
            private bool _first;

            public Builder(int capacity)
            {
                _sb = new StringBuilder(capacity);
                _sb.Append('{');
                _first = true;
            }

            private void Sep()
            {
                if (!_first) _sb.Append(',');
                _first = false;
            }

            private void Name(string key)
            {
                Sep();
                _sb.Append('"').Append(key).Append("\":");
            }

            public void Str(string key, string value)
            {
                Name(key);
                _sb.Append(JStr(value ?? string.Empty));
            }

            public void Bool(string key, bool value)
            {
                Name(key);
                _sb.Append(value ? "true" : "false");
            }

            public void Long(string key, long value)
            {
                Name(key);
                _sb.Append(value.ToString(CultureInfo.InvariantCulture));
            }

            public void Dbl(string key, double value)
            {
                Name(key);
                if (double.IsNaN(value) || double.IsInfinity(value))
                    _sb.Append("null");
                else
                    _sb.Append(value.ToString("R", CultureInfo.InvariantCulture));
            }

            public void Flt(string key, float value)
            {
                Name(key);
                if (float.IsNaN(value) || float.IsInfinity(value))
                    _sb.Append("null");
                else
                    _sb.Append(value.ToString("R", CultureInfo.InvariantCulture));
            }

            /// <summary>写入 UTC/本地可读时间字段对。</summary>
            public void TimeStr(string prefix, double unixMs)
            {
                long ms = (long)Math.Round(unixMs, MidpointRounding.AwayFromZero);
                var dt = DateTimeOffset.FromUnixTimeMilliseconds(ms);
                Str($"{prefix}_utc", dt.ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss.fff'Z'", CultureInfo.InvariantCulture));
                Str($"{prefix}_local", dt.ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss.fff zzz", CultureInfo.InvariantCulture));
            }

            /// <summary>写入 pos (Vector3) + rot (Quaternion xyzw) 字段对；无 pose 时写 null。</summary>
            public void Pose(string posKey, string rotKey, UnityEngine.Pose pose, bool valid)
            {
                Name(posKey);
                if (valid) Vec3(pose.position); else _sb.Append("null");
                Name(rotKey);
                if (valid) Quat(pose.rotation); else _sb.Append("null");
                // 附加欧拉角（Python 分析工具可选读取）
                string eulerKey = rotKey.EndsWith("_rot", StringComparison.Ordinal)
                    ? rotKey.Substring(0, rotKey.Length - 4) + "_euler_deg"
                    : rotKey + "_euler_deg";
                Name(eulerKey);
                if (valid) Vec3(ToEuler360(pose.rotation)); else _sb.Append("null");
            }

            public void Variants(IReadOnlyList<EvalVariantSnapshot> variants)
            {
                Name("variants");
                _sb.Append('[');
                if (variants != null)
                {
                    for (int i = 0; i < variants.Count; i++)
                    {
                        if (i > 0) _sb.Append(',');
                        AppendVariant(variants[i]);
                    }
                }
                _sb.Append(']');
            }

            private void AppendVariant(EvalVariantSnapshot v)
            {
                // 用独立 Builder 构建 variant object，Finish() 返回完整 {...}
                var vb = new Builder(512);
                vb.Str("label", v.Label);
                vb.Bool("is_primary", v.IsPrimary);
                vb.Long("source_frame_id", v.SourceFrameId);
                vb.Bool("has_output_pose", v.HasRuntimeOutput);
                vb.Pose("output_pos", "output_rot", v.DisplayPose, v.HasRuntimeOutput);
                vb.Bool("has_display_pose", v.HasDisplayPose);
                vb.Pose("display_pos", "display_rot", v.DisplayPose, v.HasDisplayPose);
                vb.Str("anchor_pose_source", v.AnchorPoseSource);
                vb.Bool("has_source_capture_timing", v.HasSourceCaptureTiming);
                vb.Dbl("source_capture_mono_ms", v.HasSourceCaptureTiming ? v.SourceCaptureMonoMs : double.NaN);
                vb.Long("source_capture_unity_frame", v.HasSourceCaptureTiming ? v.SourceCaptureUnityFrame : -1);
                vb.Dbl("observation_age_ms", v.ObservationAgeMs);
                vb.Dbl("policy_output_target_mono_ms", v.PolicyOutputTargetMonoMs);
                vb.Dbl("smoothing_delay_ms", v.SmoothingDelayMs);
                vb.Dbl("unity_pose_handle_mono_ms", v.UnityPoseHandleMonoMs);
                vb.Str("anchor_state", v.AnchorState);
                vb.Str("policy_action", v.PolicyAction);
                vb.Str("policy_reason", v.PolicyReason);
                vb.Str("latest_phase", v.LatestPhase);
                vb.Str("latest_failure", v.LatestFailure);
                vb.Str("motion_state", v.MotionState);
                vb.Dbl("predict_ahead_ms", v.PredictAheadMs);
                vb.Str("strategy_label", v.StrategyLabel);
                vb.Str("quality_gate", v.QualityGate);
                vb.Str("motion_model", v.MotionModel);
                vb.Str("smoothing_strategy", v.SmoothingStrategy);
                vb.Str("config_hash", v.ConfigHash);
                vb.Flt("latest_residual_meters", v.ResidualMeters);
                vb.Flt("latest_residual_degrees", v.ResidualDegrees);
                vb.Flt("latest_accepted_score", v.AcceptedScore);
                vb.Bool("latest_static_locked", v.StaticLocked);
                if (v.IsPrimary)
                {
                    vb.Bool("has_aligned_raw", v.HasAlignedRaw);
                    vb.Pose("aligned_raw_pos", "aligned_raw_rot", v.AlignedRawPose, v.HasAlignedRaw);
                    vb.Bool("has_arrival_time_raw", v.HasArrivalTimeRaw);
                    vb.Pose("arrival_time_raw_pos", "arrival_time_raw_rot", v.ArrivalTimeRawPose, v.HasArrivalTimeRaw);
                    vb.Dbl("arrival_time_raw_mono_ms", v.HasArrivalTimeRaw ? v.ArrivalTimeRawMonoMs : double.NaN);
                    vb.Long("arrival_time_raw_unity_frame", v.HasArrivalTimeRaw ? v.ArrivalTimeRawUnityFrame : -1);
                    vb.Str("arrival_time_camera_reference", v.ArrivalTimeCameraReference);
                    vb.Flt("reliability_score", v.ReliabilityScore);
                }
                _sb.Append(vb.Finish()); // 产出完整 {...}
            }

            public string Finish()
            {
                _sb.Append('}');
                return _sb.ToString();
            }

            // ── 内部几何帮助 ──

            private void Vec3(Vector3 v)
            {
                _sb.Append('[');
                _sb.Append(v.x.ToString("R", CultureInfo.InvariantCulture)); _sb.Append(',');
                _sb.Append(v.y.ToString("R", CultureInfo.InvariantCulture)); _sb.Append(',');
                _sb.Append(v.z.ToString("R", CultureInfo.InvariantCulture));
                _sb.Append(']');
            }

            private void Quat(Quaternion q)
            {
                _sb.Append('[');
                _sb.Append(q.x.ToString("R", CultureInfo.InvariantCulture)); _sb.Append(',');
                _sb.Append(q.y.ToString("R", CultureInfo.InvariantCulture)); _sb.Append(',');
                _sb.Append(q.z.ToString("R", CultureInfo.InvariantCulture)); _sb.Append(',');
                _sb.Append(q.w.ToString("R", CultureInfo.InvariantCulture));
                _sb.Append(']');
            }

            private static Vector3 ToEuler360(Quaternion q)
            {
                double x = q.x, y = q.y, z = q.z, w = q.w;
                double n = Math.Sqrt(x*x + y*y + z*z + w*w);
                if (n <= double.Epsilon) return Vector3.zero;
                x /= n; y /= n; z /= n; w /= n;
                double ex = Math.Atan2(2*(w*x + y*z), 1 - 2*(x*x + y*y)) * 57.29577951308232;
                double ey = Math.Asin(Math.Max(-1, Math.Min(1, 2*(w*y - z*x)))) * 57.29577951308232;
                double ez = Math.Atan2(2*(w*z + x*y), 1 - 2*(y*y + z*z)) * 57.29577951308232;
                return new Vector3(Norm360((float)ex), Norm360((float)ey), Norm360((float)ez));
            }

            private static float Norm360(float v)
            {
                float r = v % 360f;
                if (r < 0f) r += 360f;
                return Math.Abs(r - 360f) <= 1e-5f ? 0f : r;
            }
        }
    }

    // ─────────────── 数据结构 ───────────────

    /// <summary>一次渲染 tick 中某个 runtime 变体的快照数据。</summary>
    public readonly struct EvalVariantSnapshot
    {
        public readonly string Label;
        public readonly bool IsPrimary;
        public readonly long SourceFrameId;
        /// <summary>policy runtime 本帧是否给出有效输出。</summary>
        public readonly bool HasRuntimeOutput;
        /// <summary>用户当前是否看到已应用或 hold-last 的 anchor pose。</summary>
        public readonly bool HasDisplayPose;
        /// <summary>实际显示 Transform 的 world pose。</summary>
        public readonly Pose DisplayPose;
        /// <summary>兼容现有 C# 调用的 runtime 输出有效性别名。</summary>
        public bool HasOutputPose => HasRuntimeOutput;
        /// <summary>兼容现有 C# 调用的显示 pose 别名。</summary>
        public Pose OutputPose => DisplayPose;
        public readonly string AnchorPoseSource;
        public readonly bool HasSourceCaptureTiming;
        public readonly double SourceCaptureMonoMs;
        public readonly int SourceCaptureUnityFrame;
        /// <summary>当前渲染时刻距最近图像观测语义时刻的年龄，单位毫秒。</summary>
        public readonly double ObservationAgeMs;
        /// <summary>policy 输出 pose 对应的 Unity 单调时钟语义时刻，单位毫秒。</summary>
        public readonly double PolicyOutputTargetMonoMs;
        /// <summary>当前渲染时刻相对 policy 输出语义时刻的实际平滑延迟，单位毫秒。</summary>
        public readonly double SmoothingDelayMs;
        /// <summary>与 SourceFrameId 对应的 aligned pose 在 Unity 中处理完成的单调时钟毫秒。</summary>
        public readonly double UnityPoseHandleMonoMs;
        public readonly string AnchorState;
        public readonly string PolicyAction;
        public readonly string PolicyReason;
        public readonly string LatestPhase;
        public readonly string LatestFailure;
        public readonly string MotionState;
        public readonly double PredictAheadMs;
        public readonly string StrategyLabel;
        public readonly string QualityGate;
        public readonly string MotionModel;
        public readonly string SmoothingStrategy;
        public readonly string ConfigHash;
        public readonly float ResidualMeters;
        public readonly float ResidualDegrees;
        public readonly float AcceptedScore;
        public readonly bool StaticLocked;
        // 仅主变体
        public readonly bool HasAlignedRaw;
        public readonly Pose AlignedRawPose;
        public readonly bool HasArrivalTimeRaw;
        public readonly Pose ArrivalTimeRawPose;
        public readonly double ArrivalTimeRawMonoMs;
        public readonly int ArrivalTimeRawUnityFrame;
        public readonly string ArrivalTimeCameraReference;
        public readonly float ReliabilityScore;

        public EvalVariantSnapshot(
            string label, bool isPrimary, long sourceFrameId,
            bool hasRuntimeOutput, bool hasDisplayPose, Pose displayPose, string anchorPoseSource,
            bool hasSourceCaptureTiming, double sourceCaptureMonoMs, int sourceCaptureUnityFrame,
            double observationAgeMs, double policyOutputTargetMonoMs, double smoothingDelayMs,
            double unityPoseHandleMonoMs,
            string anchorState, string policyAction, string policyReason,
            string latestPhase, string latestFailure, string motionState, double predictAheadMs,
            string strategyLabel, string qualityGate, string motionModel, string smoothingStrategy,
            string configHash, float residualMeters, float residualDegrees, float acceptedScore, bool staticLocked,
            bool hasAlignedRaw, Pose alignedRawPose,
            bool hasArrivalTimeRaw, Pose arrivalTimeRawPose,
            double arrivalTimeRawMonoMs, int arrivalTimeRawUnityFrame, string arrivalTimeCameraReference,
            float reliabilityScore)
        {
            Label = label ?? string.Empty;
            IsPrimary = isPrimary;
            SourceFrameId = sourceFrameId;
            HasRuntimeOutput = hasRuntimeOutput;
            HasDisplayPose = hasDisplayPose;
            DisplayPose = displayPose;
            AnchorPoseSource = anchorPoseSource ?? string.Empty;
            HasSourceCaptureTiming = hasSourceCaptureTiming;
            SourceCaptureMonoMs = sourceCaptureMonoMs;
            SourceCaptureUnityFrame = sourceCaptureUnityFrame;
            ObservationAgeMs = observationAgeMs;
            PolicyOutputTargetMonoMs = policyOutputTargetMonoMs;
            SmoothingDelayMs = smoothingDelayMs;
            UnityPoseHandleMonoMs = unityPoseHandleMonoMs;
            AnchorState = anchorState ?? string.Empty;
            PolicyAction = policyAction ?? string.Empty;
            PolicyReason = policyReason ?? string.Empty;
            LatestPhase = latestPhase ?? string.Empty;
            LatestFailure = latestFailure ?? string.Empty;
            MotionState = motionState ?? string.Empty;
            PredictAheadMs = predictAheadMs;
            StrategyLabel = strategyLabel ?? string.Empty;
            QualityGate = qualityGate ?? string.Empty;
            MotionModel = motionModel ?? string.Empty;
            SmoothingStrategy = smoothingStrategy ?? string.Empty;
            ConfigHash = configHash ?? string.Empty;
            ResidualMeters = residualMeters;
            ResidualDegrees = residualDegrees;
            AcceptedScore = acceptedScore;
            StaticLocked = staticLocked;
            HasAlignedRaw = hasAlignedRaw;
            AlignedRawPose = alignedRawPose;
            HasArrivalTimeRaw = hasArrivalTimeRaw;
            ArrivalTimeRawPose = arrivalTimeRawPose;
            ArrivalTimeRawMonoMs = arrivalTimeRawMonoMs;
            ArrivalTimeRawUnityFrame = arrivalTimeRawUnityFrame;
            ArrivalTimeCameraReference = arrivalTimeCameraReference ?? string.Empty;
            ReliabilityScore = reliabilityScore;
        }
    }

    /// <summary>变体配置摘要，写入 manifest。</summary>
    public readonly struct EvalVariantConfig
    {
        public readonly string Label;
        public readonly string MotionModel;
        public readonly string SmoothingStrategy;
        public readonly string QualityGate;
        public readonly string ConfigHash;

        public EvalVariantConfig(string label, string motionModel, string smoothingStrategy, string qualityGate, string configHash)
        {
            Label = label ?? string.Empty;
            MotionModel = motionModel ?? string.Empty;
            SmoothingStrategy = smoothingStrategy ?? string.Empty;
            QualityGate = qualityGate ?? string.Empty;
            ConfigHash = configHash ?? string.Empty;
        }
    }
}

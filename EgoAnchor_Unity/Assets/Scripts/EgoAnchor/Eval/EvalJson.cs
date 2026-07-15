using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using EgoAnchor.Eval.Experiment;
using UnityEngine;

namespace EgoAnchor.Eval
{
    /// <summary>一次 schema-v2 session 的冻结 manifest 元数据。</summary>
    public readonly struct EvalManifestMetadata
    {
        /// <summary>跨端共享 session 标识。</summary>
        public readonly string SessionId;

        /// <summary>追踪对象标识。</summary>
        public readonly string ObjectId;

        /// <summary>运行类型：smoke、calibration、formal 或 debug。</summary>
        public readonly string RunKind;

        /// <summary>操作员匿名标识。</summary>
        public readonly string OperatorId;

        /// <summary>session 开始时的 Unix 毫秒时间。</summary>
        public readonly double CreatedUnixMs;

        /// <summary>Unity 执行模式。</summary>
        public readonly string UnityRunMode;

        /// <summary>Python 主机标识；跨机器 fragment 合并前可为空。</summary>
        public readonly string PythonHost;

        /// <summary>Unity 版本。</summary>
        public readonly string UnityVersion;

        /// <summary>Python 版本；跨机器 fragment 合并前可为空。</summary>
        public readonly string PythonVersion;

        /// <summary>采集代码的 Git commit。</summary>
        public readonly string GitCommit;

        /// <summary>协议版本。</summary>
        public readonly string ProtocolVersion;

        /// <summary>正式参数冻结集合标识。</summary>
        public readonly string FrozenParameterSetId;

        /// <summary>目标三维模型标识。</summary>
        public readonly string ObjectModelId;

        /// <summary>采集备注。</summary>
        public readonly string Notes;

        /// <summary>构造冻结 manifest 元数据。</summary>
        public EvalManifestMetadata(
            string sessionId,
            string objectId,
            string runKind,
            string operatorId,
            double createdUnixMs,
            string unityRunMode,
            string pythonHost,
            string unityVersion,
            string pythonVersion,
            string gitCommit,
            string protocolVersion,
            string frozenParameterSetId,
            string objectModelId,
            string notes)
        {
            SessionId = sessionId ?? string.Empty;
            ObjectId = objectId ?? string.Empty;
            RunKind = runKind ?? string.Empty;
            OperatorId = operatorId ?? string.Empty;
            CreatedUnixMs = createdUnixMs;
            UnityRunMode = unityRunMode ?? string.Empty;
            PythonHost = pythonHost ?? string.Empty;
            UnityVersion = unityVersion ?? string.Empty;
            PythonVersion = pythonVersion ?? string.Empty;
            GitCommit = gitCommit ?? string.Empty;
            ProtocolVersion = protocolVersion ?? string.Empty;
            FrozenParameterSetId = frozenParameterSetId ?? string.Empty;
            ObjectModelId = objectModelId ?? string.Empty;
            Notes = notes ?? string.Empty;
        }
    }

    /// <summary>
    /// 评估 JSONL 单行构建工具；只做字符串拼接，不依赖 JsonUtility。
    /// 输出字段名与 Python schema-v2 契约保持一致，不得擅自更改。
    /// </summary>
    public static class EvalJson
    {
        // ─────────────── 公共构建入口 ───────────────

        /// <summary>
        /// 构建每个 frame_id 采集瞬间的 unity_reference 行。
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
        /// <param name="gtSample">回调实际采样的参考 world pose 及其新鲜度诊断。</param>
        /// <param name="cameraReference">参考相机名称。</param>
        /// <returns>可写入 JSONL 的单行 JSON。</returns>
        public static string BuildReferenceLine(
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
            EvalReferencePose gtSample,
            string cameraReference,
            string sessionId = "")
        {
            var b = new Builder(512);
            b.Long("schema_version", 2);
            b.Str("event", "unity_reference");
            b.Str("session_id", sessionId);
            b.Long("frame_id", frameId);
            b.Dbl("capture_mono_ms", captureMonoMs);
            b.Dbl("capture_unix_ms", captureUnixMs);
            b.TimeStr("capture", captureUnixMs);
            b.Long("capture_unity_frame", captureUnityFrame);
            b.Dbl("sender_mono_ms", senderMonoMs);
            b.Long("sender_unity_frame", senderUnityFrame);
            b.Dbl("reference_sample_mono_ms", gtSampleMonoMs);
            b.Str("image_time_basis", "camera_pose_history_proxy");
            b.Long("image_time_offset_frames", imageTimeOffsetFrames);
            b.Dbl("publish_attempt_mono_ms", publishAttemptMonoMs);
            b.Bool("publish_succeeded", publishSucceeded);
            b.Pose("head_pos", "head_rot", headPose, true);
            b.Bool("cam_valid", cameraValid);
            b.Str("camera_reference", cameraReference ?? string.Empty);
            b.Pose("cam_pos", "cam_rot", cameraPose, cameraValid);
            b.ReferencePose(gtSample);
            return b.Finish();
        }


        /// <summary>构建一条 candidate × variant 的 unity_admission 长表行。</summary>
        public static string BuildAdmissionLine(EvalAdmissionSnapshot snapshot)
        {
            var b = new Builder(1024);
            b.Long("schema_version", 2);
            b.Str("event", "unity_admission");
            b.Str("session_id", snapshot.SessionId);
            b.Str("candidate_id", snapshot.CandidateId);
            b.Long("frame_id", snapshot.FrameId);
            b.Str("variant_id", snapshot.VariantId);
            b.Str("variant_label", snapshot.VariantLabel);
            b.Dbl("unity_pose_handle_mono_ms", snapshot.PoseHandleMonoMs);
            b.Long("unity_frame", snapshot.UnityFrame);
            b.Str("world_alignment_mode", snapshot.AlignmentMode.ToString());
            b.Bool("uses_capture_time_alignment", snapshot.UsesCaptureTimeAlignment);
            b.Dbl("source_capture_mono_ms", snapshot.SourceCaptureMonoMs);
            b.Long("source_capture_unity_frame", snapshot.SourceCaptureUnityFrame);
            b.Bool("has_aligned_raw", snapshot.HasAlignedRaw);
            b.Pose("aligned_raw_pos", "aligned_raw_rot", snapshot.AlignedRawPose, snapshot.HasAlignedRaw);
            b.Bool("has_arrival_time_raw", snapshot.HasArrivalTimeRaw);
            b.Pose("arrival_time_raw_pos", "arrival_time_raw_rot", snapshot.ArrivalTimeRawPose, snapshot.HasArrivalTimeRaw);
            b.Dbl("arrival_time_raw_mono_ms", snapshot.ArrivalTimeRawMonoMs);
            b.Bool("uses_vcd_admission", snapshot.UsesVcdAdmission);
            b.Flt("vcd_score", snapshot.VcdScore);
            b.Str("quality_gate", snapshot.QualityGate);
            b.Str("admission_decision", snapshot.AdmissionDecision);
            b.Str("policy_action", snapshot.PolicyAction);
            b.Str("policy_reason", snapshot.PolicyReason);
            b.Str("anchor_state", snapshot.AnchorState);
            b.Str("motion_model", snapshot.MotionModel);
            b.Str("smoothing_strategy", snapshot.SmoothingStrategy);
            b.Bool("uses_temporal_synthesis", snapshot.UsesTemporalSynthesis);
            b.Bool("uses_static_lock", snapshot.UsesStaticLock);
            b.Str("config_hash", snapshot.ConfigHash);
            b.Str("experiment_id", snapshot.ExperimentId);
            b.Str("scenario_id", snapshot.ScenarioId);
            b.Str("trial_id", snapshot.TrialId);
            b.Str("event_id", snapshot.EventId);
            b.Str("condition_id", snapshot.ConditionId);
            return b.Finish();
        }

        /// <summary>构建一条 session/runtime 边界事件行。</summary>
        public static string BuildEventLine(
            string sessionId,
            string eventType,
            string source,
            string message,
            double monoMs,
            int unityFrame,
            string experimentId = "",
            string scenarioId = "",
            string trialId = "",
            string eventId = "",
            string conditionId = "",
            string eventRole = "",
            string severity = "info",
            string variantId = "")
        {
            var b = new Builder(256);
            b.Long("schema_version", 2);
            b.Str("event", eventType);
            b.Str("event_type", eventType);
            b.Str("session_id", sessionId);
            b.Str("source", source);
            b.Dbl("created_unix_ms", DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
            b.Dbl("mono_ms", monoMs);
            b.Long("unity_frame", unityFrame);
            b.Str("severity", severity);
            b.Str("experiment_id", experimentId);
            b.Str("scenario_id", scenarioId);
            b.Str("trial_id", trialId);
            b.Str("event_id", eventId);
            b.Str("variant_id", variantId);
            b.Str("message", message);
            b.StringPairObject(
                "payload",
                "condition_id", conditionId,
                "event_role", eventRole);
            return b.Finish();
        }

        /// <summary>构建一条单变体 unity_render 长表行，不嵌套 variants 数组。</summary>
        public static string BuildRenderLine(
            double renderMonoMs,
            double renderUnixMs,
            int renderUnityFrame,
            Pose headPose,
            EvalReferencePose referencePose,
            float referenceLinearSpeedMs,
            float referenceAngularSpeedDegS,
            EvalVariantSnapshot variant,
            string sessionId = "",
            string experimentId = "",
            string scenarioId = "",
            string trialId = "",
            string eventId = "",
            string conditionId = "")
        {
            var b = new Builder(1024);
            b.Long("schema_version", 2);
            b.Str("event", "unity_render");
            b.Str("session_id", sessionId);
            b.Long("render_tick_id", renderUnityFrame);
            b.Dbl("render_mono_ms", renderMonoMs);
            b.Dbl("render_unix_ms", renderUnixMs);
            b.TimeStr("render", renderUnixMs);
            b.Long("render_unity_frame", renderUnityFrame);
            b.Str("variant_id", variant.Label);
            b.Str("variant_label", variant.Label);
            b.Long("source_frame_id", variant.SourceFrameId);
            b.Pose("head_pos", "head_rot", headPose, true);
            b.ReferencePose(referencePose);
            b.Flt("reference_linear_speed_m_s", referenceLinearSpeedMs);
            b.Flt("reference_angular_speed_deg_s", referenceAngularSpeedDegS);
            b.Str("experiment_id", experimentId);
            b.Str("scenario_id", scenarioId);
            b.Str("trial_id", trialId);
            b.Str("event_id", eventId);
            b.Str("condition_id", conditionId);
            AppendVariantFields(ref b, variant);
            return b.Finish();
        }

        private static void AppendVariantFields(ref Builder b, EvalVariantSnapshot v)
        {
            b.Bool("has_output_pose", v.HasRuntimeOutput);
            b.Pose("output_pos", "output_rot", v.RuntimeOutputPose, v.HasRuntimeOutput);
            b.Bool("has_display_pose", v.HasDisplayPose);
            b.Pose("display_pos", "display_rot", v.DisplayPose, v.HasDisplayPose);
            b.Str("anchor_pose_source", v.AnchorPoseSource);
            b.Bool("has_source_capture_timing", v.HasSourceCaptureTiming);
            b.Dbl("source_capture_mono_ms", v.HasSourceCaptureTiming ? v.SourceCaptureMonoMs : double.NaN);
            b.Long("source_capture_unity_frame", v.HasSourceCaptureTiming ? v.SourceCaptureUnityFrame : -1);
            b.Dbl("observation_age_ms", v.ObservationAgeMs);
            b.Dbl("policy_output_target_mono_ms", v.PolicyOutputTargetMonoMs);
            b.Dbl("smoothing_delay_ms", v.SmoothingDelayMs);
            b.Dbl("unity_pose_handle_mono_ms", v.UnityPoseHandleMonoMs);
            b.Str("anchor_state", v.AnchorState);
            b.Str("policy_action", v.PolicyAction);
            b.Str("policy_reason", v.PolicyReason);
            b.Str("latest_phase", v.LatestPhase);
            b.Str("latest_failure", v.LatestFailure);
            b.Str("motion_state", v.MotionState);
            b.Dbl("predict_ahead_ms", v.PredictAheadMs);
            b.Str("strategy_label", v.StrategyLabel);
            b.Str("quality_gate", v.QualityGate);
            b.Str("motion_model", v.MotionModel);
            b.Str("smoothing_strategy", v.SmoothingStrategy);
            b.Str("config_hash", v.ConfigHash);
            b.Flt("latest_residual_meters", v.ResidualMeters);
            b.Flt("latest_residual_degrees", v.ResidualDegrees);
            b.Flt("latest_accepted_score", v.AcceptedScore);
            b.Bool("latest_static_locked", v.StaticLocked);
        }

        /// <summary>
        /// 构建 schema-v2 manifest.json 内容。
        /// </summary>
        public static string BuildManifest(
            EvalManifestMetadata metadata,
            IReadOnlyList<string> variantLabels,
            IReadOnlyList<EvalVariantConfig> variantConfigs,
            EvalLogStats referenceStats,
            EvalLogStats admissionStats,
            EvalLogStats renderStats,
            EvalLogStats eventsStats)
        {
            string configHash = BuildAggregateConfigHash(variantConfigs);
            string frozenParameterSetId = string.IsNullOrWhiteSpace(metadata.FrozenParameterSetId)
                ? configHash
                : metadata.FrozenParameterSetId;
            var sb = new StringBuilder(512);
            sb.Append('{');
            sb.Append("\"schema_version\":2,");
            sb.Append($"\"session_id\":{JStr(metadata.SessionId)},");
            sb.Append($"\"object_id\":{JStr(metadata.ObjectId)},");
            sb.Append($"\"run_kind\":{JStr(metadata.RunKind)},");
            AppendExperimentIds(sb);
            sb.Append($"\"operator_id\":{JStr(metadata.OperatorId)},");
            sb.Append("\"created_unix_ms\":").Append(metadata.CreatedUnixMs.ToString("R", CultureInfo.InvariantCulture)).Append(',');
            sb.Append($"\"unity_run_mode\":{JStr(metadata.UnityRunMode)},");
            sb.Append($"\"python_host\":{JStr(metadata.PythonHost)},");
            sb.Append($"\"unity_version\":{JStr(metadata.UnityVersion)},");
            sb.Append($"\"python_version\":{JStr(metadata.PythonVersion)},");
            sb.Append($"\"egoanchor_git_commit\":{JStr(metadata.GitCommit)},");
            sb.Append($"\"protocol_version\":{JStr(metadata.ProtocolVersion)},");
            sb.Append($"\"config_hash\":{JStr(configHash)},");
            sb.Append($"\"frozen_parameter_set_id\":{JStr(frozenParameterSetId)},");
            sb.Append($"\"object_model_id\":{JStr(metadata.ObjectModelId)},");
            sb.Append("\"log_files\":{");
            sb.Append($"\"python_candidates\":{JStr(EvalV2Manifest.PythonCandidatesFileName)},");
            sb.Append($"\"unity_reference\":{JStr(EvalV2Manifest.UnityReferenceFileName)},");
            sb.Append($"\"unity_admission\":{JStr(EvalV2Manifest.UnityAdmissionFileName)},");
            sb.Append($"\"unity_render\":{JStr(EvalV2Manifest.UnityRenderFileName)},");
            sb.Append($"\"events\":{JStr(EvalV2Manifest.EventsFileName)}}},");
            sb.Append($"\"notes\":{JStr(metadata.Notes)},");

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

            // 后台日志队列统计按固定文件名分组，供 Python QC 直接读取。
            sb.Append("\"log_writer_stats\":{");
            AppendPendingPythonStats(sb, EvalV2Manifest.PythonCandidatesFileName, false);
            AppendLogStats(sb, EvalV2Manifest.UnityReferenceFileName, referenceStats, true);
            AppendLogStats(sb, EvalV2Manifest.UnityAdmissionFileName, admissionStats, true);
            AppendLogStats(sb, EvalV2Manifest.UnityRenderFileName, renderStats, true);
            AppendPendingMergedEventStats(sb, EvalV2Manifest.EventsFileName, eventsStats, true);
            sb.Append("},");

            sb.Append("\"variant_definitions\":[");
            if (variantConfigs != null)
            {
                for (int i = 0; i < variantConfigs.Count; i++)
                {
                    if (i > 0) sb.Append(',');
                    EvalVariantConfig c = variantConfigs[i];
                    sb.Append('{');
                    sb.Append($"\"variant_id\":{JStr(c.Label)},");
                    sb.Append($"\"variant_label\":{JStr(c.Label)},");
                    sb.Append($"\"world_alignment_mode\":{JStr(c.WorldAlignmentMode)},");
                    sb.Append($"\"uses_capture_time_alignment\":{(c.UsesCaptureTimeAlignment ? "true" : "false")},");
                    sb.Append($"\"uses_vcd_admission\":{(c.UsesVcdAdmission ? "true" : "false")},");
                    sb.Append($"\"uses_temporal_synthesis\":{(c.UsesTemporalSynthesis ? "true" : "false")},");
                    sb.Append($"\"uses_static_lock\":{(c.UsesStaticLock ? "true" : "false")},");
                    sb.Append($"\"uses_low_score_reacquire\":{(c.UsesLowScoreReacquire ? "true" : "false")},");
                    sb.Append($"\"uses_server_reacquire\":{(c.UsesServerReacquire ? "true" : "false")},");
                    sb.Append($"\"config_hash\":{JStr(c.ConfigHash)}");
                    sb.Append('}');
                }
            }
            sb.Append("],");
            AppendTrialPlan(sb);
            sb.Append('}');
            return sb.ToString();
        }

        private static void AppendLogStats(StringBuilder sb, string name, EvalLogStats stats, bool prependComma)
        {
            if (prependComma) sb.Append(',');
            sb.Append(JStr(name)).Append(":{");
            sb.Append("\"rows_written\":").Append(stats.RowsWritten.ToString(CultureInfo.InvariantCulture)).Append(',');
            sb.Append("\"dropped_rows\":").Append(stats.DroppedRows.ToString(CultureInfo.InvariantCulture)).Append(',');
            sb.Append("\"peak_queue_depth\":").Append(stats.PeakQueueDepth.ToString(CultureInfo.InvariantCulture)).Append(',');
            sb.Append("\"write_error\":").Append(JStr(stats.Error));
            sb.Append('}');
        }

        /// <summary>Python writer 仍在外部进程中运行时写显式 pending，而不是伪造零丢行。</summary>
        private static void AppendPendingPythonStats(StringBuilder sb, string name, bool prependComma)
        {
            if (prependComma) sb.Append(',');
            sb.Append(JStr(name)).Append(":{");
            sb.Append("\"rows_written\":null,\"dropped_rows\":null,\"log_write_failures\":null,");
            sb.Append("\"status\":\"pending_python_fragment\"}");
        }

        /// <summary>events 需要在离线阶段合并 Python 与 Unity 来源，因此顶层统计保持 pending。</summary>
        private static void AppendPendingMergedEventStats(
            StringBuilder sb,
            string name,
            EvalLogStats unityStats,
            bool prependComma)
        {
            if (prependComma) sb.Append(',');
            sb.Append(JStr(name)).Append(":{");
            sb.Append("\"rows_written\":null,\"dropped_rows\":null,\"log_write_failures\":null,");
            sb.Append("\"status\":\"pending_python_fragment_merge\",\"unity\":{");
            sb.Append("\"rows_written\":").Append(unityStats.RowsWritten.ToString(CultureInfo.InvariantCulture)).Append(',');
            sb.Append("\"dropped_rows\":").Append(unityStats.DroppedRows.ToString(CultureInfo.InvariantCulture)).Append(',');
            sb.Append("\"peak_queue_depth\":").Append(unityStats.PeakQueueDepth.ToString(CultureInfo.InvariantCulture)).Append(',');
            sb.Append("\"write_error\":").Append(JStr(unityStats.Error)).Append("}}");
        }

        /// <summary>写入本轮冻结的实验一/二标识。</summary>
        private static void AppendExperimentIds(StringBuilder sb)
        {
            sb.Append("\"experiment_ids\":[")
                .Append(JStr(ExperimentId.SystemCharacterization)).Append(',')
                .Append(JStr(ExperimentId.DesignAttribution)).Append("],");
        }

        /// <summary>写入正式采集使用的九类实验场景计划。</summary>
        private static void AppendTrialPlan(StringBuilder sb)
        {
            sb.Append("\"trial_plan\":[");
            bool first = true;
            AppendTrialPlanEntries(sb, ExperimentId.SystemCharacterization, ExperimentScenario.SystemScenarios, ref first);
            AppendTrialPlanEntries(sb, ExperimentId.DesignAttribution, ExperimentScenario.AttributionScenarios, ref first);
            sb.Append(']');
        }

        /// <summary>把一个实验的场景数组追加为 manifest trial plan 条目。</summary>
        private static void AppendTrialPlanEntries(
            StringBuilder sb,
            string experimentId,
            IReadOnlyList<string> scenarios,
            ref bool first)
        {
            for (int i = 0; i < scenarios.Count; i++)
            {
                if (!first) sb.Append(',');
                first = false;
                sb.Append("{\"experiment_id\":").Append(JStr(experimentId))
                    .Append(",\"scenario_id\":").Append(JStr(scenarios[i])).Append('}');
            }
        }

        /// <summary>按 manifest 中的变体顺序生成整体配置摘要。</summary>
        private static string BuildAggregateConfigHash(IReadOnlyList<EvalVariantConfig> configs)
        {
            unchecked
            {
                const ulong offset = 14695981039346656037UL;
                const ulong prime = 1099511628211UL;
                ulong hash = offset;
                if (configs != null)
                {
                    for (int i = 0; i < configs.Count; i++)
                    {
                        foreach (byte value in Encoding.UTF8.GetBytes(configs[i].ConfigHash ?? string.Empty))
                        {
                            hash ^= value;
                            hash *= prime;
                        }
                    }
                }
                return hash.ToString("x16", CultureInfo.InvariantCulture);
            }
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

            /// <summary>写入只含两个字符串字段的 JSON object。</summary>
            public void StringPairObject(
                string key,
                string firstName,
                string firstValue,
                string secondName,
                string secondValue)
            {
                Name(key);
                _sb.Append('{').Append(JStr(firstName)).Append(':')
                    .Append(JStr(firstValue ?? string.Empty)).Append(',')
                    .Append(JStr(secondName)).Append(':')
                    .Append(JStr(secondValue ?? string.Empty)).Append('}');
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

            /// <summary>写入平台参考位姿及其真实追踪、keep-alive 和样本年龄诊断。</summary>
            public void ReferencePose(EvalReferencePose sample)
            {
                Pose("reference_pos", "reference_rot", sample.Pose, sample.Valid);
                Bool("reference_pose_valid", sample.Valid);
                Str("reference_pose_source", sample.Valid ? "transform" : "none");
                Bool("reference_pose_fresh", sample.Fresh);
                Bool("reference_pose_keep_alive", sample.KeepAlive);
                Dbl("reference_pose_fresh_age_ms", sample.FreshAgeMs);
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
        /// <summary>policy runtime 本帧给出的 world pose。</summary>
        public readonly Pose RuntimeOutputPose;
        /// <summary>用户当前是否看到已应用或 hold-last 的 anchor pose。</summary>
        public readonly bool HasDisplayPose;
        /// <summary>实际显示 Transform 的 world pose。</summary>
        public readonly Pose DisplayPose;
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
            bool hasRuntimeOutput, Pose runtimeOutputPose,
            bool hasDisplayPose, Pose displayPose, string anchorPoseSource,
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
            RuntimeOutputPose = runtimeOutputPose;
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
        /// <summary>变体稳定标签。</summary>
        public readonly string Label;

        /// <summary>运动模型名称。</summary>
        public readonly string MotionModel;

        /// <summary>平滑策略名称。</summary>
        public readonly string SmoothingStrategy;

        /// <summary>观测接纳门控模式。</summary>
        public readonly string QualityGate;

        /// <summary>该变体全部生效组件的配置摘要。</summary>
        public readonly string ConfigHash;

        /// <summary>世界系复合使用的时刻模式。</summary>
        public readonly string WorldAlignmentMode;

        /// <summary>是否使用采集时刻世界对齐。</summary>
        public readonly bool UsesCaptureTimeAlignment;

        /// <summary>是否启用 VCD 观测接纳。</summary>
        public readonly bool UsesVcdAdmission;

        /// <summary>是否启用连续时序合成。</summary>
        public readonly bool UsesTemporalSynthesis;

        /// <summary>是否启用显式静止锚定。</summary>
        public readonly bool UsesStaticLock;

        /// <summary>是否允许低分触发本地重获取。</summary>
        public readonly bool UsesLowScoreReacquire;

        /// <summary>是否允许向共享 hub 请求服务器重获取。</summary>
        public readonly bool UsesServerReacquire;

        /// <summary>构造不可变的变体配置摘要。</summary>
        public EvalVariantConfig(
            string label,
            string motionModel,
            string smoothingStrategy,
            string qualityGate,
            string configHash,
            string worldAlignmentMode = "",
            bool usesCaptureTimeAlignment = false,
            bool usesVcdAdmission = false,
            bool usesTemporalSynthesis = false,
            bool usesStaticLock = false,
            bool usesLowScoreReacquire = false,
            bool usesServerReacquire = false)
        {
            Label = label ?? string.Empty;
            MotionModel = motionModel ?? string.Empty;
            SmoothingStrategy = smoothingStrategy ?? string.Empty;
            QualityGate = qualityGate ?? string.Empty;
            ConfigHash = configHash ?? string.Empty;
            WorldAlignmentMode = worldAlignmentMode ?? string.Empty;
            UsesCaptureTimeAlignment = usesCaptureTimeAlignment;
            UsesVcdAdmission = usesVcdAdmission;
            UsesTemporalSynthesis = usesTemporalSynthesis;
            UsesStaticLock = usesStaticLock;
            UsesLowScoreReacquire = usesLowScoreReacquire;
            UsesServerReacquire = usesServerReacquire;
        }
    }
}

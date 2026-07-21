using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;
using EgoAnchor.Alignment;
using EgoAnchor.Client;
using EgoAnchor.Eval;
using EgoAnchor.Eval.Experiment;
using EgoAnchor.Policy;
using EgoAnchor.Protocol.Generated;
using EgoAnchor.Runtime;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.InputSystem;

namespace EgoAnchor.Tests
{
    /// <summary>评估公共状态文本测试，固定实验界面共用的显示规则。</summary>
    public sealed class EvalStatusTextTests
    {
        /// <summary>录制、session 与时长文本必须使用稳定格式。</summary>
        [Test]
        public void CommonStatusTextUsesStableFormatting()
        {
            Assert.That(EvalStatusText.Recording(true), Is.EqualTo("[REC] Recording"));
            Assert.That(EvalStatusText.Recording(false), Is.EqualTo("[IDLE] Not Recording"));
            Assert.That(EvalStatusText.Session(string.Empty), Is.EqualTo("Session: Not Started"));
            Assert.That(EvalStatusText.Session("session-01"), Is.EqualTo("Session: session-01"));
            Assert.That(EvalStatusText.Duration(-1.0), Is.EqualTo("00:00"));
            Assert.That(EvalStatusText.Duration(65.9), Is.EqualTo("01:05"));
        }

        /// <summary>公共活动行样式只包裹选中内容。</summary>
        [Test]
        public void SelectionRowHighlightsOnlyActiveContent()
        {
            var builder = new StringBuilder();
            EvalStatusText.AppendSelectionRow(builder, "[1]  Static", false);
            EvalStatusText.AppendSelectionRow(builder, "[2]  Occlusion", true);

            Assert.That(
                builder.ToString(),
                Is.EqualTo("[1]  Static\n<color=#FFD700><b>[2]  Occlusion  ◀</b></color>\n"));
        }
    }

    /// <summary>实时诊断面板的采样语义和文本契约测试。</summary>
    public sealed class EvalLiveStatsTests
    {
        /// <summary>面板必须实时计算显示 pose 相对平台参考的差异，并保持 ASCII 输出。</summary>
        [Test]
        public void LiveStatsUsesHeldPlatformReferenceWhileTransformIsInactive()
        {
            GameObject recorderObject = new GameObject("LiveStatsTests.Recorder");
            GameObject runtimeObject = new GameObject("LiveStatsTests.Runtime");
            GameObject referenceObject = new GameObject("LiveStatsTests.Reference");
            GameObject statsObject = new GameObject("LiveStatsTests.Panel");
            GameObject historyObject = new GameObject("LiveStatsTests.History");
            try
            {
                EvalRecorder recorder = recorderObject.AddComponent<EvalRecorder>();
                PoseToAnchorRuntime runtime = runtimeObject.AddComponent<PoseToAnchorRuntime>();
                EvalLiveStats stats = statsObject.AddComponent<EvalLiveStats>();
                FramePoseHistory history = historyObject.AddComponent<FramePoseHistory>();

                SetPrivateField(recorder, "groundTruth", referenceObject.transform);
                SetPrivateEnumField(recorder, "gtController", 0);
                SetPrivateField(recorder, "variants", new List<EvalVariant>
                {
                    new EvalVariant
                    {
                        label = "EgoAnchor",
                        runtime = runtime,
                        anchorTransform = runtimeObject.transform,
                        isPrimary = true,
                    },
                });
                SetPrivateField(recorder, "framePoseHistory", history);
                SetPrivateField(stats, "recorder", recorder);

                var timingResult = new PoseResult
                {
                    Header = new MessageHeader { FrameId = 7 },
                    HasPose = false,
                    ServerReceiveMonoMs = 1000.0,
                    ServerPublishMonoMs = 1042.0,
                };
                runtime.AcceptPoseResult(timingResult);

                double nowMs = Time.realtimeSinceStartupAsDouble * 1000.0;
                history.Record(
                    7,
                    Pose.identity,
                    Pose.identity,
                    Pose.identity,
                    nowMs - 100.0,
                    1,
                    0,
                    nowMs - 90.0,
                    1);
                SetPrivateField(runtime, "latestAlignedFrameId", 7L);
                SetPrivateField(runtime, "latestUnityPoseHandleFrameId", 7L);
                SetPrivateField(runtime, "latestUnityPoseHandleMonoMs", nowMs - 30.0);
                SetPrivateField(runtime, "hasOutputPose", true);
                SetPrivateField(runtime, "outputPose", Pose.identity);
                runtimeObject.transform.SetPositionAndRotation(
                    new Vector3(0.01f, 0f, 0f),
                    Quaternion.Euler(0f, 10f, 0f));
                InvokeSample(stats);

                runtimeObject.transform.SetPositionAndRotation(
                    new Vector3(0.012f, 0f, 0f),
                    Quaternion.Euler(0f, 12f, 0f));
                InvokeSample(stats);

                Assert.That(stats.HasOutput, Is.True);
                Assert.That(stats.HasReference, Is.True);
                Assert.That(stats.ReferenceActive, Is.True);
                Assert.That(stats.HasDisplay, Is.True);
                Assert.That(stats.LatestE2eArrivalMs, Is.EqualTo(70.0).Within(2.0));
                Assert.That(runtime.LatestServerProcessingMs, Is.EqualTo(42.0).Within(1e-6));
                Assert.That(stats.LatestPositionDeltaM, Is.EqualTo(0.012).Within(1e-5));
                Assert.That(stats.LatestRotationDeltaDeg, Is.EqualTo(12.0).Within(1e-3));
                Assert.That(stats.LatestFrameStepM, Is.EqualTo(0.002).Within(1e-5));
                Assert.That(stats.LatestFrameStepDeg, Is.EqualTo(2.0).Within(1e-3));

                string text = stats.BuildStatsText();
                StringAssert.Contains("LIVE SYSTEM DIAGNOSTICS", text);
                StringAssert.Contains("PRIMARY  EgoAnchor", text);
                StringAssert.Contains("XR DEVICE  NOT RUNNING", text);
                StringAssert.Contains("XR FOCUS   NOT RUNNING", text);
                StringAssert.Contains("DISPLAY VS PLATFORM CONTROLLER", text);
                StringAssert.Contains("POSITION DELTA", text);
                StringAssert.Contains("12.0 mm", text);
                StringAssert.Contains("ROTATION DELTA", text);
                StringAssert.Contains("12.00 deg", text);
                StringAssert.Contains("E2E ARRIVAL", text);
                StringAssert.Contains("SERVER  42 ms", text);
                StringAssert.Contains("VCD  LATEST", text);
                StringAssert.Contains("FRAME STEP  2.0 mm / 2.00 deg", text);
                StringAssert.Contains("REF <color=#4DD6A6>ACTIVE</color>", text);
                StringAssert.DoesNotContain("Ground Truth", text);
                StringAssert.DoesNotContain("Latency", text);
                AssertAscii(text);

                referenceObject.SetActive(false);
                referenceObject.transform.SetPositionAndRotation(
                    new Vector3(100f, 0f, 0f),
                    Quaternion.Euler(0f, 180f, 0f));
                InvokeSample(stats);

                Assert.That(stats.HasReference, Is.True);
                Assert.That(stats.ReferenceActive, Is.False);
                Assert.That(stats.LatestPositionDeltaM, Is.EqualTo(0.012).Within(1e-5));
                Assert.That(stats.LatestRotationDeltaDeg, Is.EqualTo(12.0).Within(1e-3));
                StringAssert.Contains("REF <color=#FFD054>HELD</color>", stats.BuildStatsText());
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(statsObject);
                UnityEngine.Object.DestroyImmediate(historyObject);
                UnityEngine.Object.DestroyImmediate(referenceObject);
                UnityEngine.Object.DestroyImmediate(runtimeObject);
                UnityEngine.Object.DestroyImmediate(recorderObject);
            }
        }

        /// <summary>session 开始时参考已失活，也必须沿用 Play 生命周期内最后一次激活 Transform。</summary>
        [Test]
        public void RecorderKeepsLastActiveReferenceAcrossSessionStart()
        {
            GameObject recorderObject = new GameObject("LiveStatsTests.SessionRecorder");
            GameObject referenceObject = new GameObject("LiveStatsTests.SessionReference");
            string directory = Path.Combine(
                Application.temporaryCachePath,
                $"egoanchor_reference_hold_{Guid.NewGuid():N}");
            try
            {
                EvalRecorder recorder = recorderObject.AddComponent<EvalRecorder>();
                SetPrivateField(recorder, "groundTruth", referenceObject.transform);
                SetPrivateEnumField(recorder, "gtController", 0);

                referenceObject.transform.SetPositionAndRotation(
                    new Vector3(1f, 2f, 3f),
                    Quaternion.Euler(0f, 20f, 0f));
                Assert.That(recorder.TryGetLiveReferencePose(out Pose activePose, out bool active), Is.True);
                Assert.That(active, Is.True);

                referenceObject.SetActive(false);
                referenceObject.transform.SetPositionAndRotation(
                    new Vector3(100f, 200f, 300f),
                    Quaternion.Euler(0f, 180f, 0f));
                Directory.CreateDirectory(directory);
                recorder.BeginRecording(
                    Path.Combine(directory, "reference.jsonl"),
                    Path.Combine(directory, "admission.jsonl"),
                    Path.Combine(directory, "render.jsonl"),
                    Path.Combine(directory, "events.jsonl"),
                    "reference-hold-session");

                Assert.That(recorder.TryGetLiveReferencePose(out Pose heldPose, out active), Is.True);
                Assert.That(active, Is.False);
                Assert.That(heldPose.position, Is.EqualTo(activePose.position));
                Assert.That(Quaternion.Angle(heldPose.rotation, activePose.rotation), Is.LessThan(1e-4f));
            }
            finally
            {
                EvalRecorder recorder = recorderObject.GetComponent<EvalRecorder>();
                if (recorder != null) recorder.StopRecording();
                UnityEngine.Object.DestroyImmediate(referenceObject);
                UnityEngine.Object.DestroyImmediate(recorderObject);
                if (Directory.Exists(directory)) Directory.Delete(directory, true);
            }
        }

        /// <summary>正式参考必须在开始前观察到真实运动；右手 prefab 身份由场景契约另行冻结。</summary>
        [Test]
        public void RecorderRequiresReferenceMotionPreflight()
        {
            GameObject rig = new GameObject("OVRCameraRig");
            GameObject interaction = new GameObject("OVRInteractionComprehensive");
            GameObject visual = new GameObject("OVRControllerVisualRight");
            GameObject reference = new GameObject("OVRControllerPrefab");
            GameObject recorderObject = new GameObject("ReferenceValidation.Recorder");
            try
            {
                interaction.transform.SetParent(rig.transform, false);
                visual.transform.SetParent(interaction.transform, false);
                reference.transform.SetParent(visual.transform, false);
                EvalRecorder recorder = recorderObject.AddComponent<EvalRecorder>();
                SetPrivateField(recorder, "groundTruth", reference.transform);
                SetPrivateEnumField(recorder, "gtController", 0);
                InvokeReferencePreflight(recorder);
                Assert.That(
                    recorder.TryValidatePlatformReference("custom_object", out string error),
                    Is.False);
                StringAssert.Contains("platformReferencePreflight", error);

                reference.transform.position = new Vector3(0.02f, 0f, 0f);
                InvokeReferencePreflight(recorder);

                Assert.That(recorder.TryValidatePlatformReference("custom_object", out error), Is.True);
                Assert.That(error, Is.Empty);
                Assert.That(
                    recorder.PlatformReferenceTransformPath,
                    Is.EqualTo(
                        "OVRCameraRig/OVRInteractionComprehensive/OVRControllerVisualRight/OVRControllerPrefab"));
                Assert.That(recorder.PlatformReferenceController, Is.EqualTo("None"));
                Assert.That(
                    recorder.TryValidatePlatformReference("controller_right", out error),
                    Is.False);
                StringAssert.Contains("platformReferenceController", error);
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(recorderObject);
                UnityEngine.Object.DestroyImmediate(rig);
            }
        }

        /// <summary>反射调用私有采样入口，避免为了测试扩大逐帧更新 API。</summary>
        private static void InvokeSample(EvalLiveStats stats)
        {
            MethodInfo method = typeof(EvalLiveStats).GetMethod(
                "SampleLiveSignals",
                BindingFlags.Instance | BindingFlags.NonPublic);
            Assert.That(method, Is.Not.Null);
            method.Invoke(stats, Array.Empty<object>());
        }

        /// <summary>反射执行一次参考运动预检采样。</summary>
        private static void InvokeReferencePreflight(EvalRecorder recorder)
        {
            MethodInfo method = typeof(EvalRecorder).GetMethod(
                "Update",
                BindingFlags.Instance | BindingFlags.NonPublic);
            Assert.That(method, Is.Not.Null);
            method.Invoke(recorder, Array.Empty<object>());
        }

        /// <summary>设置测试需要的序列化字段。</summary>
        private static void SetPrivateField(object target, string fieldName, object value)
        {
            FieldInfo field = target.GetType().GetField(
                fieldName,
                BindingFlags.Instance | BindingFlags.NonPublic);
            Assert.That(field, Is.Not.Null, $"missing private field {fieldName}");
            field.SetValue(target, value);
        }

        /// <summary>设置测试程序集无法直接引用的外部枚举字段。</summary>
        private static void SetPrivateEnumField(object target, string fieldName, int value)
        {
            FieldInfo field = target.GetType().GetField(
                fieldName,
                BindingFlags.Instance | BindingFlags.NonPublic);
            Assert.That(field, Is.Not.Null, $"missing private enum field {fieldName}");
            Assert.That(field.FieldType.IsEnum, Is.True, $"field {fieldName} is not an enum");
            field.SetValue(target, Enum.ToObject(field.FieldType, value));
        }

        /// <summary>实时头显文本必须使用当前字体可稳定显示的 ASCII 字符。</summary>
        private static void AssertAscii(string text)
        {
            foreach (char character in text)
            {
                bool allowed = character == '\r' || character == '\n' || character == '\t'
                    || (character >= ' ' && character <= '~');
                Assert.That(allowed, Is.True, $"non-ASCII character U+{(int)character:X4}");
            }
        }
    }

    /// <summary>Quest 双目发布器的 XR focus 保护测试。</summary>
    public sealed class QuestStreamPublisherTests
    {
        /// <summary>VR focus 丢失时必须暂停采集，恢复后继续并各通知一次。</summary>
        [Test]
        public void PublisherPausesCaptureWhileVrFocusIsLost()
        {
            GameObject owner = new GameObject("QuestStreamPublisherTests.Owner");
            owner.SetActive(false);
            try
            {
                QuestStreamPublisher publisher = owner.AddComponent<QuestStreamPublisher>();
                var focusEvents = new List<bool>();
                publisher.VrFocusChanged += focusEvents.Add;

                InvokeVrFocus(publisher, false);
                Assert.That(publisher.HasVrFocus, Is.False);
                Assert.That(publisher.CapturePausedForVrFocus, Is.True);

                InvokeVrFocus(publisher, true);
                Assert.That(publisher.HasVrFocus, Is.True);
                Assert.That(publisher.CapturePausedForVrFocus, Is.False);
                Assert.That(focusEvents, Is.EqualTo(new[] { false, true }));
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(owner);
            }
        }

        /// <summary>反射调用私有 focus 更新入口，避免测试触发真实 OpenXR 生命周期。</summary>
        private static void InvokeVrFocus(QuestStreamPublisher publisher, bool hasFocus)
        {
            MethodInfo method = typeof(QuestStreamPublisher).GetMethod(
                "SetVrFocus",
                BindingFlags.Instance | BindingFlags.NonPublic);
            Assert.That(method, Is.Not.Null);
            method.Invoke(publisher, new object[] { hasFocus });
        }
    }

    /// <summary>schema-v2 Unity 长表与 manifest 的 JSON contract 测试。</summary>
    public sealed class EvalSchemaV2JsonTests
    {
        /// <summary>reference、admission、render、manifest 均必须使用 schema-v2 固定字段。</summary>
        [Test]
        public void JsonLinesUseSchemaV2AndFlatRenderRows()
        {
            string reference = EvalJson.BuildReferenceLine(
                7, 1000, 2000, 3, 1010, 4, 1020, 1, 1030, true,
                Pose.identity, true, Pose.identity,
                new EvalReferencePose(true, true, false, Pose.identity, 0), "Left", "s01");
            string admission = EvalJson.BuildAdmissionLine(new EvalAdmissionSnapshot(
                "s01", "s01:7:1", 7, "egoanchor", "EgoAnchor", 1040,
                5, Runtime.WorldAlignmentMode.CaptureTime, true, 1000, 3,
                true, Pose.identity, false, Pose.identity, double.NaN,
                true, 0.8f, "aligned", "accepted", "quality_ok", "Tracking",
                "enabled", "kalman", "hermite", true, true, "cfg"));
            EvalVariantSnapshot variant = new EvalVariantSnapshot(
                "egoanchor", true, 7, true, Pose.identity, true, Pose.identity, "transform",
                true, 1000, 3, 20, 1010, 10, 1040, "Tracking", "accepted", "quality_ok",
                "TRACK", string.Empty, "static", 0, "egoanchor", "enabled", "kalman", "hermite",
                "cfg", 0, 0, 0.8f, false, false, Pose.identity, false, Pose.identity, double.NaN, -1, "Left", 0.8f);
            string render = EvalJson.BuildRenderLine(
                1100, 2100, 5, Pose.identity,
                new EvalReferencePose(false, false, false, Pose.identity, double.NaN), 0, 0,
                variant, "s01");
            string eventLine = EvalJson.BuildEventLine(
                "s01", "event_marker", "experiment_ui", "marked", 1050, 5,
                ExperimentId.SystemCharacterization, "static_head_motion", "trial_001", "event_001",
                "exp1_system_characterization/static_head_motion", ExperimentEventRole.GenericMarker,
                "info", "egoanchor");
            string manifest = EvalJson.BuildManifest(
                new EvalManifestMetadata(
                    "s01", "controller_right", "operator-01", 2000,
                    "editor_link", string.Empty, "6000.3.11f1", string.Empty,
                    "commit", "v1", string.Empty, "controller-mesh-v1", string.Empty,
                    "OVRCameraRig/OVRInteractionComprehensive/OVRControllerVisualRight/OVRControllerPrefab",
                    "RTouch", true),
                new[] { "EgoAnchor" },
                new[]
                {
                    new EvalVariantConfig(
                        "EgoAnchor", "kalman", "hermite", "enabled", "cfg",
                        "CaptureTime", true, true, true, true, true, true),
                },
                new EvalLogStats(0, 1, null, 2), new EvalLogStats(0, 1, null, 2),
                new EvalLogStats(0, 1, null, 2), new EvalLogStats(0, 1, null, 2),
                new[]
                {
                    new CompletedExperimentTask(
                        1, ExperimentId.SystemCharacterization, "static_head_motion", "trial_001"),
                    new CompletedExperimentTask(
                        3, ExperimentId.SystemCharacterization, "continuous_translation", "trial_002"),
                });

            foreach (string line in new[] { reference, admission, render })
            {
                StringAssert.Contains("\"schema_version\":2", line);
                StringAssert.DoesNotContain("rq1_", line);
                StringAssert.DoesNotContain("rq2_", line);
                StringAssert.DoesNotContain("gt_", line);
            }
            StringAssert.Contains("\"event\":\"unity_reference\"", reference);
            StringAssert.Contains("\"event\":\"unity_admission\"", admission);
            StringAssert.Contains("\"event\":\"unity_render\"", render);
            foreach (string field in new[]
            {
                "event_type", "source", "created_unix_ms", "mono_ms", "unity_frame", "severity",
                "experiment_id", "scenario_id", "trial_id", "event_id", "variant_id", "message", "payload",
            })
                StringAssert.Contains($"\"{field}\":", eventLine);
            StringAssert.Contains("\"severity\":\"info\"", eventLine);
            StringAssert.Contains("\"variant_id\":\"egoanchor\"", eventLine);
            StringAssert.Contains(
                "\"payload\":{\"condition_id\":\"exp1_system_characterization/static_head_motion\",\"event_role\":\"generic_marker\"}",
                eventLine);
            foreach (string field in new[]
            {
                "unity_frame", "source_capture_mono_ms", "source_capture_unity_frame",
                "arrival_time_raw_mono_ms", "quality_gate", "policy_action", "motion_model",
                "smoothing_strategy", "uses_temporal_synthesis", "uses_static_lock",
            })
                StringAssert.Contains($"\"{field}\":", admission);
            StringAssert.DoesNotContain("\"variants\"", render);
            foreach (string file in new[] { "python_candidates.jsonl", "unity_reference.jsonl", "unity_admission.jsonl", "unity_render.jsonl", "events.jsonl" })
                StringAssert.Contains(file, manifest);
            CollectionAssert.AreEqual(
                new[] { "python_candidates.jsonl", "unity_reference.jsonl", "unity_admission.jsonl", "unity_render.jsonl", "events.jsonl" },
                EvalV2Manifest.FixedLogFileNames);
            StringAssert.Contains("\"dropped_rows\":0", manifest);
            StringAssert.Contains("\"python_candidates.jsonl\":{\"rows_written\":null,\"dropped_rows\":null", manifest);
            StringAssert.Contains("\"status\":\"pending_python_fragment_merge\"", manifest);
            StringAssert.Contains("\"peak_queue_depth\":1", manifest);
            StringAssert.Contains("\"run_kind\":\"formal\"", manifest);
            StringAssert.Contains($"\"variant_matrix_id\":\"{EvalV2Manifest.VariantMatrixId}\"", manifest);
            Match configHash = Regex.Match(manifest, "\\\"config_hash\\\":\\\"(?<hash>[0-9a-f]{16})\\\"");
            Assert.That(configHash.Success, Is.True);
            StringAssert.Contains(
                $"\"frozen_parameter_set_id\":\"{configHash.Groups["hash"].Value}\"",
                manifest);
            StringAssert.Contains("\"experiment_ids\":[\"exp1_system_characterization\",\"exp2_design_attribution\"]", manifest);
            foreach (string field in new[]
            {
                "session_id", "object_id", "run_kind", "experiment_ids", "operator_id", "created_unix_ms",
                "unity_run_mode", "python_host", "unity_version", "python_version", "egoanchor_git_commit",
                "protocol_version", "config_hash", "frozen_parameter_set_id", "object_model_id",
                "platform_reference", "variant_matrix_id", "variant_definitions", "completed_tasks", "trial_plan",
                "log_files", "log_writer_stats",
            })
                StringAssert.Contains($"\"{field}\":", manifest);
            StringAssert.Contains(
                "\"completed_tasks\":[{\"task_number\":1,\"experiment_id\":\"exp1_system_characterization\",\"scenario_id\":\"static_head_motion\",\"trial_id\":\"trial_001\"},{\"task_number\":3",
                manifest);
            StringAssert.Contains("\"scenario_id\":\"occlusion_recovery\"", manifest);
            StringAssert.DoesNotContain("\"scenario_id\":\"without_static_lock\"", manifest);
            StringAssert.Contains("\"controller\":\"RTouch\"", manifest);
            StringAssert.Contains("\"preflight_passed\":true", manifest);
            StringAssert.DoesNotContain("minimum_seconds", manifest);
            StringAssert.DoesNotContain("maximum_seconds", manifest);
            StringAssert.Contains("\"config_hash\":", manifest);
            StringAssert.Contains("\"uses_vcd_admission\":true", manifest);
            StringAssert.Contains("\"uses_temporal_synthesis\":true", manifest);
            StringAssert.Contains("\"uses_static_lock\":true", manifest);
            StringAssert.Contains("\"uses_low_score_reacquire\":true", manifest);
            StringAssert.Contains("\"uses_server_reacquire\":true", manifest);
        }
    }

    /// <summary>实验一/实验二采集上下文和输入状态机测试。</summary>
    public sealed class ExperimentContextTests
    {
        /// <summary>未录制时可先选择任务，但不得写入 marker。</summary>
        [Test]
        public void SelectorAllowsSelectionBeforeRecording()
        {
            WithSelector((_, selector) =>
            {
                Assert.That(selector.SelectedTaskIndex, Is.EqualTo(0));
                Assert.That(selector.MoveSelection(Vector2.right), Is.True);
                Assert.That(selector.SelectedTaskIndex, Is.EqualTo(1));
                Assert.That(selector.SelectTask(4), Is.True);
                Assert.That(selector.MarkEvent(), Is.False);
                Assert.That(selector.HasMarkerFeedback, Is.True);
                Assert.That(selector.MarkerFeedbackSucceeded, Is.False);
                Assert.That(selector.MarkerFeedbackText, Is.EqualTo("MARKER IGNORED: START A TASK FIRST"));
                Assert.That(selector.CurrentContext.IsSelected, Is.True);
                Assert.That(selector.CurrentPhaseText, Is.EqualTo("TASK SELECTED - READY"));
            }, recording: false);
        }

        /// <summary>第一次开始动作必须原子地启动 session 和当前选中 trial，不要求第二次确认。</summary>
        [Test]
        public void StartActionStartsSessionAndSelectedTrialOnce()
        {
            string root = Path.Combine(
                Application.temporaryCachePath,
                $"egoanchor_one_start_{Guid.NewGuid():N}");
            string sessionId = $"test_{Guid.NewGuid():N}_controller_right";
            GameObject owner = new GameObject("ExperimentContextTests.OneStart");
            try
            {
                EvalRecorder recorder = owner.AddComponent<EvalRecorder>();
                PoseToAnchorRuntime runtime = owner.AddComponent<PoseToAnchorRuntime>();
                AnchorRuntimeHub hub = owner.AddComponent<AnchorRuntimeHub>();
                EvalSession session = owner.AddComponent<EvalSession>();
                ExperimentTrialSelector selector = owner.AddComponent<ExperimentTrialSelector>();
                ExperimentInputHandler input = owner.AddComponent<ExperimentInputHandler>();

                SetPrivateField(recorder, "groundTruth", owner.transform);
                SetPrivateField(recorder, "_referencePreflightPassed", true);
                SetPrivateField(recorder, "variants", new List<EvalVariant>
                {
                    new EvalVariant
                    {
                        label = "test-formal",
                        runtime = runtime,
                        anchorTransform = owner.transform,
                        isPrimary = true,
                    },
                });
                SetPrivateField(recorder, "experimentSelector", selector);
                SetPrivateField(hub, "latestPythonSessionId", sessionId);
                SetPrivateField(session, "recorder", recorder);
                SetPrivateField(session, "runtimeHub", hub);
                SetPrivateField(session, "outputRoot", root);
                SetPrivateField(session, "objectId", "test_object");
                SetPrivateField(input, "selector", selector);
                selector.BindSession(session);

                var eventTypes = new List<string>();
                selector.ContextEvent += (_, eventType) => eventTypes.Add(eventType);
                Assert.That(selector.SelectTask(4), Is.True);
                Assert.That(session.IsRecording, Is.False);
                Assert.That(selector.HasActiveTrial, Is.False);

                Assert.That(input.HandleStart(), Is.True);

                Assert.That(session.IsRecording, Is.True);
                Assert.That(selector.HasActiveTrial, Is.True);
                Assert.That(selector.SelectedTaskIndex, Is.EqualTo(4));
                Assert.That(selector.ActiveTaskIndex, Is.EqualTo(4));
                Assert.That(selector.CurrentTrialId, Is.EqualTo("trial_001"));
                Assert.That(eventTypes.FindAll(item => item == "trial_started").Count, Is.EqualTo(1));
                Assert.That(input.HandleStart(), Is.False);
                Assert.That(eventTypes.FindAll(item => item == "trial_started").Count, Is.EqualTo(1));

                Assert.That(input.HandleFinish(), Is.True);
                Assert.That(session.IsRecording, Is.False);
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(owner);
                if (Directory.Exists(root)) Directory.Delete(root, true);
            }
        }

        /// <summary>摇杆四方向必须按三乘三网格选场，运行中禁止切换。</summary>
        [Test]
        public void SelectorNavigatesTaskGridAndLocksDuringTrial()
        {
            WithSelector((_, selector) =>
            {
                Assert.That(selector.SelectedTaskIndex, Is.EqualTo(0));
                Assert.That(selector.MoveSelection(Vector2.right), Is.True);
                Assert.That(selector.SelectedTaskIndex, Is.EqualTo(1));
                Assert.That(selector.MoveSelection(Vector2.down), Is.True);
                Assert.That(selector.SelectedTaskIndex, Is.EqualTo(4));
                Assert.That(selector.MoveSelection(Vector2.left), Is.True);
                Assert.That(selector.SelectedTaskIndex, Is.EqualTo(3));
                Assert.That(selector.MoveSelection(Vector2.up), Is.True);
                Assert.That(selector.SelectedTaskIndex, Is.EqualTo(0));
                Assert.That(selector.MoveSelection(Vector2.left), Is.False);

                Assert.That(selector.StartTrial(), Is.True);
                Assert.That(selector.MoveSelection(Vector2.right), Is.False);
                Assert.That(selector.SelectedTaskIndex, Is.EqualTo(0));
            });
        }

        /// <summary>普通任务必须独立开始、写主事件并结束，不自动切换场景。</summary>
        [Test]
        public void SelectorRunsSelectedTaskWithExplicitActions()
        {
            WithSelector((_, selector) =>
            {
                Assert.That(selector.SelectTask(1), Is.True);
                Assert.That(selector.StartTrial(), Is.True);
                Assert.That(selector.CurrentTrialId, Is.EqualTo("trial_001"));
                Assert.That(selector.MarkEvent(), Is.True);
                Assert.That(selector.CurrentEventRole, Is.EqualTo(ExperimentEventRole.TransitionStarted));
                Assert.That(selector.HasMarkerFeedback, Is.True);
                Assert.That(selector.MarkerFeedbackSucceeded, Is.True);
                Assert.That(selector.MarkerFeedbackText, Is.EqualTo("MARKER SAVED #1: MOTION START"));
                Assert.That(selector.CurrentPhaseText, Is.EqualTo("MOTION IN PROGRESS"));
                StringAssert.DoesNotContain("RECOVERY", selector.CurrentPhaseText);
                Assert.That(selector.EndTrial(), Is.True);

                Assert.That(selector.HasActiveTrial, Is.False);
                Assert.That(selector.SelectedTaskIndex, Is.EqualTo(1));
                Assert.That(selector.IsTaskCompleted(1), Is.True);
                Assert.That(selector.CompletedTaskCount, Is.EqualTo(1));
            });
        }

        /// <summary>写入必需 marker 后可立即结束，不以经过时长作为门禁。</summary>
        [Test]
        public void SelectorAllowsImmediateEndAfterRequiredMarker()
        {
            WithSelector((_, selector) =>
            {
                Assert.That(selector.StartTrial(), Is.True);
                Assert.That(selector.MarkEvent(), Is.True);
                Assert.That(selector.EndTrial(), Is.True);
                Assert.That(selector.IsTaskCompleted(0), Is.True);
            });
        }

        /// <summary>遮挡任务必须允许多组遮挡/可见 marker，悬空遮挡时不得结束。</summary>
        [Test]
        public void SelectorAlternatesOcclusionMarkers()
        {
            WithSelector((_, selector) =>
            {
                selector.SelectTask(4);
                selector.StartTrial();
                Assert.That(selector.MarkEvent(), Is.True);
                Assert.That(selector.CurrentEventRole, Is.EqualTo(ExperimentEventRole.OcclusionStarted));
                Assert.That(selector.HasOpenOcclusion, Is.True);
                Assert.That(selector.EndTrial(), Is.False);

                Assert.That(selector.MarkEvent(), Is.True);
                Assert.That(selector.CurrentEventRole, Is.EqualTo(ExperimentEventRole.TargetVisible));
                Assert.That(selector.HasOpenOcclusion, Is.False);
                Assert.That(selector.CurrentPhaseText, Is.EqualTo("TARGET VISIBLE"));
                Assert.That(selector.MarkEvent(), Is.True);
                Assert.That(selector.CurrentEventRole, Is.EqualTo(ExperimentEventRole.OcclusionStarted));
                Assert.That(selector.MarkEvent(), Is.True);
                Assert.That(selector.CurrentEventRole, Is.EqualTo(ExperimentEventRole.TargetVisible));
                Assert.That(selector.EndTrial(), Is.True);
                Assert.That(selector.IsTaskCompleted(4), Is.True);
            });
        }

        /// <summary>作废活动或已完成 trial 后只重做该任务，不清空其他完成状态。</summary>
        [Test]
        public void SelectorRejectsOnlySelectedTrialForRedo()
        {
            WithSelector((_, selector) =>
            {
                var eventTypes = new List<string>();
                selector.ContextEvent += (_, eventType) => eventTypes.Add(eventType);

                CompleteTask(selector, 0);
                CompleteTask(selector, 1);
                selector.SelectTask(0);
                Assert.That(selector.IsTaskCompleted(0), Is.True);
                Assert.That(selector.RejectCurrentOrSelected(), Is.True);
                Assert.That(selector.IsTaskCompleted(0), Is.False);
                Assert.That(selector.IsTaskCompleted(1), Is.True);
                Assert.That(selector.CompletedTaskCount, Is.EqualTo(1));
                CollectionAssert.Contains(eventTypes, "trial_rejected");

                selector.SelectTask(2);
                selector.StartTrial();
                Assert.That(selector.RejectCurrentOrSelected(), Is.True);
                Assert.That(selector.HasActiveTrial, Is.False);
                Assert.That(selector.IsTaskCompleted(1), Is.True);
                Assert.That(selector.IsTaskCompleted(2), Is.False);
                Assert.That(eventTypes.FindAll(item => item == "trial_rejected").Count, Is.EqualTo(2));
            });
        }

        /// <summary>按开始动作重录已完成任务时，旧 trial 必须先写入 rejected 审计。</summary>
        [Test]
        public void SelectorRerecordsCompletedTaskWithRejectedAudit()
        {
            WithSelector((_, selector) =>
            {
                var events = new List<Tuple<ExperimentContext, string>>();
                selector.ContextEvent += (context, eventType) => events.Add(Tuple.Create(context, eventType));

                CompleteTask(selector, 0);
                Assert.That(selector.CurrentTrialId, Is.Empty);
                Assert.That(selector.StartTrial(), Is.True);
                Assert.That(selector.HasActiveTrial, Is.True);
                Assert.That(selector.CurrentTrialId, Is.EqualTo("trial_002"));
                Assert.That(selector.IsTaskCompleted(0), Is.False);

                Assert.That(
                    events.Exists(item => item.Item1.TrialId == "trial_001" && item.Item2 == "trial_rejected"),
                    Is.True);
            });
        }

        /// <summary>完成任意任务子集后可独立停止模块化 session。</summary>
        [Test]
        public void SelectorFinishesPartialSessionAfterExplicitConfirmation()
        {
            WithSelector((session, selector) =>
            {
                CompleteTask(selector, 0);
                CompleteTask(selector, 2);

                Assert.That(selector.CompletedTaskCount, Is.EqualTo(2));
                Assert.That(selector.CanFinishSession, Is.True);
                Assert.That(session.IsRecording, Is.True);
                Assert.That(selector.FinishSessionNow(), Is.True);
                Assert.That(session.IsRecording, Is.False);
            });
        }

        /// <summary>即使尚无完成任务，也允许随时正常关闭 session。</summary>
        [Test]
        public void SelectorAllowsEmptySessionFinish()
        {
            WithSelector((session, selector) =>
            {
                Assert.That(selector.CanFinishSession, Is.True);
                Assert.That(selector.FinishSessionNow(), Is.True);
                Assert.That(session.IsRecording, Is.False);
            });
        }

        /// <summary>活动任务中停止 session 时只作废该 trial，并保留其他完成任务。</summary>
        [Test]
        public void SelectorRejectsActiveTrialWhenSessionStops()
        {
            WithSelector((session, selector) =>
            {
                CompleteTask(selector, 0);
                selector.SelectTask(2);
                selector.StartTrial();
                Assert.That(selector.CanFinishSession, Is.True);
                Assert.That(selector.FinishSessionNow(), Is.True);

                Assert.That(session.IsRecording, Is.False);
                Assert.That(selector.HasActiveTrial, Is.False);
                Assert.That(selector.IsTaskCompleted(0), Is.True);
                Assert.That(selector.IsTaskCompleted(2), Is.False);
            });
        }

        /// <summary>完成摘要只保留未作废任务，并按任务编号稳定排序。</summary>
        [Test]
        public void SelectorCollectsFinalCompletedTaskSubset()
        {
            WithSelector((_, selector) =>
            {
                CompleteTask(selector, 2);
                CompleteTask(selector, 0);
                selector.SelectTask(2);
                Assert.That(selector.RejectCurrentOrSelected(), Is.True);

                var tasks = new List<CompletedExperimentTask>();
                selector.CollectCompletedTasks(tasks);

                Assert.That(tasks.Count, Is.EqualTo(1));
                Assert.That(tasks[0].TaskNumber, Is.EqualTo(1));
                Assert.That(tasks[0].ScenarioId, Is.EqualTo("static_head_motion"));
                Assert.That(tasks[0].TrialId, Is.EqualTo("trial_002"));
            });
        }

        /// <summary>输入组件必须暴露内联 InputAction，数字键只选择，其他动作与手柄共用状态机。</summary>
        [Test]
        public void InputHandlerUsesInlineActionsAndTaskKeys()
        {
            WithSelector((session, selector) =>
            {
                GameObject inputObject = new GameObject("ExperimentContextTests.Input");
                try
                {
                    ExperimentInputHandler input = inputObject.AddComponent<ExperimentInputHandler>();
                    SetPrivateField(input, "selector", selector);

                    Assert.That(input.HandleTask(2), Is.True);
                    Assert.That(selector.SelectedTaskIndex, Is.EqualTo(2));
                    Assert.That(selector.HasActiveTrial, Is.False);
                    Assert.That(input.HandleStart(), Is.True);
                    Assert.That(selector.HasActiveTrial, Is.True);
                    Assert.That(input.HandleTask(2), Is.False);
                    Assert.That(selector.CurrentEventRole, Is.EqualTo(ExperimentEventRole.None));
                    Assert.That(input.HandleMark(), Is.True);
                    Assert.That(selector.CurrentEventRole, Is.EqualTo(ExperimentEventRole.GenericMarker));
                    Assert.That(input.HandleStop(), Is.True);
                    Assert.That(selector.IsTaskCompleted(2), Is.True);
                    Assert.That(input.HandleTask(2), Is.True);
                    Assert.That(selector.HasActiveTrial, Is.False);
                    Assert.That(input.HandleStart(), Is.True);
                    Assert.That(selector.CurrentTrialId, Is.EqualTo("trial_002"));
                    Assert.That(selector.IsTaskCompleted(2), Is.False);
                    Assert.That(input.HandleFinish(), Is.True);
                    Assert.That(session.IsRecording, Is.False);

                    foreach (string fieldName in new[]
                    {
                        "navigateAction", "startAction", "markAction", "stopAction", "finishAction", "rejectAction"
                    })
                        Assert.That(GetPrivateField(input, fieldName), Is.TypeOf<InputAction>());
                    Assert.That(GetPrivateField(input, "taskActions"), Is.TypeOf<InputAction[]>());
                    Assert.That(((InputAction[])GetPrivateField(input, "taskActions")).Length, Is.EqualTo(5));
                    Assert.That(input.GetType().GetField("controllerBinding", BindingFlags.Instance | BindingFlags.NonPublic), Is.Null);
                    Assert.That(input.GetType().GetField("keyboardBinding", BindingFlags.Instance | BindingFlags.NonPublic), Is.Null);
                }
                finally
                {
                    UnityEngine.Object.DestroyImmediate(inputObject);
                }
            });
        }

        /// <summary>session 配对后任务 1 只能处于选中状态，必须显式开始后才能进入运行状态。</summary>
        [Test]
        public void StatusUiKeepsInitialTaskSelectedButIdle()
        {
            WithSelector((session, selector) =>
            {
                GameObject uiObject = new GameObject("ExperimentContextTests.InitialUI");
                try
                {
                    ExperimentStatusUI status = uiObject.AddComponent<ExperimentStatusUI>();
                    SetPrivateField(status, "selector", selector);
                    SetPrivateField(status, "session", session);
                    string text = status.BuildStatusText();

                    Assert.That(selector.SelectedTaskIndex, Is.EqualTo(0));
                    Assert.That(selector.HasActiveTrial, Is.False);
                    StringAssert.Contains("[READY] SESSION ACTIVE", text);
                    StringAssert.Contains("SERVER  CONNECTED", text);
                    StringAssert.Contains("<b><color=#FFD054>>[ ]1 HEAD", text);
                    StringAssert.Contains("STATE  <color=#6DD3FF>TASK SELECTED - NOT RUNNING", text);
                    StringAssert.Contains("TIME  <color=#B1BCCC>--:--", text);
                    StringAssert.DoesNotContain("[REC] RECORDING", text);
                    StringAssert.DoesNotContain("[RUN]1 HEAD", text);
                }
                finally
                {
                    UnityEngine.Object.DestroyImmediate(uiObject);
                }
            });
        }

        /// <summary>UI 必须显示五任务状态、直白操作状态、单一计时和统一按键图例。</summary>
        [Test]
        public void StatusUiShowsTaskBoardAndLivePhase()
        {
            WithSelector((session, selector) =>
            {
                GameObject uiObject = new GameObject("ExperimentContextTests.UI");
                try
                {
                    CompleteTask(selector, 0);
                    selector.SelectTask(4);
                    selector.StartTrial();
                    selector.MarkEvent();

                    ExperimentStatusUI status = uiObject.AddComponent<ExperimentStatusUI>();
                    SetPrivateField(status, "selector", selector);
                    SetPrivateField(status, "session", session);
                    string text = status.BuildStatusText();

                    StringAssert.Contains("TASKS  <color=#5BA9FF>1/5 COMPLETE</color>", text);
                    StringAssert.Contains("[OK]1 HEAD", text);
                    StringAssert.Contains(">[RUN]5 OCC", text);
                    StringAssert.Contains("<color=#5BA9FF> [OK]1 HEAD", text);
                    StringAssert.Contains("<b><color=#4DD6A6>>[RUN]5 OCC", text);
                    StringAssert.Contains("MARKER  <size=26><b><color=#4DD6A6>MARKER SAVED #1: OCCLUSION START", text);
                    StringAssert.Contains("Occlusion and reappearance", text);
                    StringAssert.Contains("STATE  <color=#6DD3FF>TARGET OCCLUDED", text);
                    StringAssert.Contains("TIME  <color=#4DD6A6>", text);
                    StringAssert.DoesNotContain("01:30", text);
                    StringAssert.DoesNotContain("02:00", text);
                    StringAssert.DoesNotContain("TO MINIMUM", text);
                    StringAssert.Contains("KEYPAD  1-5 Select | Enter Start | + Marker | 0 End", text);
                    StringAssert.Contains("VR      Stick Select | A Start | Trigger Marker | Tap B End", text);
                    StringAssert.Contains("OTHER   Space Reject | F Stop Session | Hold B Stop", text);
                    StringAssert.DoesNotContain("Phase:", text);
                    StringAssert.DoesNotContain("Role:", text);
                    StringAssert.DoesNotContain("RECOVERY", text);
                    StringAssert.DoesNotContain(ExperimentEventRole.OcclusionStarted, text);
                    StringAssert.DoesNotContain("RQ1", text);
                    StringAssert.DoesNotContain("RQ2", text);
                    AssertAscii(text);
                }
                finally
                {
                    UnityEngine.Object.DestroyImmediate(uiObject);
                }
            });
        }

        /// <summary>已完成任务被选中时仍显示完成蓝色，选中只增加箭头和粗体。</summary>
        [Test]
        public void StatusUiKeepsCompletedColorWhenTaskIsSelected()
        {
            WithSelector((session, selector) =>
            {
                GameObject uiObject = new GameObject("ExperimentContextTests.CompletedUI");
                try
                {
                    CompleteTask(selector, 0);
                    selector.SelectTask(0);

                    ExperimentStatusUI status = uiObject.AddComponent<ExperimentStatusUI>();
                    SetPrivateField(status, "selector", selector);
                    SetPrivateField(status, "session", session);
                    string text = status.BuildStatusText();

                    StringAssert.Contains("<b><color=#5BA9FF>>[OK]1 HEAD", text);
                    StringAssert.DoesNotContain("<b><color=#FFD054>>[OK]1 HEAD", text);
                    StringAssert.Contains("RERECORD: NUMPAD ENTER | REJECT: SPACE", text);
                }
                finally
                {
                    UnityEngine.Object.DestroyImmediate(uiObject);
                }
            });
        }

        /// <summary>session 启动被阻断时，状态面板必须显示可执行的跨端配对原因。</summary>
        [Test]
        public void StatusUiShowsSessionStartBlockReason()
        {
            WithSelector((session, selector) =>
            {
                GameObject uiObject = new GameObject("ExperimentContextTests.BlockedUI");
                try
                {
                    const string reason = "PYTHON SESSION ALREADY HAS UNITY LOGS - RESTART PYTHON";
                    SetPrivateField(session, "_sessionStatusMessage", reason);

                    ExperimentStatusUI status = uiObject.AddComponent<ExperimentStatusUI>();
                    SetPrivateField(status, "selector", selector);
                    SetPrivateField(status, "session", session);
                    string text = status.BuildStatusText();

                    StringAssert.Contains(reason, text);
                    StringAssert.Contains($"NEXT  <size=25><b><color=#FFD054>{reason}</color>", text);
                    AssertAscii(text);
                }
                finally
                {
                    UnityEngine.Object.DestroyImmediate(uiObject);
                }
            }, recording: false);
        }

        /// <summary>完成一个指定任务，遮挡任务自动补齐 target_visible。</summary>
        private static void CompleteTask(ExperimentTrialSelector selector, int index)
        {
            Assert.That(selector.SelectTask(index), Is.True);
            Assert.That(selector.StartTrial(), Is.True);
            Assert.That(selector.MarkEvent(), Is.True);
            if (selector.HasOpenOcclusion)
                Assert.That(selector.MarkEvent(), Is.True);
            Assert.That(selector.EndTrial(), Is.True);
        }

        /// <summary>运行时可见文本只能使用 ASCII，避免默认 TMP 字体回退成乱码。</summary>
        private static void AssertAscii(string text)
        {
            Assert.That(text, Is.Not.Null);
            foreach (char character in text)
            {
                bool allowed = character == '\r' || character == '\n' || character == '\t'
                    || (character >= ' ' && character <= '~');
                Assert.That(allowed, Is.True, $"non-ASCII character U+{(int)character:X4}");
            }
        }

        /// <summary>创建 selector，并按需模拟已开始录制的 session。</summary>
        private static void WithSelector(
            Action<EvalSession, ExperimentTrialSelector> test,
            bool recording = true)
        {
            GameObject sessionObject = new GameObject("ExperimentContextTests.Session");
            GameObject selectorObject = new GameObject("ExperimentContextTests.Selector");
            try
            {
                EvalSession session = sessionObject.AddComponent<EvalSession>();
                SetPrivateField(session, "_recording", recording);
                ExperimentTrialSelector selector = selectorObject.AddComponent<ExperimentTrialSelector>();
                selector.BindSession(session);
                test(session, selector);
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(selectorObject);
                UnityEngine.Object.DestroyImmediate(sessionObject);
            }
        }

        /// <summary>通过反射读取测试所需的私有字段。</summary>
        private static object GetPrivateField(object target, string fieldName)
        {
            FieldInfo field = target.GetType().GetField(fieldName, BindingFlags.Instance | BindingFlags.NonPublic);
            Assert.That(field, Is.Not.Null, $"missing private field {fieldName}");
            return field.GetValue(target);
        }

        /// <summary>通过反射设置测试所需的私有录制状态，不扩大生产 API。</summary>
        private static void SetPrivateField(object target, string fieldName, object value)
        {
            FieldInfo field = target.GetType().GetField(fieldName, BindingFlags.Instance | BindingFlags.NonPublic);
            Assert.That(field, Is.Not.Null, $"missing private field {fieldName}");
            field.SetValue(target, value);
        }
    }

    /// <summary>正式实验一/二场景和 policy capability 的契约测试。</summary>
    public sealed class ExperimentSceneContractTests
    {
        /// <summary>正式场景中必须出现的九个唯一 runtime 标签。</summary>
        private static readonly string[] RequiredLabels =
        {
            "Arrival-Hold",
            "Capture-Hold",
            "One-Euro Anchor",
            "EgoAnchor",
            "EgoAnchor Linear/SLERP",
            "EgoAnchor w/o capture-time alignment",
            "EgoAnchor w/o VCD",
            "EgoAnchor w/o temporal synthesis",
            "EgoAnchor w/o StaticLock",
        };

        /// <summary>capability flags 必须反映实际绑定组件和生命周期开关。</summary>
        [Test]
        public void PolicyFlagsReflectConfiguredComponents()
        {
            GameObject owner = new GameObject("ExperimentSceneContractTests.Policy");
            try
            {
                KalmanModel model = owner.AddComponent<KalmanModel>();
                HermiteStrategy smoothing = owner.AddComponent<HermiteStrategy>();
                EgoAnchorStaticLockModule staticLock = owner.AddComponent<EgoAnchorStaticLockModule>();
                AnchorPolicyHost host = owner.AddComponent<AnchorPolicyHost>();
                SetPrivateField(host, "motionModel", model);
                SetPrivateField(host, "smoothingStrategy", smoothing);
                SetPrivateField(host, "staticLockModule", staticLock);
                SetPrivateField(host, "enableQualityGate", true);

                Assert.That(host.UsesVcdAdmission, Is.True);
                Assert.That(host.UsesTemporalSynthesis, Is.True);
                Assert.That(host.UsesStaticLock, Is.True);
                Assert.That(host.UsesLowScoreReacquire, Is.True);
                Assert.That(host.UsesServerReacquire, Is.True);
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(owner);
            }
        }

        /// <summary>YAML 必须包含真实、启用且由 Hub 注册的全部 runtime。</summary>
        [Test]
        public void ExperimentSceneContainsConfiguredRuntimeGraph()
        {
            string path = Path.Combine(Application.dataPath, "Scene", "EgoAnchor-Experiment12.unity");
            Assert.That(File.Exists(path), Is.True, $"missing scene: {path}");
            string yaml = File.ReadAllText(path);

            StringAssert.DoesNotContain("EgoAnchor-RQ1", yaml);
            StringAssert.DoesNotContain("EgoAnchor-RQ2", yaml);
            StringAssert.DoesNotContain("EvalHotkeys", yaml);
            Assert.That(
                Regex.Matches(yaml, "m_EditorClassIdentifier: EgoAnchor::EgoAnchor.Runtime.PoseToAnchorRuntime").Count,
                Is.EqualTo(RequiredLabels.Length));

            var runtimeIds = new Dictionary<string, string>(StringComparer.Ordinal);
            MatchCollection variantMatches = Regex.Matches(
                yaml,
                @"(?m)^  - label: (?<label>[^\r\n]+)\r?\n    runtime: \{fileID: (?<id>\d+)\}");
            foreach (Match match in variantMatches)
            {
                runtimeIds[match.Groups["label"].Value] = match.Groups["id"].Value;
            }

            string hubSection = GetSectionContaining(
                yaml,
                "m_EditorClassIdentifier: EgoAnchor::EgoAnchor.Runtime.AnchorRuntimeHub");
            var distinctRuntimeIds = new HashSet<string>(StringComparer.Ordinal);
            foreach (string label in RequiredLabels)
            {
                Assert.That(runtimeIds.TryGetValue(label, out string runtimeId), Is.True, $"missing variant: {label}");
                Assert.That(distinctRuntimeIds.Add(runtimeId), Is.True, $"duplicate runtime: {runtimeId}");

                string runtimeSection = GetSection(yaml, runtimeId);
                StringAssert.Contains("EgoAnchor.Runtime.PoseToAnchorRuntime", runtimeSection);
                StringAssert.Contains($"- {{fileID: {runtimeId}}}", hubSection);

                string gameObjectId = ReadReference(runtimeSection, "m_GameObject");
                StringAssert.Contains("m_IsActive: 1", GetSection(yaml, gameObjectId));

                string policyId = ReadReference(runtimeSection, "policyHost");
                string policySection = GetSection(yaml, policyId);
                int expectedEmit = IsShadowBaseline(label) ? 0 : 1;
                StringAssert.Contains($"emitServerReacquire: {expectedEmit}", policySection);
            }

            Assert.That(distinctRuntimeIds.Count, Is.EqualTo(RequiredLabels.Length));
        }

        /// <summary>正式场景只允许 Formal，并序列化可在 Inspector 编辑的内联 InputAction。</summary>
        [Test]
        public void ExperimentSceneUsesFormalInlineInputActions()
        {
            string path = Path.Combine(Application.dataPath, "Scene", "EgoAnchor-Experiment12.unity");
            string yaml = File.ReadAllText(path);
            string sessionSection = GetSectionContaining(
                yaml, "m_EditorClassIdentifier: EgoAnchor::EgoAnchor.Eval.EvalSession");
            string inputSection = GetSectionContaining(
                yaml, "m_EditorClassIdentifier: EgoAnchor::EgoAnchor.Eval.Experiment.ExperimentInputHandler");

            foreach (string removedField in new[]
            {
                "runKind:",
                "runMode:",
                "operatorId:",
                "frozenParameterSetId:",
                "objectModelId:",
                "egoanchorGitCommit:",
                "protocolVersion:",
                "notes:",
            })
                StringAssert.DoesNotContain(removedField, sessionSection);
            StringAssert.Contains("autoStart: 0", sessionSection);

            StringAssert.DoesNotContain("controllerBinding:", inputSection);
            StringAssert.DoesNotContain("keyboardBinding:", inputSection);
            foreach (string actionField in new[]
            {
                "navigateAction:", "startAction:", "markAction:", "stopAction:",
                "finishAction:", "rejectAction:", "taskActions:"
            })
                StringAssert.Contains(actionField, inputSection);
            foreach (string bindingPath in new[]
            {
                "<XRController>{RightHand}/primary2DAxis",
                "<XRController>{RightHand}/primaryButton",
                "<XRController>{RightHand}/triggerPressed",
                "<XRController>{RightHand}/secondaryButton",
                "<XRController>{RightHand}/thumbstickClicked",
                "<Keyboard>/upArrow",
                "<Keyboard>/downArrow",
                "<Keyboard>/leftArrow",
                "<Keyboard>/rightArrow",
                "<Keyboard>/enter",
                "<Keyboard>/numpadEnter",
                "<Keyboard>/m",
                "<Keyboard>/numpadPlus",
                "<Keyboard>/e",
                "<Keyboard>/numpad0",
                "<Keyboard>/f",
                "<Keyboard>/space",
            })
                StringAssert.Contains($"m_Path: {bindingPath}", inputSection);
            StringAssert.DoesNotContain("<Keyboard>/backspace", inputSection);
            StringAssert.DoesNotContain("enforceMinimumDuration:", yaml);
            AssertUnifiedActionBindings(inputSection);
            AssertKeyboardTaskBindings(inputSection);
            Assert.That(
                Regex.Matches(inputSection, @"(?m)^  - m_Name: Task[1-5]\r?$").Count,
                Is.EqualTo(ExperimentScenario.PlanCount));

            MatchCollection ids = Regex.Matches(inputSection, @"(?m)^\s+m_Id: (?<id>[^\r\n]+)$");
            var distinctIds = new HashSet<string>(StringComparer.Ordinal);
            foreach (Match match in ids)
                Assert.That(distinctIds.Add(match.Groups["id"].Value), Is.True, "InputAction GUID 必须唯一");
            Assert.That(distinctIds.Count, Is.GreaterThanOrEqualTo(20));

            string canvasTransform = ReadFirstComponentReference(GetSectionContaining(yaml, "m_Name: Canvas"));
            StringAssert.Contains("m_Father: {fileID: 0}", GetSection(yaml, canvasTransform));
        }

        /// <summary>工程开发场景复用正式输入，但不再产生另一类评估 session。</summary>
        [Test]
        public void DevelopmentSceneUsesInlineInputActions()
        {
            string path = Path.Combine(Application.dataPath, "Scene", "EgoAnchor-Develop.unity");
            string yaml = File.ReadAllText(path);
            string sessionSection = GetSectionContaining(
                yaml, "m_EditorClassIdentifier: EgoAnchor::EgoAnchor.Eval.EvalSession");
            string inputSection = GetSectionContaining(
                yaml, "m_EditorClassIdentifier: EgoAnchor::EgoAnchor.Eval.Experiment.ExperimentInputHandler");

            StringAssert.DoesNotContain("runKind:", sessionSection);
            StringAssert.Contains("autoStart: 0", sessionSection);
            StringAssert.DoesNotContain("controlSessionShortcuts:", inputSection);
            StringAssert.DoesNotContain("controllerBinding:", inputSection);
            StringAssert.Contains("navigateAction:", inputSection);
            StringAssert.Contains("taskActions:", inputSection);
            StringAssert.Contains("m_Path: <XRController>{RightHand}/primaryButton", inputSection);
            StringAssert.Contains("m_Path: <Keyboard>/numpadEnter", inputSection);
            StringAssert.Contains("m_Path: <Keyboard>/f", inputSection);
            StringAssert.Contains("m_Path: <Keyboard>/space", inputSection);
            StringAssert.DoesNotContain("<Keyboard>/backspace", inputSection);
            StringAssert.DoesNotContain("enforceMinimumDuration:", yaml);
            AssertUnifiedActionBindings(inputSection);
            AssertKeyboardTaskBindings(inputSection);
            Assert.That(
                Regex.Matches(inputSection, @"(?m)^  - m_Name: Task[1-5]\r?$").Count,
                Is.EqualTo(ExperimentScenario.PlanCount));

            string canvasTransform = ReadFirstComponentReference(GetSectionContaining(yaml, "m_Name: Canvas"));
            StringAssert.Contains("m_Father: {fileID: 0}", GetSection(yaml, canvasTransform));
        }

        /// <summary>采集场景首次连接 NATS 失败后必须持续重试，避免依赖 Python 的启动顺序。</summary>
        [Test]
        public void CollectionScenesRetryInitialNatsConnection()
        {
            foreach (string sceneName in new[] { "EgoAnchor-Experiment12.unity", "EgoAnchor-Develop.unity" })
            {
                string path = Path.Combine(Application.dataPath, "Scene", sceneName);
                string yaml = File.ReadAllText(path);
                string natsSection = GetSectionContaining(
                    yaml,
                    "m_EditorClassIdentifier: EgoAnchor::EgoAnchor.Client.NatsControlClient");

                StringAssert.Contains("retryOnInitialConnect: 1", natsSection, sceneName);
            }
        }

        /// <summary>两个采集场景都必须使用静止根 Canvas 下互不重叠的任务板和实时诊断板。</summary>
        [Test]
        public void CollectionScenesContainWiredLiveMetricsPanel()
        {
            foreach (string sceneName in new[] { "EgoAnchor-Experiment12.unity", "EgoAnchor-Develop.unity" })
            {
                string path = Path.Combine(Application.dataPath, "Scene", sceneName);
                string yaml = File.ReadAllText(path);
                Assert.That(
                    Regex.Matches(yaml, "m_EditorClassIdentifier: EgoAnchor::EgoAnchor.Eval.EvalLiveStats").Count,
                    Is.EqualTo(1),
                    sceneName);

                string canvasSection = GetSectionContaining(yaml, "m_Name: Canvas");
                string canvasTransformId = ReadFirstComponentReference(canvasSection);
                string canvasTransform = GetSection(yaml, canvasTransformId);
                StringAssert.Contains("m_Father: {fileID: 0}", canvasTransform, sceneName);

                string statusPanel = GetSectionContaining(yaml, "m_Name: ExperimentStatusPanel");
                string statusRect = GetSection(yaml, ReadFirstComponentReference(statusPanel));
                StringAssert.Contains($"m_Father: {{fileID: {canvasTransformId}}}", statusRect, sceneName);

                string livePanel = GetSectionContaining(yaml, "m_Name: LiveMetricsPanel");
                string liveRect = GetSection(yaml, ReadFirstComponentReference(livePanel));
                StringAssert.Contains($"m_Father: {{fileID: {canvasTransformId}}}", liveRect, sceneName);

                bool centeredColumns =
                    statusRect.Contains("m_AnchoredPosition: {x: -450, y: 0}")
                    && statusRect.Contains("m_SizeDelta: {x: 900, y: 650}")
                    && statusRect.Contains("m_Pivot: {x: 0.5, y: 0.5}")
                    && liveRect.Contains("m_AnchoredPosition: {x: 470, y: 0}")
                    && liveRect.Contains("m_SizeDelta: {x: 720, y: 650}")
                    && liveRect.Contains("m_Pivot: {x: 0.5, y: 0.5}");
                bool edgeColumns =
                    statusRect.Contains("m_AnchorMin: {x: 0, y: 0}")
                    && statusRect.Contains("m_AnchorMax: {x: 0, y: 1}")
                    && statusRect.Contains("m_AnchoredPosition: {x: 0, y: 0}")
                    && statusRect.Contains("m_SizeDelta: {x: 800, y: 0}")
                    && statusRect.Contains("m_Pivot: {x: 0, y: 0.5}")
                    && liveRect.Contains("m_AnchorMin: {x: 1, y: 0}")
                    && liveRect.Contains("m_AnchorMax: {x: 1, y: 1}")
                    && liveRect.Contains("m_AnchoredPosition: {x: 0, y: 0}")
                    && liveRect.Contains("m_SizeDelta: {x: 500, y: 0}")
                    && liveRect.Contains("m_Pivot: {x: 1, y: 0.5}");
                Assert.That(
                    centeredColumns || edgeColumns,
                    Is.True,
                    $"{sceneName} 的两个同级面板必须使用已验证的无重叠布局。");

                string stats = GetSectionContaining(
                    yaml,
                    "m_EditorClassIdentifier: EgoAnchor::EgoAnchor.Eval.EvalLiveStats");
                string recorderId = ReadReference(stats, "recorder");
                string statsTextId = ReadReference(stats, "statsText");
                Assert.That(recorderId, Is.Not.EqualTo("0"), sceneName);
                Assert.That(statsTextId, Is.Not.EqualTo("0"), sceneName);

                string statsText = GetSection(yaml, statsTextId);
                string statsTextObject = GetSection(yaml, ReadReference(statsText, "m_GameObject"));
                StringAssert.Contains("m_Name: LiveMetricsText", statsTextObject, sceneName);

                string publisher = GetSectionContaining(
                    yaml,
                    "m_EditorClassIdentifier: EgoAnchor::EgoAnchor.Client.QuestStreamPublisher");
                StringAssert.Contains("pauseWhenVrFocusLost: 1", publisher, sceneName);
            }
        }

        /// <summary>两个采集场景都必须绑定平台参考 Transform，且不得恢复限时 freshness 策略。</summary>
        [Test]
        public void CollectionScenesUseTransformReferenceWithoutTimedFreshnessPolicy()
        {
            foreach (string sceneName in new[] { "EgoAnchor-Experiment12.unity", "EgoAnchor-Develop.unity" })
            {
                string path = Path.Combine(Application.dataPath, "Scene", sceneName);
                string yaml = File.ReadAllText(path);
                string recorder = GetSectionContaining(
                    yaml,
                    "m_EditorClassIdentifier: EgoAnchor::EgoAnchor.Eval.EvalRecorder");

                string groundTruthId = ReadReference(recorder, "groundTruth");
                Assert.That(groundTruthId, Is.Not.EqualTo("0"), sceneName);
                string groundTruth = GetSection(yaml, groundTruthId);
                StringAssert.Contains(
                    "m_CorrespondingSourceObject: {fileID: 1168042862848623612, " +
                    "guid: 0a7d2469f24041c4284c66706f84c45e, type: 3}",
                    groundTruth,
                    sceneName);
                StringAssert.Contains("gtController: 2", recorder, sceneName);
                StringAssert.DoesNotContain("gtFreshnessMode:", recorder, sceneName);
                StringAssert.DoesNotContain("gtKeepAliveSeconds:", recorder, sceneName);
            }
        }

        /// <summary>每个任务必须同时绑定数字行与小键盘，并且路径能被当前 Input System 解析。</summary>
        private static void AssertKeyboardTaskBindings(string inputSection)
        {
            StringAssert.DoesNotContain("<Keyboard>/digit", inputSection);
            for (int taskNumber = 1; taskNumber <= ExperimentScenario.PlanCount; taskNumber++)
            {
                Match task = Regex.Match(
                    inputSection,
                    $@"(?ms)^  - m_Name: Task{taskNumber}\r?\n(?<body>.*?)(?=^  - m_Name: Task|\r?\n  navigationThreshold:)"
                );
                Assert.That(task.Success, Is.True, $"missing Task{taskNumber} action");

                string[] expectedPaths =
                {
                    $"<Keyboard>/{taskNumber}",
                    $"<Keyboard>/numpad{taskNumber}",
                };
                foreach (string path in expectedPaths)
                {
                    StringAssert.Contains($"m_Path: {path}", task.Groups["body"].Value);
                    using (var action = new InputAction(type: InputActionType.Button, binding: path))
                    {
                        action.Enable();
                        Assert.That(action.controls, Is.Not.Empty, $"unresolved Input System path: {path}");
                    }
                }
            }
        }

        /// <summary>键盘必须复用手柄动作语义，并验证主 Enter 与小键盘 Enter 均可解析。</summary>
        private static void AssertUnifiedActionBindings(string inputSection)
        {
            string navigate = ReadInlineAction(inputSection, "navigateAction", "startAction");
            string start = ReadInlineAction(inputSection, "startAction", "markAction");
            string mark = ReadInlineAction(inputSection, "markAction", "stopAction");
            string stop = ReadInlineAction(inputSection, "stopAction", "finishAction");
            string finish = ReadInlineAction(inputSection, "finishAction", "rejectAction");
            string reject = ReadInlineAction(inputSection, "rejectAction", "taskActions");

            foreach (string path in new[]
            {
                "<Keyboard>/upArrow", "<Keyboard>/downArrow",
                "<Keyboard>/leftArrow", "<Keyboard>/rightArrow",
            })
                StringAssert.Contains($"m_Path: {path}", navigate);
            foreach (string path in new[] { "<Keyboard>/enter", "<Keyboard>/numpadEnter" })
                StringAssert.Contains($"m_Path: {path}", start);
            StringAssert.Contains("m_Path: <Keyboard>/m", mark);
            StringAssert.Contains("m_Path: <Keyboard>/numpadPlus", mark);
            StringAssert.Contains("m_Path: <Keyboard>/e", stop);
            StringAssert.Contains("m_Path: <Keyboard>/numpad0", stop);
            StringAssert.Contains("m_Interactions: Tap(duration=0.5)", stop);
            StringAssert.Contains("m_Path: <Keyboard>/f", finish);
            StringAssert.Contains("m_Interactions: Hold(duration=1.5)", finish);
            StringAssert.Contains("m_Path: <Keyboard>/space", reject);

            foreach (string path in new[]
            {
                "<Keyboard>/upArrow", "<Keyboard>/downArrow",
                "<Keyboard>/leftArrow", "<Keyboard>/rightArrow",
                "<Keyboard>/enter", "<Keyboard>/numpadEnter",
                "<Keyboard>/m", "<Keyboard>/numpadPlus",
                "<Keyboard>/e", "<Keyboard>/numpad0",
                "<Keyboard>/f", "<Keyboard>/space",
            })
            {
                using (var action = new InputAction(type: InputActionType.Button, binding: path))
                {
                    action.Enable();
                    Assert.That(action.controls, Is.Not.Empty, $"unresolved Input System path: {path}");
                }
            }
        }

        /// <summary>从场景 YAML 中读取一个内联 InputAction 段。</summary>
        private static string ReadInlineAction(string inputSection, string field, string nextField)
        {
            Match match = Regex.Match(
                inputSection,
                $@"(?ms)^  {Regex.Escape(field)}:\r?\n(?<body>.*?)(?=^  {Regex.Escape(nextField)}:)"
            );
            Assert.That(match.Success, Is.True, $"missing inline action: {field}");
            return match.Groups["body"].Value;
        }

        /// <summary>各配置只能按实验定义切换目标组件，避免消融同时改变无关机制。</summary>
        [Test]
        public void ExperimentSceneVariantsMatchFrozenComponentMatrix()
        {
            string path = Path.Combine(Application.dataPath, "Scene", "EgoAnchor-Experiment12.unity");
            string yaml = File.ReadAllText(path);

            AssertVariantConfig(yaml, "Arrival-Hold", 1, 0, "ConstantVelocityModel", "HoldStrategy", false, 0, 0);
            AssertVariantConfig(yaml, "Capture-Hold", 0, 0, "ConstantVelocityModel", "HoldStrategy", false, 0, 0);
            AssertVariantConfig(yaml, "One-Euro Anchor", 0, 1, "OneEuroModel", "LinearSlerpStrategy", false, 1, 1);
            AssertVariantConfig(yaml, "EgoAnchor", 0, 1, "KalmanModel", "HermiteStrategy", true, 1, 1);
            AssertVariantConfig(yaml, "EgoAnchor Linear/SLERP", 0, 1, "KalmanModel", "LinearSlerpStrategy", true, 1, 1);
            AssertVariantConfig(yaml, "EgoAnchor w/o capture-time alignment", 1, 1, "KalmanModel", "HermiteStrategy", true, 1, 1);
            AssertVariantConfig(yaml, "EgoAnchor w/o VCD", 0, 0, "KalmanModel", "HermiteStrategy", true, 0, 1);
            AssertVariantConfig(yaml, "EgoAnchor w/o temporal synthesis", 0, 1, "KalmanModel", "PredictToNowStrategy", true, 1, 1);
            AssertVariantConfig(yaml, "EgoAnchor w/o StaticLock", 0, 1, "KalmanModel", "HermiteStrategy", false, 1, 1);
        }

        /// <summary>Hub 层级必须按实验一与实验二分组，完整 EgoAnchor 只保留一个共享 runtime。</summary>
        [Test]
        public void ExperimentSceneHierarchySeparatesExperimentGroups()
        {
            string path = Path.Combine(Application.dataPath, "Scene", "EgoAnchor-Experiment12.unity");
            string yaml = File.ReadAllText(path);

            string experiment1Transform = ReadFirstComponentReference(GetSectionContaining(
                yaml, "m_Name: Experiment 1 - System Characterization"));
            string experiment2Transform = ReadFirstComponentReference(GetSectionContaining(
                yaml, "m_Name: Experiment 2 - Design Attribution"));
            string experiment1Section = GetSection(yaml, experiment1Transform);
            string experiment2Section = GetSection(yaml, experiment2Transform);

            AssertVariantParent(yaml, "Arrival-Hold", experiment1Transform, experiment1Section);
            AssertVariantParent(yaml, "Capture-Hold", experiment1Transform, experiment1Section);
            AssertVariantParent(yaml, "One-Euro Anchor", experiment1Transform, experiment1Section);
            AssertVariantParent(yaml, "EgoAnchor", experiment1Transform, experiment1Section);
            AssertVariantParent(yaml, "EgoAnchor Linear/SLERP", experiment2Transform, experiment2Section);
            AssertVariantParent(yaml, "EgoAnchor w/o capture-time alignment", experiment2Transform, experiment2Section);
            AssertVariantParent(yaml, "EgoAnchor w/o VCD", experiment2Transform, experiment2Section);
            AssertVariantParent(yaml, "EgoAnchor w/o temporal synthesis", experiment2Transform, experiment2Section);
            AssertVariantParent(yaml, "EgoAnchor w/o StaticLock", experiment2Transform, experiment2Section);

            StringAssert.Contains("AnchorObject - EgoAnchor [Shared Full System]", yaml);
            string hubTransform = ReadFirstComponentReference(GetSectionContaining(yaml, "m_Name: AnchorRuntimeHub"));
            string hubSection = GetSection(yaml, hubTransform);
            Assert.That(Regex.Matches(hubSection, @"(?m)^  - \{fileID: \d+\}$").Count, Is.EqualTo(2));
            StringAssert.Contains($"- {{fileID: {experiment1Transform}}}", hubSection);
            StringAssert.Contains($"- {{fileID: {experiment2Transform}}}", hubSection);
        }

        /// <summary>验证一条 recorder 变体引用的 runtime 与 policy 组件矩阵。</summary>
        private static void AssertVariantConfig(
            string yaml,
            string label,
            int worldAlignmentMode,
            int qualityGate,
            string motionModel,
            string smoothingStrategy,
            bool usesStaticLock,
            int lowScoreReacquire,
            int serverReacquire)
        {
            Match variant = Regex.Match(
                yaml,
                $@"(?m)^  - label: {Regex.Escape(label)}\r?\n    runtime: \{{fileID: (?<id>\d+)\}}");
            Assert.That(variant.Success, Is.True, $"missing variant: {label}");

            string runtimeSection = GetSection(yaml, variant.Groups["id"].Value);
            StringAssert.Contains($"worldAlignmentMode: {worldAlignmentMode}", runtimeSection);

            string policySection = GetSection(yaml, ReadReference(runtimeSection, "policyHost"));
            StringAssert.Contains($"enableQualityGate: {qualityGate}", policySection);
            StringAssert.Contains($"enableLowScoreReacquire: {lowScoreReacquire}", policySection);
            StringAssert.Contains($"emitServerReacquire: {serverReacquire}", policySection);

            string modelSection = GetSection(yaml, ReadReference(policySection, "motionModel"));
            string smoothingSection = GetSection(yaml, ReadReference(policySection, "smoothingStrategy"));
            StringAssert.Contains($"EgoAnchor.Policy.{motionModel}", modelSection);
            StringAssert.Contains($"EgoAnchor.Policy.{smoothingStrategy}", smoothingSection);

            string staticLockId = ReadReference(policySection, "staticLockModule");
            if (usesStaticLock)
            {
                StringAssert.Contains("EgoAnchor.Policy.EgoAnchorStaticLockModule", GetSection(yaml, staticLockId));
            }
            else
            {
                Assert.That(staticLockId, Is.EqualTo("0"));
            }
        }

        /// <summary>验证一个 recorder 变体对应的锚点对象直接属于指定实验分组。</summary>
        private static void AssertVariantParent(
            string yaml,
            string label,
            string expectedParentTransform,
            string parentSection)
        {
            Match variant = Regex.Match(
                yaml,
                $@"(?m)^  - label: {Regex.Escape(label)}\r?\n    runtime: \{{fileID: (?<id>\d+)\}}");
            Assert.That(variant.Success, Is.True, $"missing variant: {label}");
            string runtimeSection = GetSection(yaml, variant.Groups["id"].Value);
            string gameObjectSection = GetSection(yaml, ReadReference(runtimeSection, "m_GameObject"));
            string anchorTransform = ReadFirstComponentReference(gameObjectSection);
            StringAssert.Contains($"m_Father: {{fileID: {expectedParentTransform}}}", GetSection(yaml, anchorTransform));
            StringAssert.Contains($"- {{fileID: {anchorTransform}}}", parentSection);
        }

        /// <summary>只有直接消费候选的 Hold 基线不得请求共享 Python pipeline 重获取。</summary>
        private static bool IsShadowBaseline(string label)
        {
            return label == "Arrival-Hold" || label == "Capture-Hold";
        }

        /// <summary>读取包含指定标记的完整 Unity YAML 对象段。</summary>
        private static string GetSectionContaining(string yaml, string marker)
        {
            int markerIndex = yaml.IndexOf(marker, StringComparison.Ordinal);
            Assert.That(markerIndex, Is.GreaterThanOrEqualTo(0), $"missing marker: {marker}");
            int start = yaml.LastIndexOf("\n--- !u!", markerIndex, StringComparison.Ordinal);
            start = start < 0 ? 0 : start + 1;
            int end = yaml.IndexOf("\n--- !u!", markerIndex, StringComparison.Ordinal);
            return yaml.Substring(start, end < 0 ? yaml.Length - start : end - start);
        }

        /// <summary>按 fileID 读取完整 Unity YAML 对象段。</summary>
        private static string GetSection(string yaml, string fileId)
        {
            Match header = Regex.Match(
                yaml,
                $@"(?m)^--- !u!\d+ &{Regex.Escape(fileId)}(?: stripped)?\r?$");
            Assert.That(header.Success, Is.True, $"missing Unity YAML object: {fileId}");
            int end = yaml.IndexOf("\n--- !u!", header.Index + header.Length, StringComparison.Ordinal);
            return yaml.Substring(
                header.Index,
                end < 0 ? yaml.Length - header.Index : end - header.Index);
        }

        /// <summary>读取 YAML 对象段中的本地 fileID 引用。</summary>
        private static string ReadReference(string section, string field)
        {
            Match match = Regex.Match(section, $@"(?m)^  {Regex.Escape(field)}: \{{fileID: (?<id>\d+)\}}");
            Assert.That(match.Success, Is.True, $"missing reference: {field}");
            return match.Groups["id"].Value;
        }

        /// <summary>读取 GameObject 的第一个组件引用；Unity 保证该组件为 Transform。</summary>
        private static string ReadFirstComponentReference(string gameObjectSection)
        {
            Match match = Regex.Match(gameObjectSection, @"(?m)^  - component: \{fileID: (?<id>\d+)\}");
            Assert.That(match.Success, Is.True, "missing GameObject component reference");
            return match.Groups["id"].Value;
        }

        /// <summary>设置测试所需的私有序列化字段。</summary>
        private static void SetPrivateField(object target, string fieldName, object value)
        {
            FieldInfo field = target.GetType().GetField(fieldName, BindingFlags.Instance | BindingFlags.NonPublic);
            Assert.That(field, Is.Not.Null, $"missing private field {fieldName}");
            field.SetValue(target, value);
        }
    }
}

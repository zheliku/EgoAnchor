using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;
using EgoAnchor.Eval;
using EgoAnchor.Eval.Experiment;
using EgoAnchor.Policy;
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
            Assert.That(EvalStatusText.Recording(true), Is.EqualTo("● Recording"));
            Assert.That(EvalStatusText.Recording(false), Is.EqualTo("○ Not Recording"));
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
                "enabled", "kalman", "interp_hermite", true, true, "cfg"));
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
                    "s01", "controller_right", "smoke", "operator-01", 2000,
                    "editor_link", string.Empty, "6000.3.11f1", string.Empty,
                    "commit", "v1", string.Empty, "controller-mesh-v1", string.Empty),
                new[] { "EgoAnchor" },
                new[]
                {
                    new EvalVariantConfig(
                        "EgoAnchor", "kalman", "interp_hermite", "enabled", "cfg",
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
            StringAssert.Contains("\"run_kind\":\"smoke\"", manifest);
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
                "variant_definitions", "completed_tasks", "trial_plan", "log_files", "log_writer_stats",
            })
                StringAssert.Contains($"\"{field}\":", manifest);
            StringAssert.Contains(
                "\"completed_tasks\":[{\"task_number\":1,\"experiment_id\":\"exp1_system_characterization\",\"scenario_id\":\"static_head_motion\",\"trial_id\":\"trial_001\"},{\"task_number\":3",
                manifest);
            StringAssert.Contains("\"scenario_id\":\"occlusion_recovery\"", manifest);
            StringAssert.Contains("\"scenario_id\":\"without_static_lock\"", manifest);
            StringAssert.Contains("\"minimum_seconds\":90", manifest);
            StringAssert.Contains("\"maximum_seconds\":120", manifest);
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
        /// <summary>未录制时不得选择、开始或标记 trial。</summary>
        [Test]
        public void SelectorRejectsChangesBeforeRecording()
        {
            WithSelector((_, selector) =>
            {
                Assert.That(selector.SelectTask(0), Is.False);
                Assert.That(selector.StartTrial(), Is.False);
                Assert.That(selector.MarkEvent(), Is.False);
                Assert.That(selector.CurrentContext.IsSelected, Is.False);
            }, recording: false);
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
                Assert.That(selector.StopOrFinish(), Is.True);

                Assert.That(selector.HasActiveTrial, Is.False);
                Assert.That(selector.SelectedTaskIndex, Is.EqualTo(1));
                Assert.That(selector.IsTaskCompleted(1), Is.True);
                Assert.That(selector.CompletedTaskCount, Is.EqualTo(1));
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
                Assert.That(selector.StopOrFinish(), Is.False);

                Assert.That(selector.MarkEvent(), Is.True);
                Assert.That(selector.CurrentEventRole, Is.EqualTo(ExperimentEventRole.TargetVisible));
                Assert.That(selector.HasOpenOcclusion, Is.False);
                Assert.That(selector.MarkEvent(), Is.True);
                Assert.That(selector.CurrentEventRole, Is.EqualTo(ExperimentEventRole.OcclusionStarted));
                Assert.That(selector.MarkEvent(), Is.True);
                Assert.That(selector.CurrentEventRole, Is.EqualTo(ExperimentEventRole.TargetVisible));
                Assert.That(selector.StopOrFinish(), Is.True);
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
                Assert.That(selector.IsTaskCompleted(0), Is.True);
                Assert.That(selector.RejectCurrentOrSelected(), Is.True);
                Assert.That(selector.IsTaskCompleted(0), Is.False);
                CollectionAssert.Contains(eventTypes, "trial_rejected");

                selector.SelectTask(1);
                selector.StartTrial();
                Assert.That(selector.RejectCurrentOrSelected(), Is.True);
                Assert.That(selector.HasActiveTrial, Is.False);
                Assert.That(selector.IsTaskCompleted(1), Is.False);
                Assert.That(eventTypes.FindAll(item => item == "trial_rejected").Count, Is.EqualTo(2));
            });
        }

        /// <summary>完成任意任务子集后必须等待额外确认，再结束模块化 session。</summary>
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
                Assert.That(selector.StopOrFinish(), Is.True);
                Assert.That(session.IsRecording, Is.False);
            });
        }

        /// <summary>零项完成时不得生成空的正式 session。</summary>
        [Test]
        public void SelectorRejectsEmptySessionFinish()
        {
            WithSelector((session, selector) =>
            {
                Assert.That(selector.CanFinishSession, Is.False);
                Assert.That(selector.StopOrFinish(), Is.False);
                Assert.That(session.IsRecording, Is.True);
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

        /// <summary>输入组件必须暴露内联 InputAction，键盘任务键复用对应任务状态机。</summary>
        [Test]
        public void InputHandlerUsesInlineActionsAndTaskKeys()
        {
            WithSelector((_, selector) =>
            {
                GameObject inputObject = new GameObject("ExperimentContextTests.Input");
                try
                {
                    ExperimentInputHandler input = inputObject.AddComponent<ExperimentInputHandler>();
                    SetPrivateField(input, "selector", selector);

                    Assert.That(input.HandleTask(2), Is.True);
                    Assert.That(selector.SelectedTaskIndex, Is.EqualTo(2));
                    Assert.That(selector.HasActiveTrial, Is.True);
                    Assert.That(input.HandleTask(2), Is.True);
                    Assert.That(selector.CurrentEventRole, Is.EqualTo(ExperimentEventRole.GenericMarker));
                    Assert.That(input.HandleStop(), Is.True);
                    Assert.That(selector.IsTaskCompleted(2), Is.True);

                    foreach (string fieldName in new[]
                    {
                        "navigateAction", "startAction", "markAction", "stopAction", "rejectAction"
                    })
                        Assert.That(GetPrivateField(input, fieldName), Is.TypeOf<InputAction>());
                    Assert.That(GetPrivateField(input, "taskActions"), Is.TypeOf<InputAction[]>());
                    Assert.That(((InputAction[])GetPrivateField(input, "taskActions")).Length, Is.EqualTo(9));
                    Assert.That(input.GetType().GetField("controllerBinding", BindingFlags.Instance | BindingFlags.NonPublic), Is.Null);
                    Assert.That(input.GetType().GetField("keyboardBinding", BindingFlags.Instance | BindingFlags.NonPublic), Is.Null);
                }
                finally
                {
                    UnityEngine.Object.DestroyImmediate(inputObject);
                }
            });
        }

        /// <summary>UI 必须同时显示九任务状态、选中项、当前阶段与 90--120 秒时长。</summary>
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

                    StringAssert.Contains("Completed: 1 / 9", text);
                    StringAssert.Contains("This session: 1", text);
                    StringAssert.Contains("[OK]1 HEAD", text);
                    StringAssert.Contains(">[RUN]5 OCC", text);
                    StringAssert.Contains("Occlusion recovery", text);
                    StringAssert.Contains("Phase: OCCLUDED", text);
                    StringAssert.Contains("Recommended: 90-120 s", text);
                    StringAssert.DoesNotContain("RQ1", text);
                    StringAssert.DoesNotContain("RQ2", text);
                }
                finally
                {
                    UnityEngine.Object.DestroyImmediate(uiObject);
                }
            });
        }

        /// <summary>完成一个指定任务，遮挡任务自动补齐 target_visible。</summary>
        private static void CompleteTask(ExperimentTrialSelector selector, int index)
        {
            Assert.That(selector.SelectTask(index), Is.True);
            Assert.That(selector.StartTrial(), Is.True);
            Assert.That(selector.MarkEvent(), Is.True);
            if (selector.HasOpenOcclusion)
                Assert.That(selector.MarkEvent(), Is.True);
            Assert.That(selector.StopOrFinish(), Is.True);
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
        /// <summary>正式场景中必须出现的八个唯一 runtime 标签。</summary>
        private static readonly string[] RequiredLabels =
        {
            "Arrival-Hold",
            "Capture-Hold",
            "One-Euro Anchor",
            "EgoAnchor",
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
                DelayedInterpStrategy smoothing = owner.AddComponent<DelayedInterpStrategy>();
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

        /// <summary>正式场景必须固定 Formal，并序列化可在 Inspector 编辑的内联 InputAction。</summary>
        [Test]
        public void ExperimentSceneUsesFormalInlineInputActions()
        {
            string path = Path.Combine(Application.dataPath, "Scene", "EgoAnchor-Experiment12.unity");
            string yaml = File.ReadAllText(path);
            string sessionSection = GetSectionContaining(
                yaml, "m_EditorClassIdentifier: EgoAnchor::EgoAnchor.Eval.EvalSession");
            string inputSection = GetSectionContaining(
                yaml, "m_EditorClassIdentifier: EgoAnchor::EgoAnchor.Eval.Experiment.ExperimentInputHandler");

            StringAssert.Contains("runKind: 3", sessionSection);
            foreach (string removedField in new[]
            {
                "runMode:",
                "operatorId:",
                "frozenParameterSetId:",
                "objectModelId:",
                "egoanchorGitCommit:",
                "protocolVersion:",
                "notes:",
            })
                StringAssert.DoesNotContain(removedField, sessionSection);

            StringAssert.DoesNotContain("controllerBinding:", inputSection);
            StringAssert.DoesNotContain("keyboardBinding:", inputSection);
            foreach (string actionField in new[]
            {
                "navigateAction:", "startAction:", "markAction:", "stopAction:",
                "rejectAction:", "taskActions:"
            })
                StringAssert.Contains(actionField, inputSection);
            foreach (string bindingPath in new[]
            {
                "<XRController>{RightHand}/primary2DAxis",
                "<XRController>{RightHand}/primaryButton",
                "<XRController>{RightHand}/triggerPressed",
                "<XRController>{RightHand}/secondaryButton",
                "<XRController>{RightHand}/thumbstickClicked",
                "<Keyboard>/enter",
                "<Keyboard>/backspace",
                "<Keyboard>/digit1",
                "<Keyboard>/digit9",
            })
                StringAssert.Contains($"m_Path: {bindingPath}", inputSection);
            Assert.That(
                Regex.Matches(inputSection, @"(?m)^  - m_Name: Task[1-9]\r?$").Count,
                Is.EqualTo(ExperimentScenario.PlanCount));

            MatchCollection ids = Regex.Matches(inputSection, @"(?m)^\s+m_Id: (?<id>[^\r\n]+)$");
            var distinctIds = new HashSet<string>(StringComparer.Ordinal);
            foreach (Match match in ids)
                Assert.That(distinctIds.Add(match.Groups["id"].Value), Is.True, "InputAction GUID 必须唯一");
            Assert.That(distinctIds.Count, Is.GreaterThanOrEqualTo(20));

            string canvasTransform = ReadFirstComponentReference(GetSectionContaining(yaml, "m_Name: Canvas"));
            StringAssert.Contains("m_Father: {fileID: 0}", GetSection(yaml, canvasTransform));
        }

        /// <summary>开发场景必须使用相同内联动作，才能按正式流程执行 smoke。</summary>
        [Test]
        public void DevelopmentSceneUsesInlineInputActions()
        {
            string path = Path.Combine(Application.dataPath, "Scene", "EgoAnchor-Develop.unity");
            string yaml = File.ReadAllText(path);
            string sessionSection = GetSectionContaining(
                yaml, "m_EditorClassIdentifier: EgoAnchor::EgoAnchor.Eval.EvalSession");
            string inputSection = GetSectionContaining(
                yaml, "m_EditorClassIdentifier: EgoAnchor::EgoAnchor.Eval.Experiment.ExperimentInputHandler");

            StringAssert.Contains("runKind: 0", sessionSection);
            StringAssert.DoesNotContain("controlSessionShortcuts:", inputSection);
            StringAssert.DoesNotContain("controllerBinding:", inputSection);
            StringAssert.Contains("navigateAction:", inputSection);
            StringAssert.Contains("taskActions:", inputSection);
            StringAssert.Contains("m_Path: <XRController>{RightHand}/primaryButton", inputSection);
            StringAssert.Contains("m_Path: <Keyboard>/digit1", inputSection);
            StringAssert.Contains("m_Path: <Keyboard>/digit9", inputSection);
            StringAssert.Contains("m_Path: <Keyboard>/backspace", inputSection);
            Assert.That(
                Regex.Matches(inputSection, @"(?m)^  - m_Name: Task[1-9]\r?$").Count,
                Is.EqualTo(ExperimentScenario.PlanCount));

            string canvasTransform = ReadFirstComponentReference(GetSectionContaining(yaml, "m_Name: Canvas"));
            StringAssert.Contains("m_Father: {fileID: 0}", GetSection(yaml, canvasTransform));
        }

        /// <summary>各配置只能按实验定义切换目标组件，避免消融同时改变无关机制。</summary>
        [Test]
        public void ExperimentSceneVariantsMatchFrozenComponentMatrix()
        {
            string path = Path.Combine(Application.dataPath, "Scene", "EgoAnchor-Experiment12.unity");
            string yaml = File.ReadAllText(path);

            AssertVariantConfig(yaml, "Arrival-Hold", 1, 0, "ConstantVelocityModel", "RawPassthroughStrategy", false, 0, 0);
            AssertVariantConfig(yaml, "Capture-Hold", 0, 0, "ConstantVelocityModel", "RawPassthroughStrategy", false, 0, 0);
            AssertVariantConfig(yaml, "One-Euro Anchor", 0, 0, "OneEuroModel", "RawPassthroughStrategy", false, 0, 0);
            AssertVariantConfig(yaml, "EgoAnchor", 0, 1, "KalmanModel", "DelayedInterpStrategy", true, 1, 1);
            AssertVariantConfig(yaml, "EgoAnchor w/o capture-time alignment", 1, 1, "KalmanModel", "DelayedInterpStrategy", true, 1, 1);
            AssertVariantConfig(yaml, "EgoAnchor w/o VCD", 0, 0, "KalmanModel", "DelayedInterpStrategy", true, 0, 1);
            AssertVariantConfig(yaml, "EgoAnchor w/o temporal synthesis", 0, 1, "ConstantVelocityModel", "RawPassthroughStrategy", true, 1, 1);
            AssertVariantConfig(yaml, "EgoAnchor w/o StaticLock", 0, 1, "KalmanModel", "DelayedInterpStrategy", false, 1, 1);
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
                yaml, "m_Name: Experiment 2 - Design Attribution (Ablations)"));
            string experiment1Section = GetSection(yaml, experiment1Transform);
            string experiment2Section = GetSection(yaml, experiment2Transform);

            AssertVariantParent(yaml, "Arrival-Hold", experiment1Transform, experiment1Section);
            AssertVariantParent(yaml, "Capture-Hold", experiment1Transform, experiment1Section);
            AssertVariantParent(yaml, "One-Euro Anchor", experiment1Transform, experiment1Section);
            AssertVariantParent(yaml, "EgoAnchor", experiment1Transform, experiment1Section);
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

        /// <summary>三类实验一基线不得请求共享 Python pipeline 重获取。</summary>
        private static bool IsShadowBaseline(string label)
        {
            return label == "Arrival-Hold" || label == "Capture-Hold" || label == "One-Euro Anchor";
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
            string marker = $"&{fileId}\r\n";
            if (yaml.IndexOf(marker, StringComparison.Ordinal) < 0)
            {
                marker = $"&{fileId}\n";
            }
            return GetSectionContaining(yaml, marker);
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

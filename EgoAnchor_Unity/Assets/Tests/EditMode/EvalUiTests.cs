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
                new EvalLogStats(0, 1, null, 2), new EvalLogStats(0, 1, null, 2));

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
                "variant_definitions", "trial_plan", "log_files", "log_writer_stats",
            })
                StringAssert.Contains($"\"{field}\":", manifest);
            StringAssert.Contains("\"scenario_id\":\"occlusion_recovery\"", manifest);
            StringAssert.Contains("\"scenario_id\":\"without_static_lock\"", manifest);
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
        /// <summary>未录制时不得创建场景、trial 或事件上下文。</summary>
        [Test]
        public void SelectorRejectsContextChangesBeforeRecording()
        {
            GameObject sessionObject = new GameObject("ExperimentContextTests.Session");
            GameObject selectorObject = new GameObject("ExperimentContextTests.Selector");
            try
            {
                EvalSession session = sessionObject.AddComponent<EvalSession>();
                ExperimentTrialSelector selector = selectorObject.AddComponent<ExperimentTrialSelector>();
                selector.BindSession(session);

                Assert.That(selector.Advance(), Is.False);
                Assert.That(selector.CurrentContext.IsSelected, Is.False);
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(selectorObject);
                UnityEngine.Object.DestroyImmediate(sessionObject);
            }
        }

        /// <summary>普通场景三次推进必须依次开始、标记并结束，然后自动切换场景。</summary>
        [Test]
        public void SelectorAdvancesNormalScenarioWithOneAction()
        {
            GameObject sessionObject = new GameObject("ExperimentContextTests.Session");
            GameObject selectorObject = new GameObject("ExperimentContextTests.Selector");
            try
            {
                EvalSession session = sessionObject.AddComponent<EvalSession>();
                SetPrivateField(session, "_recording", true);
                ExperimentTrialSelector selector = selectorObject.AddComponent<ExperimentTrialSelector>();
                selector.BindSession(session);

                Assert.That(selector.CurrentExperimentId, Is.EqualTo(ExperimentId.SystemCharacterization));
                Assert.That(selector.CurrentScenarioId, Is.EqualTo("static_head_motion"));
                Assert.That(selector.CurrentPlanStep, Is.EqualTo(1));
                Assert.That(selector.Advance(), Is.True);
                Assert.That(selector.CurrentTrialId, Is.EqualTo("trial_001"));
                Assert.That(selector.Advance(), Is.True);
                Assert.That(selector.CurrentEventId, Is.EqualTo("event_001"));
                Assert.That(selector.CurrentEventRole, Is.EqualTo(ExperimentEventRole.GenericMarker));
                Assert.That(selector.Advance(), Is.True);
                Assert.That(selector.CurrentTrialId, Is.Empty);
                Assert.That(selector.CurrentEventId, Is.Empty);
                Assert.That(selector.CurrentScenarioId, Is.EqualTo("start_stop_6dof"));
                Assert.That(selector.CurrentPlanStep, Is.EqualTo(2));
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(selectorObject);
                UnityEngine.Object.DestroyImmediate(sessionObject);
            }
        }

        /// <summary>固定计划的起停场景必须把第二次推进标记为转换开始。</summary>
        [Test]
        public void SelectorMapsTransitionScenarioToTransitionStarted()
        {
            GameObject sessionObject = new GameObject("ExperimentContextTests.Session");
            GameObject selectorObject = new GameObject("ExperimentContextTests.Selector");
            try
            {
                EvalSession session = sessionObject.AddComponent<EvalSession>();
                SetPrivateField(session, "_recording", true);
                ExperimentTrialSelector selector = selectorObject.AddComponent<ExperimentTrialSelector>();
                selector.BindSession(session);

                CompleteCurrentScenario(selector);
                Assert.That(selector.CurrentScenarioId, Is.EqualTo("start_stop_6dof"));
                Assert.That(selector.Advance(), Is.True);
                Assert.That(selector.Advance(), Is.True);
                Assert.That(selector.CurrentEventRole, Is.EqualTo(ExperimentEventRole.TransitionStarted));
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(selectorObject);
                UnityEngine.Object.DestroyImmediate(sessionObject);
            }
        }

        /// <summary>遮挡场景四次推进必须依次开始、遮挡、可见并切换到实验二。</summary>
        [Test]
        public void SelectorAdvancesOcclusionRolesInOrder()
        {
            GameObject sessionObject = new GameObject("ExperimentContextTests.Session");
            GameObject selectorObject = new GameObject("ExperimentContextTests.Selector");
            try
            {
                EvalSession session = sessionObject.AddComponent<EvalSession>();
                SetPrivateField(session, "_recording", true);
                ExperimentTrialSelector selector = selectorObject.AddComponent<ExperimentTrialSelector>();
                selector.BindSession(session);

                for (int i = 0; i < 4; i++) CompleteCurrentScenario(selector);
                Assert.That(selector.CurrentScenarioId, Is.EqualTo("occlusion_recovery"));

                Assert.That(selector.Advance(), Is.True);
                Assert.That(selector.Advance(), Is.True);
                Assert.That(selector.CurrentEventRole, Is.EqualTo(ExperimentEventRole.OcclusionStarted));
                Assert.That(selector.HasOpenOcclusion, Is.True);
                string occlusionEventId = selector.CurrentEventId;

                Assert.That(selector.Advance(), Is.True);
                Assert.That(selector.CurrentEventRole, Is.EqualTo(ExperimentEventRole.TargetVisible));
                Assert.That(selector.CurrentEventId, Is.Not.EqualTo(occlusionEventId));
                Assert.That(selector.HasOpenOcclusion, Is.False);
                Assert.That(selector.Advance(), Is.True);
                Assert.That(selector.CurrentExperimentId, Is.EqualTo(ExperimentId.DesignAttribution));
                Assert.That(selector.CurrentScenarioId, Is.EqualTo("without_capture_time_alignment"));
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(selectorObject);
                UnityEngine.Object.DestroyImmediate(sessionObject);
            }
        }

        /// <summary>固定九场景全部完成后必须自动停止 session，无需额外停止键。</summary>
        [Test]
        public void SelectorStopsSessionAfterFinalScenario()
        {
            GameObject sessionObject = new GameObject("ExperimentContextTests.Session");
            GameObject selectorObject = new GameObject("ExperimentContextTests.Selector");
            try
            {
                EvalSession session = sessionObject.AddComponent<EvalSession>();
                SetPrivateField(session, "_recording", true);
                ExperimentTrialSelector selector = selectorObject.AddComponent<ExperimentTrialSelector>();
                selector.BindSession(session);

                for (int guard = 0; session.IsRecording && guard < 40; guard++)
                    Assert.That(selector.Advance(), Is.True);

                Assert.That(session.IsRecording, Is.False);
                Assert.That(selector.IsPlanComplete, Is.True);
                Assert.That(selector.CurrentPlanStep, Is.EqualTo(ExperimentScenario.PlanCount));
                Assert.That(selector.NextActionText, Is.EqualTo("COLLECTION COMPLETE"));
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(selectorObject);
                UnityEngine.Object.DestroyImmediate(sessionObject);
            }
        }

        /// <summary>手柄与键盘 binding 必须共用同一个推进状态机。</summary>
        [Test]
        public void InputHandlerExposesControllerAndKeyboardBindings()
        {
            GameObject sessionObject = new GameObject("ExperimentContextTests.Session");
            GameObject selectorObject = new GameObject("ExperimentContextTests.Selector");
            GameObject inputObject = new GameObject("ExperimentContextTests.Input");
            try
            {
                EvalSession session = sessionObject.AddComponent<EvalSession>();
                SetPrivateField(session, "_recording", true);
                ExperimentTrialSelector selector = selectorObject.AddComponent<ExperimentTrialSelector>();
                selector.BindSession(session);
                ExperimentInputHandler input = inputObject.AddComponent<ExperimentInputHandler>();
                SetPrivateField(input, "selector", selector);
                Assert.That(input.HandleAdvance(), Is.True);
                Assert.That(selector.HasActiveTrial, Is.True);
                Assert.That(input.HandleAdvance(), Is.True);
                Assert.That(selector.CurrentEventRole, Is.EqualTo(ExperimentEventRole.GenericMarker));

                Assert.That(
                    GetPrivateField(input, "controllerBinding"),
                    Is.EqualTo("<XRController>{RightHand}/primaryButton"));
                Assert.That(GetPrivateField(input, "keyboardBinding"), Is.EqualTo("<Keyboard>/space"));
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(inputObject);
                UnityEngine.Object.DestroyImmediate(selectorObject);
                UnityEngine.Object.DestroyImmediate(sessionObject);
            }
        }

        /// <summary>状态 UI 文本必须显示实验命名并拒绝旧 RQ 顶层文案。</summary>
        [Test]
        public void StatusUiUsesExperimentNaming()
        {
            GameObject sessionObject = new GameObject("ExperimentContextTests.Session");
            GameObject selectorObject = new GameObject("ExperimentContextTests.Selector");
            GameObject uiObject = new GameObject("ExperimentContextTests.UI");
            try
            {
                EvalSession session = sessionObject.AddComponent<EvalSession>();
                SetPrivateField(session, "_recording", true);
                ExperimentTrialSelector selector = selectorObject.AddComponent<ExperimentTrialSelector>();
                selector.BindSession(session);
                for (int i = 0; i < 6; i++) CompleteCurrentScenario(selector);
                Assert.That(selector.CurrentScenarioId, Is.EqualTo("without_vcd_admission"));
                selector.Advance();
                selector.Advance();

                ExperimentStatusUI status = uiObject.AddComponent<ExperimentStatusUI>();
                SetPrivateField(status, "selector", selector);
                SetPrivateField(status, "session", session);
                string text = status.BuildStatusText();

                StringAssert.Contains("EXP2 | DESIGN ATTRIBUTION", text);
                StringAssert.Contains("Ablation: VCD admission", text);
                StringAssert.Contains("Progress: 7 / 9", text);
                StringAssert.Contains("NEXT: PRESS RIGHT A WHEN TARGET IS VISIBLE", text);
                StringAssert.Contains("trial_007", text);
                StringAssert.Contains("Role: occlusion_started", text);
                StringAssert.DoesNotContain("RQ1", text);
                StringAssert.DoesNotContain("RQ2", text);
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(uiObject);
                UnityEngine.Object.DestroyImmediate(selectorObject);
                UnityEngine.Object.DestroyImmediate(sessionObject);
            }
        }

        /// <summary>完成当前场景，自动适配普通和遮挡场景需要的推进次数。</summary>
        private static void CompleteCurrentScenario(ExperimentTrialSelector selector)
        {
            int step = selector.CurrentPlanStep;
            for (int guard = 0; selector.CurrentPlanStep == step && guard < 5; guard++)
                Assert.That(selector.Advance(), Is.True);
            Assert.That(selector.CurrentPlanStep, Is.Not.EqualTo(step));
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

        /// <summary>正式场景必须固定 Formal，并暴露右手手柄与键盘两条统一推进 binding。</summary>
        [Test]
        public void ExperimentSceneUsesFormalSingleActionInput()
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

            StringAssert.Contains("controllerBinding: <XRController>{RightHand}/primaryButton", inputSection);
            StringAssert.Contains("keyboardBinding: <Keyboard>/space", inputSection);

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

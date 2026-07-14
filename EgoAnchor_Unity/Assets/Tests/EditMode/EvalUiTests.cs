using System.Text;
using System;
using EgoAnchor.Eval;
using EgoAnchor.Eval.Experiment;
using NUnit.Framework;
using System.Reflection;
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
                Runtime.WorldAlignmentMode.CaptureTime, true, true, Pose.identity,
                false, Pose.identity, true, 0.8f, "accepted", "quality_ok", "Tracking", "cfg"));
            EvalVariantSnapshot variant = new EvalVariantSnapshot(
                "egoanchor", true, 7, true, Pose.identity, true, Pose.identity, "transform",
                true, 1000, 3, 20, 1010, 10, 1040, "Tracking", "accepted", "quality_ok",
                "TRACK", string.Empty, "static", 0, "egoanchor", "enabled", "kalman", "hermite",
                "cfg", 0, 0, 0.8f, false, false, Pose.identity, false, Pose.identity, double.NaN, -1, "Left", 0.8f);
            string render = EvalJson.BuildRenderLine(
                1100, 2100, 5, Pose.identity,
                new EvalReferencePose(false, false, false, Pose.identity, double.NaN), 0, 0,
                variant, "s01");
            string manifest = EvalJson.BuildManifest(
                "s01", "controller_right", "editor_link",
                Array.Empty<string>(), Array.Empty<EvalVariantConfig>(), string.Empty,
                new EvalLogStats(0, 1, null), new EvalLogStats(0, 1, null),
                new EvalLogStats(0, 1, null), new EvalLogStats(0, 1, null));

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
            StringAssert.DoesNotContain("\"variants\"", render);
            foreach (string file in new[] { "python_candidates.jsonl", "unity_reference.jsonl", "unity_admission.jsonl", "unity_render.jsonl", "events.jsonl" })
                StringAssert.Contains(file, manifest);
            CollectionAssert.AreEqual(
                new[] { "python_candidates.jsonl", "unity_reference.jsonl", "unity_admission.jsonl", "unity_render.jsonl", "events.jsonl" },
                EvalV2Manifest.FixedLogFileNames);
            StringAssert.Contains("\"dropped_rows\":0", manifest);
            StringAssert.Contains("\"peak_queue_depth\":1", manifest);
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

                Assert.That(selector.SelectSystemScenario(1), Is.False);
                Assert.That(selector.BeginTrial(), Is.False);
                Assert.That(selector.MarkEvent(), Is.False);
                Assert.That(selector.CurrentContext.IsSelected, Is.False);
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(selectorObject);
                UnityEngine.Object.DestroyImmediate(sessionObject);
            }
        }

        /// <summary>实验一场景、trial、event 和结束动作必须生成稳定上下文标识。</summary>
        [Test]
        public void SelectorMaintainsStableTrialAndEventContext()
        {
            GameObject sessionObject = new GameObject("ExperimentContextTests.Session");
            GameObject selectorObject = new GameObject("ExperimentContextTests.Selector");
            try
            {
                EvalSession session = sessionObject.AddComponent<EvalSession>();
                SetPrivateField(session, "_recording", true);
                ExperimentTrialSelector selector = selectorObject.AddComponent<ExperimentTrialSelector>();
                selector.BindSession(session);

                Assert.That(selector.SelectSystemScenario(1), Is.True);
                Assert.That(selector.CurrentExperimentId, Is.EqualTo(ExperimentId.SystemCharacterization));
                Assert.That(selector.CurrentScenarioId, Is.EqualTo("static_head_motion"));
                Assert.That(selector.BeginTrial(), Is.True);
                Assert.That(selector.CurrentTrialId, Is.EqualTo("trial_001"));
                Assert.That(selector.MarkEvent(), Is.True);
                Assert.That(selector.CurrentEventId, Is.EqualTo("event_001"));
                Assert.That(selector.EndTrial(), Is.True);
                Assert.That(selector.CurrentTrialId, Is.Empty);
                Assert.That(selector.CurrentEventId, Is.Empty);
            }
            finally
            {
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
                selector.SelectAttributionScenario(2);
                selector.BeginTrial();

                ExperimentStatusUI status = uiObject.AddComponent<ExperimentStatusUI>();
                SetPrivateField(status, "selector", selector);
                SetPrivateField(status, "session", session);
                string text = status.BuildStatusText();

                StringAssert.Contains("EXP2 | DESIGN ATTRIBUTION", text);
                StringAssert.Contains("Ablation: VCD admission", text);
                StringAssert.Contains("trial_001", text);
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

        /// <summary>通过反射设置测试所需的私有录制状态，不扩大生产 API。</summary>
        private static void SetPrivateField(object target, string fieldName, object value)
        {
            FieldInfo field = target.GetType().GetField(fieldName, BindingFlags.Instance | BindingFlags.NonPublic);
            Assert.That(field, Is.Not.Null, $"missing private field {fieldName}");
            field.SetValue(target, value);
        }
    }
}

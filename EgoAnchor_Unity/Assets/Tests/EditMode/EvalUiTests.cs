using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;
using EgoAnchor.Eval;
using EgoAnchor.Eval.RQ1;
using EgoAnchor.Eval.RQ2;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.Controls;

namespace EgoAnchor.Tests
{
    /// <summary>评估状态文本测试，固定 RQ1 与 RQ2 共用的显示规则。</summary>
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

        /// <summary>RQ1 快捷键表在活动时只高亮当前指标。</summary>
        [Test]
        public void Rq1BindingsHighlightOnlyCurrentMetric()
        {
            string idle = BuildRq1Bindings(RQ1MetricType.None);
            string active = BuildRq1Bindings(RQ1MetricType.OcclusionRecovery);

            StringAssert.DoesNotContain("<color=#FFD700>", idle);
            StringAssert.Contains(
                "<color=#FFD700><b>[2]  Occlusion  Single  ◀</b></color>", active);
            Assert.That(
                active.Split(new[] { "<color=#FFD700>" }, StringSplitOptions.None).Length - 1,
                Is.EqualTo(1));
        }

        /// <summary>调用 RQ1 状态面板的私有纯文本函数。</summary>
        private static string BuildRq1Bindings(RQ1MetricType active)
        {
            MethodInfo method = typeof(RQ1StatusUI).GetMethod(
                "BuildKeyBindingsText",
                BindingFlags.Static | BindingFlags.NonPublic);
            Assert.That(method, Is.Not.Null);
            return (string)method.Invoke(null, new object[] { active });
        }
    }

    /// <summary>评估场景序列化契约测试，防止 Inspector 引用和 shadow baseline 配置回退。</summary>
    public sealed class EvalSceneContractTests
    {
        /// <summary>AnchorPolicyHost 的服务器重获取开关必须在场景中显式序列化。</summary>
        [TestCase("EgoAnchor-Develop.unity", 2, 0)]
        [TestCase("EgoAnchor-RQ1.unity", 3, 0)]
        public void ScenesExplicitlyConfigureServerReacquire(
            string sceneName,
            int expectedEnabled,
            int expectedDisabled)
        {
            const string policyGuid = "69b1bb8d66234574a8ed623d497f3835";
            string path = Path.Combine(Application.dataPath, "Scene", sceneName);
            string scene = File.ReadAllText(path).Replace("\r\n", "\n");
            string[] blocks = scene.Split(new[] { "--- " }, StringSplitOptions.RemoveEmptyEntries);
            string[] policies = Array.FindAll(blocks, block => block.Contains(policyGuid));

            Assert.That(policies, Has.Length.EqualTo(expectedEnabled + expectedDisabled));
            Assert.That(
                Array.FindAll(policies, block => block.Contains("emitServerReacquire: 1")),
                Has.Length.EqualTo(expectedEnabled));
            Assert.That(
                Array.FindAll(policies, block => block.Contains("emitServerReacquire: 0")),
                Has.Length.EqualTo(expectedDisabled));
        }

        /// <summary>RQ2 场景必须同步记录 Full 与隐藏的 ZOH，且不再保留阶段 UI。</summary>
        [Test]
        public void Rq2SceneUsesDirectTrialsAndPassiveZohBaseline()
        {
            string path = Path.Combine(Application.dataPath, "Scene", "EgoAnchor-RQ2.unity");
            string scene = File.ReadAllText(path).Replace("\r\n", "\n");
            string recorder = FindBlockContaining(scene, "EgoAnchor::EgoAnchor.Eval.EvalRecorder");
            Dictionary<string, long> runtimeIds = ReadVariantRuntimeIds(recorder);
            Dictionary<string, string> policyBlocks = ResolveVariantPolicyBlocks(scene, runtimeIds);

            Assert.That(runtimeIds.Keys, Is.EquivalentTo(new[] { "Full", "ZOH" }));
            StringAssert.DoesNotContain("m_Name: Phase", scene);
            StringAssert.DoesNotContain("phaseText:", scene);
            StringAssert.DoesNotContain("advancePhaseAction:", scene);
            StringAssert.DoesNotContain("NoStaticLock (RQ2 Disabled)", scene);

            string input = FindBlockContaining(scene, "EgoAnchor::EgoAnchor.Eval.RQ2.RQ2InputHandler");
            StringAssert.Contains("translationSpeedMs: 0.1", input);
            StringAssert.Contains("startTranslationAction:", input);
            StringAssert.Contains("m_Path: <Keyboard>/1", input);
            StringAssert.Contains("m_Path: <Keyboard>/2", input);
            StringAssert.DoesNotContain("slowTranslationSpeedMs:", input);
            StringAssert.DoesNotContain("fastMotionSpeedMs:", input);
            StringAssert.DoesNotContain("startSlowTranslationAction:", input);
            StringAssert.DoesNotContain("startFastMotionAction:", input);
            StringAssert.DoesNotContain("m_Path: <Keyboard>/3", input);

            string zohRuntime = ExtractObjectBlock(scene, 114, runtimeIds["ZOH"]);
            StringAssert.Contains("cameraLocalPositionOffset: {x: 0, y: 0, z: -0.016}", zohRuntime);

            string fullPolicy = policyBlocks["Full"];
            StringAssert.Contains("emitServerReacquire: 0", fullPolicy);

            string zohPolicy = policyBlocks["ZOH"];
            StringAssert.Contains("enableQualityGate: 1", zohPolicy);
            StringAssert.Contains("staticLockModule: {fileID: 0}", zohPolicy);
            StringAssert.Contains("trackingScoreFloor: 0.5", zohPolicy);
            StringAssert.Contains("enableLostReacquire: 1", zohPolicy);
            StringAssert.Contains("enableLowScoreReacquire: 1", zohPolicy);
            StringAssert.Contains("emitServerReacquire: 0", zohPolicy);

            StringAssert.Contains("gtFreshnessMode: 1", recorder);

            string selector = FindBlockContaining(scene, "EgoAnchor::EgoAnchor.Eval.RQ2.RQ2TrialSelector");
            long evalSessionId = ReadFileId(selector, "evalSession");
            Assert.That(evalSessionId, Is.GreaterThan(0));

            string hub = FindBlockContaining(scene, "EgoAnchor::EgoAnchor.Runtime.AnchorRuntimeHub");
            StringAssert.Contains($"- {{fileID: {runtimeIds["Full"]}}}", hub);
            StringAssert.Contains($"- {{fileID: {runtimeIds["ZOH"]}}}", hub);
        }

        /// <summary>RQ1 Recorder 必须显式保留静止 keep-alive 参考策略。</summary>
        [Test]
        public void Rq1SceneKeepsStaticReferencePosePolicy()
        {
            string path = Path.Combine(Application.dataPath, "Scene", "EgoAnchor-RQ1.unity");
            string scene = File.ReadAllText(path).Replace("\r\n", "\n");
            string recorder = FindBlockContaining(scene, "EgoAnchor::EgoAnchor.Eval.EvalRecorder");

            StringAssert.Contains("gtFreshnessMode: 0", recorder);
            StringAssert.Contains("gtKeepAliveSeconds: 30", recorder);
        }

        /// <summary>按类标识查找唯一的 Unity YAML 对象块。</summary>
        private static string FindBlockContaining(string scene, string marker)
        {
            string[] blocks = scene.Split(new[] { "\n--- " }, StringSplitOptions.RemoveEmptyEntries);
            string[] matches = Array.FindAll(blocks, block => block.Contains(marker));
            Assert.That(matches, Has.Length.EqualTo(1), $"场景中应唯一包含 {marker}");
            return matches[0];
        }

        /// <summary>从 EvalRecorder YAML 块读取 label 到 runtime fileID 的映射。</summary>
        private static Dictionary<string, long> ReadVariantRuntimeIds(string recorderBlock)
        {
            var result = new Dictionary<string, long>(StringComparer.Ordinal);
            MatchCollection matches = Regex.Matches(
                recorderBlock,
                @"- label: (?<label>[^\n]+)\n\s+runtime: \{fileID: (?<id>-?\d+)\}");
            foreach (Match match in matches)
            {
                result.Add(match.Groups["label"].Value.Trim(), long.Parse(match.Groups["id"].Value));
            }
            return result;
        }

        /// <summary>沿 runtime 的 policyHost 引用解析每个评估变体的策略 YAML 块。</summary>
        private static Dictionary<string, string> ResolveVariantPolicyBlocks(
            string scene,
            IReadOnlyDictionary<string, long> runtimeIds)
        {
            var result = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (KeyValuePair<string, long> item in runtimeIds)
            {
                string runtimeBlock = ExtractObjectBlock(scene, 114, item.Value);
                long policyId = ReadFileId(runtimeBlock, "policyHost");
                result.Add(item.Key, ExtractObjectBlock(scene, 114, policyId));
            }
            return result;
        }

        /// <summary>读取 Unity YAML 字段中的 fileID。</summary>
        private static long ReadFileId(string block, string fieldName)
        {
            Match match = Regex.Match(
                block,
                $@"{Regex.Escape(fieldName)}: \{{fileID: (?<id>-?\d+)\}}");
            Assert.That(match.Success, Is.True, $"缺少 fileID 字段 {fieldName}");
            return long.Parse(match.Groups["id"].Value);
        }

        /// <summary>按 Unity 对象类型与 fileID 提取完整 YAML 块。</summary>
        private static string ExtractObjectBlock(string scene, int objectType, long fileId)
        {
            string startMarker = $"--- !u!{objectType} &{fileId}";
            int start = scene.IndexOf(startMarker, StringComparison.Ordinal);
            Assert.That(start, Is.GreaterThanOrEqualTo(0), $"缺少场景对象 {startMarker}");
            int end = scene.IndexOf("\n--- ", start + startMarker.Length, StringComparison.Ordinal);
            if (end < 0) end = scene.Length;
            return scene.Substring(start, end - start);
        }
    }

    /// <summary>RQ1 输入处理器测试，防止组件反复启用后累积回调。</summary>
    public sealed class EvalInputHandlerTests : InputTestFixture
    {
        /// <summary>测试使用的隔离键盘。</summary>
        private Keyboard _keyboard;

        /// <summary>重置 Input System 并创建测试键盘。</summary>
        public override void Setup()
        {
            base.Setup();
            _keyboard = InputSystem.AddDevice<Keyboard>();
        }

        /// <summary>组件反复启停后，一次按键只能产生一次指标选择。</summary>
        [Test]
        public void HandlerDoesNotAccumulateCallbacks()
        {
            GameObject go = new GameObject("RQ1InputHandlerTests");
            go.SetActive(false);
            try
            {
                RQ1MetricSelector selector = go.AddComponent<RQ1MetricSelector>();
                RQ1InputHandler handler = go.AddComponent<RQ1InputHandler>();
                int selections = 0;
                selector.MetricChanged += (metric, _) =>
                {
                    if (metric != RQ1MetricType.StaticObservation) return;
                    selections++;
                    selector.ClearMetric();
                };

                go.SetActive(true);
                InvokeLifecycle(handler, "Awake");
                InvokeLifecycle(handler, "OnEnable");
                for (int i = 0; i < 3; i++)
                {
                    InvokeLifecycle(handler, "OnDisable");
                    InvokeLifecycle(handler, "OnEnable");
                }
                PressAndRelease(_keyboard.digit1Key);

                Assert.That(selections, Is.EqualTo(1));
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(go);
            }
        }

        /// <summary>RQ2 数字键必须立即开始有效试次，0 键必须直接结束当前试次。</summary>
        [Test]
        public void Rq2HandlerStartsAndEndsTrialsDirectly()
        {
            GameObject go = new GameObject("RQ2InputHandlerTests");
            go.SetActive(false);
            try
            {
                RQ2TrialSelector selector = go.AddComponent<RQ2TrialSelector>();
                RQ2InputHandler handler = go.AddComponent<RQ2InputHandler>();
                EvalSession session = go.AddComponent<EvalSession>();
                SetPrivateField(session, "_recording", true);
                SetPrivateField(handler, "evalSession", session);
                go.SetActive(true);
                InvokeLifecycle(handler, "Awake");
                InvokeLifecycle(handler, "OnEnable");

                AssertTrialKey(selector, _keyboard.digit1Key, RQ2Condition.Translation, 1);
                EndTrialWithZero(selector);
                AssertTrialKey(selector, _keyboard.digit2Key, RQ2Condition.Rotation, 2);
                EndTrialWithZero(selector);
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(go);
            }
        }

        /// <summary>RQ2 数字键在未录制时不得创建不可追溯的 trial 上下文。</summary>
        [Test]
        public void Rq2HandlerRejectsTrialWhenSessionIsNotRecording()
        {
            GameObject go = new GameObject("RQ2InputHandlerIdleTests");
            go.SetActive(false);
            try
            {
                RQ2TrialSelector selector = go.AddComponent<RQ2TrialSelector>();
                RQ2InputHandler handler = go.AddComponent<RQ2InputHandler>();
                EvalSession session = go.AddComponent<EvalSession>();
                SetPrivateField(handler, "evalSession", session);
                go.SetActive(true);
                InvokeLifecycle(handler, "Awake");
                InvokeLifecycle(handler, "OnEnable");

                PressAndRelease(_keyboard.digit1Key);

                Assert.That(selector.CurrentTrialId, Is.EqualTo(-1));
                Assert.That(selector.CurrentCondition, Is.EqualTo(RQ2Condition.None));
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(go);
            }
        }

        /// <summary>按下指定数字键，并断言试次上下文立即生效。</summary>
        private void AssertTrialKey(
            RQ2TrialSelector selector,
            KeyControl key,
            RQ2Condition expectedCondition,
            int expectedTrialId)
        {
            PressAndRelease(key);

            Assert.That(selector.CurrentTrialId, Is.EqualTo(expectedTrialId));
            Assert.That(selector.CurrentCondition, Is.EqualTo(expectedCondition));
        }

        /// <summary>按下 0 键，并断言试次上下文立即清空。</summary>
        private void EndTrialWithZero(RQ2TrialSelector selector)
        {
            PressAndRelease(_keyboard.digit0Key);

            Assert.That(selector.CurrentTrialId, Is.EqualTo(-1));
            Assert.That(selector.CurrentCondition, Is.EqualTo(RQ2Condition.None));
        }

        /// <summary>在 EditMode 中显式执行普通 MonoBehaviour 的生命周期方法。</summary>
        private static void InvokeLifecycle(MonoBehaviour behaviour, string methodName)
        {
            MethodInfo method = behaviour.GetType().GetMethod(
                methodName,
                BindingFlags.Instance | BindingFlags.NonPublic);
            Assert.That(method, Is.Not.Null, $"缺少生命周期方法 {methodName}");
            method.Invoke(behaviour, null);
        }

        /// <summary>反射设置测试对象的私有字段，避免为测试扩大运行时 API。</summary>
        private static void SetPrivateField<T>(object instance, string fieldName, T value)
        {
            FieldInfo field = instance.GetType().GetField(fieldName, BindingFlags.Instance | BindingFlags.NonPublic);
            Assert.That(field, Is.Not.Null, $"缺少字段 {fieldName}");
            field.SetValue(instance, value);
        }
    }
}

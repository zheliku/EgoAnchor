using System;
using System.IO;
using System.Reflection;
using System.Text;
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
        [TestCase("EgoAnchor-RQ2.unity", 2, 1)]
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

        /// <summary>RQ2 场景必须同步记录 Full 与隐藏的 Raw-ZOH，且不再保留阶段 UI。</summary>
        [Test]
        public void Rq2SceneUsesDirectTrialsAndPassiveRawZohBaseline()
        {
            string path = Path.Combine(Application.dataPath, "Scene", "EgoAnchor-RQ2.unity");
            string scene = File.ReadAllText(path).Replace("\r\n", "\n");

            StringAssert.Contains("- label: Full", scene);
            StringAssert.Contains(
                "- label: Raw-ZOH\n    runtime: {fileID: 1137170458}\n" +
                "    anchorTransform: {fileID: 1137170460}\n" +
                "    anchorPresenter: {fileID: 1137170459}\n" +
                "    isPrimary: 0",
                scene);
            StringAssert.DoesNotContain("m_Name: Phase", scene);
            StringAssert.DoesNotContain("phaseText:", scene);
            StringAssert.DoesNotContain("advancePhaseAction:", scene);

            string rawObject = ExtractBlock(scene, "--- !u!1 &1137170457", "--- !u!114 &1137170458");
            StringAssert.Contains("m_Name: AnchorObject Raw-ZOH", rawObject);
            StringAssert.Contains("m_IsActive: 1", rawObject);

            string rawRuntime = ExtractBlock(scene, "--- !u!114 &1137170458", "--- !u!114 &1137170459");
            StringAssert.Contains("cameraLocalPositionOffset: {x: 0, y: 0, z: -0.016}", rawRuntime);

            string fullPolicy = ExtractBlock(scene, "--- !u!114 &1039886366", "--- !u!114 &1039886367");
            StringAssert.Contains("emitServerReacquire: 1", fullPolicy);

            string rawPolicy = ExtractBlock(scene, "--- !u!114 &1484131521", "--- !u!114 &1484131523");
            StringAssert.Contains("enableQualityGate: 1", rawPolicy);
            StringAssert.Contains("staticLockModule: {fileID: 0}", rawPolicy);
            StringAssert.Contains("trackingScoreFloor: 0.5", rawPolicy);
            StringAssert.Contains("enableLostReacquire: 1", rawPolicy);
            StringAssert.Contains("enableLowScoreReacquire: 1", rawPolicy);
            StringAssert.Contains("emitServerReacquire: 0", rawPolicy);

            string rawMesh = ExtractBlock(scene, "--- !u!1 &2017392374", "--- !u!4 &2017392375");
            StringAssert.Contains("m_Name: Mesh", rawMesh);
            StringAssert.Contains("m_IsActive: 0", rawMesh);

            string hub = ExtractBlock(scene, "--- !u!114 &1777492727", "--- !u!4 &1777492728");
            StringAssert.Contains(
                "runtimes:\n  - {fileID: 160200731}\n  - {fileID: 1137170458}",
                hub);
        }

        /// <summary>按 Unity YAML 对象边界提取单个序列化块。</summary>
        private static string ExtractBlock(string scene, string startMarker, string endMarker)
        {
            int start = scene.IndexOf(startMarker, StringComparison.Ordinal);
            int end = scene.IndexOf(endMarker, start + startMarker.Length, StringComparison.Ordinal);
            Assert.That(start, Is.GreaterThanOrEqualTo(0), $"缺少场景块 {startMarker}");
            Assert.That(end, Is.GreaterThan(start), $"缺少场景块结束标记 {endMarker}");
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
                go.SetActive(true);
                InvokeLifecycle(handler, "Awake");
                InvokeLifecycle(handler, "OnEnable");

                AssertTrialKey(selector, _keyboard.digit1Key, RQ2Condition.SlowTranslation, 1);
                EndTrialWithZero(selector);
                AssertTrialKey(selector, _keyboard.digit2Key, RQ2Condition.FastMotion, 2);
                EndTrialWithZero(selector);
                AssertTrialKey(selector, _keyboard.digit3Key, RQ2Condition.Rotation, 3);
                EndTrialWithZero(selector);
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
    }
}

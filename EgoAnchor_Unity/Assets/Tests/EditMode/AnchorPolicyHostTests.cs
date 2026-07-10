using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using EgoAnchor.Alignment;
using EgoAnchor.Eval;
using EgoAnchor.Eval.RQ2;
using EgoAnchor.Policy;
using EgoAnchor.Protocol.Generated;
using EgoAnchor.Runtime;
using NUnit.Framework;
using UnityEngine;

namespace EgoAnchor.Tests
{
    /// <summary>
    /// AnchorPolicyHost 生命周期测试，覆盖采集时刻与到达时刻分离后的重定位边界。
    /// </summary>
    public sealed class AnchorPolicyHostTests
    {
        /// <summary>
        /// frame history 必须同时保留图像时间代理、回退样本数与 payload-ready 时刻，避免混用时间轴。
        /// </summary>
        [Test]
        public void FramePoseRecordKeepsImageAndSenderTiming()
        {
            FramePoseRecord record = new FramePoseRecord(
                frameId: 42,
                leftCameraPose: Pose.identity,
                rightCameraPose: Pose.identity,
                centerCameraPose: Pose.identity,
                imageMonoMs: 1000.0,
                imageUnityFrame: 10,
                imageTimeOffsetFrames: 1,
                senderMonoMs: 1033.0,
                senderUnityFrame: 12);

            Assert.That(record.ImageMonoMs, Is.EqualTo(1000.0));
            Assert.That(record.ImageUnityFrame, Is.EqualTo(10));
            Assert.That(record.ImageTimeOffsetFrames, Is.EqualTo(1));
            Assert.That(record.SenderMonoMs, Is.EqualTo(1033.0));
            Assert.That(record.SenderUnityFrame, Is.EqualTo(12));
        }

        /// <summary>
        /// 延迟插值策略必须报告 pose 实际对应的语义时刻，而不是一律报告当前渲染时刻。
        /// </summary>
        [Test]
        public void DelayedInterpReportsActualOutputTargetTime()
        {
            GameObject go = new GameObject("DelayedInterpOutputTargetTests");
            try
            {
                ConstantVelocityModel model = go.AddComponent<ConstantVelocityModel>();
                DelayedInterpStrategy smoothing = go.AddComponent<DelayedInterpStrategy>();
                smoothing.ResetStrategy();

                smoothing.Output(model, 5.0);
                Assert.That(smoothing.OutputTargetTimeSeconds, Is.EqualTo(5.0));
                Assert.That(GetPrivateField<double>(smoothing, "lastOutputTimeSeconds"), Is.EqualTo(5.0));

                List<ControlPoint> points = GetPrivateField<List<ControlPoint>>(smoothing, "points");
                points.Add(new ControlPoint(10.0, Pose.identity, Vector3.right, Vector3.zero));
                smoothing.Output(model, 20.0);
                Assert.That(smoothing.OutputTargetTimeSeconds, Is.EqualTo(10.0));
                Assert.That(GetPrivateField<double>(smoothing, "lastOutputTimeSeconds"), Is.EqualTo(20.0));

                points.Add(new ControlPoint(20.0, new Pose(Vector3.right * 10f, Quaternion.identity), Vector3.right, Vector3.zero));

                SetPrivateField(smoothing, "delaySeconds", 20.0f);
                SetPrivateField(smoothing, "lastOutputTimeSeconds", 20.0);
                smoothing.Output(model, 20.0);
                Assert.That(smoothing.OutputTargetTimeSeconds, Is.EqualTo(10.0), "早于最早点时应钳到最早点时间。");

                SetPrivateField(smoothing, "delaySeconds", 5.0f);
                SetPrivateField(smoothing, "lastOutputTimeSeconds", 20.0);
                smoothing.Output(model, 20.0);
                Assert.That(smoothing.OutputTargetTimeSeconds, Is.EqualTo(15.0).Within(1e-6), "插值输出应报告插值目标时间。");

                SetPrivateField(smoothing, "delaySeconds", 0.0f);
                SetPrivateField(smoothing, "minDelaySeconds", 0.0f);
                SetPrivateField(smoothing, "lastOutputTimeSeconds", 30.0);
                smoothing.Output(model, 30.0);
                Assert.That(smoothing.OutputTargetTimeSeconds, Is.EqualTo(30.0).Within(1e-6), "最新点之后外推应报告外推目标时间。");
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(go);
            }
        }

        /// <summary>
        /// Blend 叠加跨时刻残差后没有唯一输出语义时刻，不能伪报为当前渲染时刻。
        /// </summary>
        [Test]
        public void BlendReportsUnknownOutputTargetWhenResidualTimeIsAmbiguous()
        {
            GameObject go = new GameObject("BlendOutputTargetTests");
            try
            {
                ConstantVelocityModel model = go.AddComponent<ConstantVelocityModel>();
                BlendStrategy smoothing = go.AddComponent<BlendStrategy>();
                model.Snap(AnchorObservation.FromAlignedPose(
                    frameId: 1,
                    worldPose: Pose.identity,
                    sampleTimeSeconds: 10.0,
                    reliabilityScore: 1.0f,
                    captureTimeSeconds: 10.0));

                smoothing.Output(model, 12.0);

                Assert.That(smoothing.OutputTargetTimeSeconds, Is.NaN);
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(go);
            }
        }

        /// <summary>
        /// Raw 零阶保持输出必须继承最新控制点时间，不能伪装成当前渲染时刻。
        /// </summary>
        [Test]
        public void RawReportsLatestControlPointTimeAsOutputTarget()
        {
            GameObject go = new GameObject("RawOutputTargetTests");
            try
            {
                ConstantVelocityModel model = go.AddComponent<ConstantVelocityModel>();
                RawPassthroughStrategy smoothing = go.AddComponent<RawPassthroughStrategy>();
                AnchorObservation observation = AnchorObservation.FromAlignedPose(
                    frameId: 1,
                    worldPose: Pose.identity,
                    sampleTimeSeconds: 10.0,
                    reliabilityScore: 1.0f,
                    captureTimeSeconds: 10.0);
                model.Snap(observation);
                smoothing.OnObservation(model, observation);

                smoothing.Output(model, 12.0);

                Assert.That(smoothing.OutputTargetTimeSeconds, Is.EqualTo(10.0));
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(go);
            }
        }

        /// <summary>
        /// runtime 有有效 policy 输出时，快照必须标记有效，并记录绑定 Transform 的实际 world pose。
        /// </summary>
        [Test]
        public void RecorderSnapshotUsesTransformPoseWhenRuntimeHasOutput()
        {
            GameObject recorderGo = new GameObject("EvalRecorderPositiveSnapshotTests");
            GameObject runtimeGo = new GameObject("EvalRuntimePositiveSnapshotTests");
            GameObject anchorGo = new GameObject("EvalAnchorPositiveSnapshotTests");
            try
            {
                EvalRecorder recorder = recorderGo.AddComponent<EvalRecorder>();
                AnchorPolicyHost host = runtimeGo.AddComponent<AnchorPolicyHost>();
                ConstantVelocityModel model = runtimeGo.AddComponent<ConstantVelocityModel>();
                RawPassthroughStrategy smoothing = runtimeGo.AddComponent<RawPassthroughStrategy>();
                PoseToAnchorRuntime runtime = runtimeGo.AddComponent<PoseToAnchorRuntime>();
                SetPrivateField(host, "motionModel", model);
                SetPrivateField(host, "smoothingStrategy", smoothing);
                SetPrivateField(runtime, "policyHost", host);
                host.Bind(runtime);

                runtime.AcceptWorldPose(42, new Pose(Vector3.one, Quaternion.identity));
                runtime.AdvanceAnchorOutput(Time.realtimeSinceStartupAsDouble + 0.01);
                Assert.That(runtime.TryGetOutputPose(out _), Is.True);
                Assert.That(runtime.LatestObservationAgeMs, Is.Not.NaN);
                Assert.That(runtime.LatestPolicyOutputTargetMonoMs, Is.Not.NaN);
                Assert.That(runtime.LatestSmoothingDelayMs, Is.Not.NaN);
                Assert.That(runtime.LatestUnityPoseHandleMonoMs, Is.Not.NaN);

                Pose expected = new Pose(new Vector3(4f, 5f, 6f), Quaternion.Euler(10f, 20f, 30f));
                anchorGo.transform.SetPositionAndRotation(expected.position, expected.rotation);
                SetPrivateField(recorder, "variants", new List<EvalVariant>
                {
                    new EvalVariant
                    {
                        label = "primary",
                        runtime = runtime,
                        anchorTransform = anchorGo.transform,
                        isPrimary = true,
                    },
                });

                InvokeBuildSnapshots(recorder);

                List<EvalVariantSnapshot> snapshots = GetPrivateField<List<EvalVariantSnapshot>>(recorder, "_snapshots");
                Assert.That(snapshots, Has.Count.EqualTo(1));
                Assert.That(snapshots[0].HasOutputPose, Is.True);
                Assert.That(snapshots[0].OutputPose.position, Is.EqualTo(expected.position));
                Assert.That(Quaternion.Angle(snapshots[0].OutputPose.rotation, expected.rotation), Is.LessThan(1e-4f));
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(anchorGo);
                UnityEngine.Object.DestroyImmediate(runtimeGo);
                UnityEngine.Object.DestroyImmediate(recorderGo);
            }
        }

        /// <summary>
        /// LateUpdate 执行顺序必须固定为 runtime(-50) → Transform 应用(0) → 评估记录(50)。
        /// </summary>
        [Test]
        public void AnchorOutputExecutionOrderIsExplicit()
        {
            Assert.That(ReadExecutionOrder<PoseToAnchorRuntime>(), Is.EqualTo(-50));
            Assert.That(ReadExecutionOrder<DynamicObjectAnchor>(), Is.EqualTo(0));
            Assert.That(ReadExecutionOrder<EvalRecorder>(), Is.EqualTo(50));
        }

        /// <summary>
        /// 控制器与模块必须显式暴露最终 pose 是否覆盖 smoothing 输出，供 Host 判定时间语义有效性。
        /// </summary>
        [Test]
        public void StaticLockModuleReportsSmoothingPoseOverrideState()
        {
            GameObject go = new GameObject("StaticLockOverrideStateTests");
            try
            {
                EgoAnchorStaticLockModule module = go.AddComponent<EgoAnchorStaticLockModule>();
                StaticLockController controller = GetPrivateField<StaticLockController>(module, "staticLock");

                Assert.That(controller.IsSeamActive, Is.False);
                Assert.That(module.OverridesSmoothingPose, Is.False);

                SetPrivateField(controller, "seamActive", true);
                Assert.That(controller.IsSeamActive, Is.True);
                Assert.That(module.OverridesSmoothingPose, Is.True);

                SetPrivateField(controller, "seamActive", false);
                SetPrivateField(controller, "locked", true);
                Assert.That(module.OverridesSmoothingPose, Is.True);
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(go);
            }
        }

        /// <summary>
        /// StaticLock 锁定或接缝改写最终 pose 时，smoothing 输出目标时间不再能解释最终 pose，必须清空。
        /// </summary>
        [Test]
        public void StaticLockOverrideInvalidatesPolicyOutputTime()
        {
            GameObject go = new GameObject("StaticLockOutputTimeTests");
            try
            {
                AnchorPolicyHost host = go.AddComponent<AnchorPolicyHost>();
                ConstantVelocityModel model = go.AddComponent<ConstantVelocityModel>();
                RawPassthroughStrategy smoothing = go.AddComponent<RawPassthroughStrategy>();
                EgoAnchorStaticLockModule module = go.AddComponent<EgoAnchorStaticLockModule>();
                SetPrivateField(host, "motionModel", model);
                SetPrivateField(host, "smoothingStrategy", smoothing);
                SetPrivateField(host, "staticLockModule", module);

                host.AcceptPose(AnchorObservation.FromAlignedPose(
                    frameId: 1,
                    worldPose: Pose.identity,
                    sampleTimeSeconds: 10.0,
                    reliabilityScore: 1.0f,
                    captureTimeSeconds: 10.0));

                AnchorPolicyOutput freeOutput = host.Advance(10.1);
                Assert.That(freeOutput.OutputTargetTimeSeconds, Is.EqualTo(10.0));
                Assert.That(freeOutput.SmoothingDelaySeconds, Is.EqualTo(0.1).Within(1e-6));

                StaticLockController controller = GetPrivateField<StaticLockController>(module, "staticLock");
                SetPrivateField(controller, "locked", true);
                SetPrivateField(controller, "lockedPose", new Pose(Vector3.one, Quaternion.identity));
                AnchorPolicyOutput lockedOutput = host.Advance(10.2);
                Assert.That(lockedOutput.OutputTargetTimeSeconds, Is.NaN);
                Assert.That(lockedOutput.SmoothingDelaySeconds, Is.NaN);

                SetPrivateField(controller, "locked", false);
                SetPrivateField(controller, "seamActive", true);
                SetPrivateField(controller, "seamPos", Vector3.one);
                AnchorPolicyOutput seamOutput = host.Advance(10.3);
                Assert.That(seamOutput.OutputTargetTimeSeconds, Is.NaN);
                Assert.That(seamOutput.SmoothingDelaySeconds, Is.NaN);
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(go);
            }
        }

        /// <summary>
        /// 最终 pose 时间语义无效时，评估 JSON 必须写 null，不能留下可误读的数值。
        /// </summary>
        [Test]
        public void EvalJsonWritesNullForInvalidPolicyOutputTime()
        {
            EvalVariantSnapshot snapshot = CreateTimingSnapshot(
                policyOutputTargetMonoMs: double.NaN,
                smoothingDelayMs: double.NaN);

            string json = EvalJson.BuildOutputLine(
                renderMonoMs: 2000.0,
                renderUnixMs: 3000.0,
                renderUnityFrame: 20,
                sourceFrameId: 42,
                headPose: Pose.identity,
                gtValid: false,
                gtPose: Pose.identity,
                gtLinearSpeedMs: 0f,
                gtAngularSpeedDegS: 0f,
                variants: new[] { snapshot });

            StringAssert.Contains("\"policy_output_target_mono_ms\":null", json);
            StringAssert.Contains("\"smoothing_delay_ms\":null", json);
        }

        /// <summary>
        /// Transform 仍保留旧 pose 时，若 runtime 已没有 policy 输出，评估快照不得伪报有效输出。
        /// </summary>
        [Test]
        public void RecorderSnapshotIsInvalidWhenRuntimeHasNoOutput()
        {
            GameObject go = new GameObject("EvalRecorderSnapshotTests");
            try
            {
                EvalRecorder recorder = go.AddComponent<EvalRecorder>();
                PoseToAnchorRuntime runtime = go.AddComponent<PoseToAnchorRuntime>();
                DynamicObjectAnchor presenter = go.AddComponent<DynamicObjectAnchor>();
                SetPrivateField(presenter, "runtime", runtime);
                SetPrivateField(presenter, "targetTransform", go.transform);
                SetPrivateField(presenter, "lastAppliedFrameId", 42L);
                var variants = new List<EvalVariant>
                {
                    new EvalVariant
                    {
                        label = "primary",
                        runtime = runtime,
                        anchorPresenter = presenter,
                        anchorTransform = go.transform,
                        isPrimary = true,
                    },
                };
                SetPrivateField(recorder, "variants", variants);

                InvokeBuildSnapshots(recorder);

                List<EvalVariantSnapshot> snapshots = GetPrivateField<List<EvalVariantSnapshot>>(recorder, "_snapshots");
                Assert.That(snapshots, Has.Count.EqualTo(1));
                Assert.That(snapshots[0].HasOutputPose, Is.False);
                Assert.That(snapshots[0].HasRuntimeOutput, Is.False);
                Assert.That(snapshots[0].HasDisplayPose, Is.True);
                Assert.That(snapshots[0].DisplayPose.position, Is.EqualTo(go.transform.position));
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(go);
            }
        }

        /// <summary>
        /// output JSON 必须包含观测年龄、policy 目标时刻、平滑延迟与 Unity pose 处理时刻。
        /// </summary>
        [Test]
        public void EvalJsonWritesPolicyTimingFields()
        {
            EvalVariantSnapshot snapshot = CreateTimingSnapshot();

            string json = EvalJson.BuildOutputLine(
                renderMonoMs: 2000.0,
                renderUnixMs: 3000.0,
                renderUnityFrame: 20,
                sourceFrameId: 42,
                headPose: Pose.identity,
                gtValid: false,
                gtPose: Pose.identity,
                gtLinearSpeedMs: 0f,
                gtAngularSpeedDegS: 0f,
                variants: new[] { snapshot });

            StringAssert.Contains("\"observation_age_ms\":120", json);
            StringAssert.Contains("\"policy_output_target_mono_ms\":1880", json);
            StringAssert.Contains("\"smoothing_delay_ms\":120", json);
            StringAssert.Contains("\"unity_pose_handle_mono_ms\":1500", json);
        }

        /// <summary>
        /// capture 行必须区分图像时间代理、payload-ready 与实际 ZMQ 发布尝试时刻。
        /// </summary>
        [Test]
        public void EvalJsonWritesCaptureTimingBasisAndPublishAttempt()
        {
            string json = EvalJson.BuildCaptureLine(
                frameId: 42,
                captureMonoMs: 1000.0,
                captureUnixMs: 3000.0,
                captureUnityFrame: 10,
                senderMonoMs: 1020.0,
                senderUnityFrame: 11,
                gtSampleMonoMs: 1030.0,
                imageTimeOffsetFrames: 1,
                publishAttemptMonoMs: 1040.0,
                publishSucceeded: true,
                headPose: Pose.identity,
                cameraValid: true,
                cameraPose: Pose.identity,
                gtValid: true,
                gtPose: Pose.identity,
                cameraReference: "Left");

            StringAssert.Contains("\"image_time_basis\":\"camera_pose_history_proxy\"", json);
            StringAssert.Contains("\"image_time_offset_frames\":1", json);
            StringAssert.Contains("\"publish_attempt_mono_ms\":1040", json);
            StringAssert.Contains("\"publish_succeeded\":true", json);
        }

        /// <summary>
        /// RQ2 场景必须使用稳定的 snake_case 日志值，供 Python 分组时直接读取。
        /// </summary>
        [Test]
        public void RQ2EnumsUseStableLogStrings()
        {
            Assert.That(RQ2Condition.SlowTranslation.ToLogString(), Is.EqualTo("slow_translation"));
            Assert.That(RQ2Condition.FastMotion.ToLogString(), Is.EqualTo("fast_motion"));
            Assert.That(RQ2Condition.Rotation.ToLogString(), Is.EqualTo("rotation"));
            Assert.That(RQ2Condition.None.ToLogString(), Is.EqualTo("none"));
        }

        /// <summary>
        /// selector 只维护试次上下文：按键开始后立即有效，编号在 session 内递增，结束后回到空闲态。
        /// </summary>
        [Test]
        public void RQ2TrialSelectorMaintainsTrialContext()
        {
            GameObject go = new GameObject("RQ2TrialSelectorTests");
            try
            {
                RQ2TrialSelector selector = go.AddComponent<RQ2TrialSelector>();

                selector.StartTrial(RQ2Condition.SlowTranslation, 0.15f, float.NaN);
                Assert.That(selector.CurrentTrialId, Is.EqualTo(1));
                Assert.That(selector.CurrentCondition, Is.EqualTo(RQ2Condition.SlowTranslation));
                Assert.That(selector.TargetLinearSpeedMs, Is.EqualTo(0.15f));
                Assert.That(selector.TargetAngularSpeedDegS, Is.NaN);

                selector.StartTrial(RQ2Condition.FastMotion, 1.0f, float.NaN);
                Assert.That(selector.CurrentTrialId, Is.EqualTo(1));
                Assert.That(selector.CurrentCondition, Is.EqualTo(RQ2Condition.SlowTranslation));
                selector.EndTrial();

                Assert.That(selector.CurrentTrialId, Is.EqualTo(-1));
                Assert.That(selector.CurrentCondition, Is.EqualTo(RQ2Condition.None));
                Assert.That(selector.TargetLinearSpeedMs, Is.NaN);
                Assert.That(selector.TargetAngularSpeedDegS, Is.NaN);

                selector.StartTrial(RQ2Condition.FastMotion, 1.0f, float.NaN);
                Assert.That(selector.CurrentTrialId, Is.EqualTo(2));

                selector.ResetSession();
                selector.StartTrial(RQ2Condition.Rotation, float.NaN, 90f);
                Assert.That(selector.CurrentTrialId, Is.EqualTo(1));
                Assert.That(selector.TargetAngularSpeedDegS, Is.EqualTo(90f));
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(go);
            }
        }

        /// <summary>RQ2 直接试次流程不得继续暴露阶段枚举、阶段推进方法或空格输入动作。</summary>
        [Test]
        public void RQ2DirectTrialFlowRemovesPhaseApi()
        {
            Assert.That(
                typeof(RQ2TrialSelector).Assembly.GetType("EgoAnchor.Eval.RQ2.RQ2TrialPhase"),
                Is.Null);
            Assert.That(
                typeof(RQ2TrialSelector).GetProperty("CurrentPhase"),
                Is.Null);
            Assert.That(
                typeof(RQ2TrialSelector).GetMethod("AdvancePhase"),
                Is.Null);
            Assert.That(
                typeof(RQ2InputHandler).GetField(
                    "advancePhaseAction",
                    BindingFlags.Instance | BindingFlags.NonPublic),
                Is.Null);
        }

        /// <summary>
        /// RQ2 状态面板空闲时不能残留任何场景快捷键高亮。
        /// </summary>
        [Test]
        public void RQ2StatusUiLeavesTrialShortcutsUnhighlightedWhenIdle()
        {
            string idleBindings = InvokePrivateStaticMethod<string>(
                typeof(RQ2StatusUI), "BuildKeyBindingsText", RQ2Condition.None);
            StringAssert.DoesNotContain("<color=#FFD700>", idleBindings);
            StringAssert.DoesNotContain("Space", idleBindings);
            StringAssert.DoesNotContain("Phase", idleBindings);
            StringAssert.Contains("[0] End Trial", idleBindings);
        }

        /// <summary>RQ2 活动场景必须只高亮对应快捷键行。</summary>
        [TestCase(
            RQ2Condition.SlowTranslation,
            "<color=#FFD700><b>[1]  Slow Translation  ◀</b></color>")]
        [TestCase(
            RQ2Condition.FastMotion,
            "<color=#FFD700><b>[2]  Fast Motion  ◀</b></color>")]
        [TestCase(
            RQ2Condition.Rotation,
            "<color=#FFD700><b>[3]  Rotation  ◀</b></color>")]
        public void RQ2StatusUiHighlightsOnlyActiveTrialShortcut(
            RQ2Condition active,
            string expectedRow)
        {
            string activeBindings = InvokePrivateStaticMethod<string>(
                typeof(RQ2StatusUI), "BuildKeyBindingsText", active);
            StringAssert.Contains(expectedRow, activeBindings);
            int highlightCount = activeBindings
                .Split(new[] { "<color=#FFD700>" }, StringSplitOptions.None)
                .Length - 1;
            Assert.That(highlightCount, Is.EqualTo(1));
        }

        /// <summary>公共录制状态与 RQ2 活动试次文本必须使用统一视觉标记。</summary>
        [Test]
        public void RQ2StatusUiUsesSharedRecordingAndTrialMarkers()
        {
            Assert.That(
                EvalStatusText.Recording(true),
                Is.EqualTo("● Recording"));
            Assert.That(
                EvalStatusText.Recording(false),
                Is.EqualTo("○ Not Recording"));
            Assert.That(
                InvokePrivateStaticMethod<string>(
                    typeof(RQ2StatusUI), "BuildTrialText", -1, RQ2Condition.None),
                Is.EqualTo("Trial: Idle"));
            Assert.That(
                InvokePrivateStaticMethod<string>(
                    typeof(RQ2StatusUI), "BuildTrialText", 1, RQ2Condition.SlowTranslation),
                Is.EqualTo("Trial 1: Slow Translation (Key 1)"));
        }

        /// <summary>
        /// output JSON 顶层必须逐帧保存 RQ2 试次上下文，不再写入已删除的阶段字段。
        /// </summary>
        [Test]
        public void EvalJsonWritesRQ2TrialContext()
        {
            string json = EvalJson.BuildOutputLine(
                renderMonoMs: 2000.0,
                renderUnixMs: 3000.0,
                renderUnityFrame: 20,
                sourceFrameId: 42,
                headPose: Pose.identity,
                gtValid: false,
                gtPose: Pose.identity,
                gtLinearSpeedMs: 0f,
                gtAngularSpeedDegS: 0f,
                variants: Array.Empty<EvalVariantSnapshot>(),
                rq2Condition: "rotation",
                rq2TrialId: 7,
                rq2TargetLinearSpeedMs: float.NaN,
                rq2TargetAngularSpeedDegS: 90f);

            StringAssert.Contains("\"rq2_condition\":\"rotation\"", json);
            StringAssert.Contains("\"rq2_trial_id\":7", json);
            StringAssert.DoesNotContain("\"rq2_phase\"", json);
            StringAssert.Contains("\"rq2_target_linear_speed_m_s\":null", json);
            StringAssert.Contains("\"rq2_target_angular_speed_deg_s\":90", json);
        }

        /// <summary>
        /// manifest 配置必须取会话开始时快照；停止后 runtime 被销毁也不能把配置摘要写成空字符串。
        /// </summary>
        [Test]
        public void RecorderKeepsManifestConfigSnapshotAfterRuntimeDestroyed()
        {
            GameObject recorderGo = new GameObject("EvalRecorderManifestTests");
            GameObject runtimeGo = new GameObject("EvalRuntimeManifestTests");
            string directory = Path.Combine(Application.temporaryCachePath, $"egoanchor_manifest_{Guid.NewGuid():N}");
            Directory.CreateDirectory(directory);
            string capturePath = Path.Combine(directory, "capture.jsonl");
            string outputPath = Path.Combine(directory, "output.jsonl");

            try
            {
                EvalRecorder recorder = recorderGo.AddComponent<EvalRecorder>();
                AnchorPolicyHost host = runtimeGo.AddComponent<AnchorPolicyHost>();
                ConstantVelocityModel model = runtimeGo.AddComponent<ConstantVelocityModel>();
                RawPassthroughStrategy smoothing = runtimeGo.AddComponent<RawPassthroughStrategy>();
                PoseToAnchorRuntime runtime = runtimeGo.AddComponent<PoseToAnchorRuntime>();
                SetPrivateField(host, "motionModel", model);
                SetPrivateField(host, "smoothingStrategy", smoothing);
                SetPrivateField(runtime, "policyHost", host);
                SetPrivateField(recorder, "variants", new List<EvalVariant>
                {
                    new EvalVariant
                    {
                        label = "Full",
                        runtime = runtime,
                        anchorTransform = runtimeGo.transform,
                        isPrimary = true,
                    },
                });

                recorder.BeginRecording(capturePath, outputPath);
                UnityEngine.Object.DestroyImmediate(runtimeGo);
                recorder.StopRecording();

                var labels = new List<string>();
                var configs = new List<EvalVariantConfig>();
                recorder.CollectVariantLabels(labels);
                recorder.CollectVariantConfigs(configs);

                Assert.That(labels, Is.EqualTo(new[] { "Full" }));
                Assert.That(configs, Has.Count.EqualTo(1));
                Assert.That(configs[0].MotionModel, Is.EqualTo("cv"));
                Assert.That(configs[0].SmoothingStrategy, Is.EqualTo("raw_passthrough"));
                Assert.That(configs[0].QualityGate, Is.EqualTo("disabled"));
                Assert.That(configs[0].ConfigHash, Is.Not.Empty);
            }
            finally
            {
                if (runtimeGo != null) UnityEngine.Object.DestroyImmediate(runtimeGo);
                UnityEngine.Object.DestroyImmediate(recorderGo);
                if (Directory.Exists(directory)) Directory.Delete(directory, true);
            }
        }

        /// <summary>
        /// 高分 register pose 即使推理延迟较大，也不能在到达后一帧立刻被生命周期判 Lost 并请求 server reacquire。
        /// </summary>
        [Test]
        public void HighScoreDelayedRegisterDoesNotImmediatelyRequestServerReacquire()
        {
            GameObject go = new GameObject("AnchorPolicyHostTests");
            try
            {
                AnchorPolicyHost host = go.AddComponent<AnchorPolicyHost>();
                ConstantVelocityModel model = go.AddComponent<ConstantVelocityModel>();
                RawPassthroughStrategy smoothing = go.AddComponent<RawPassthroughStrategy>();
                SetPrivateField(host, "motionModel", model);
                SetPrivateField(host, "smoothingStrategy", smoothing);

                AnchorObservation observation = AnchorObservation.FromAlignedPose(
                    frameId: 42,
                    worldPose: new Pose(new Vector3(0.1f, 0.2f, 0.3f), Quaternion.identity),
                    sampleTimeSeconds: 10.0,
                    reliabilityScore: 1.0f,
                    reliabilityFlags: new[] { "quality_pending" },
                    phase: "REGISTER",
                    poseSource: "REGISTER",
                    captureTimeSeconds: 7.0);

                host.AcceptPose(observation);
                AnchorPolicyOutput output = host.Advance(10.1);

                Assert.That(output.State, Is.Not.EqualTo(AnchorState.Lost));
                Assert.That(host.ConsumeServerReacquireRequest(), Is.False);
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(go);
            }
        }

        /// <summary>
        /// 位于状态提示 floor 和重注册阈值之间的分数只应降级显示，不应触发 Python 重新 register。
        /// </summary>
        [Test]
        public void ScoreBetweenDisplayFloorAndReacquireThresholdDoesNotRequestServerReacquire()
        {
            GameObject go = new GameObject("AnchorPolicyHostTests");
            try
            {
                AnchorPolicyHost host = go.AddComponent<AnchorPolicyHost>();
                ConstantVelocityModel model = go.AddComponent<ConstantVelocityModel>();
                RawPassthroughStrategy smoothing = go.AddComponent<RawPassthroughStrategy>();
                SetPrivateField(host, "motionModel", model);
                SetPrivateField(host, "smoothingStrategy", smoothing);

                host.AcceptPose(AnchorObservation.FromAlignedPose(
                    frameId: 1,
                    worldPose: new Pose(Vector3.zero, Quaternion.identity),
                    sampleTimeSeconds: 10.0,
                    reliabilityScore: 1.0f,
                    captureTimeSeconds: 10.0));

                host.AcceptPose(AnchorObservation.FromAlignedPose(
                    frameId: 2,
                    worldPose: new Pose(new Vector3(0.01f, 0.0f, 0.0f), Quaternion.identity),
                    sampleTimeSeconds: 10.1,
                    reliabilityScore: 0.48f,
                    captureTimeSeconds: 10.1,
                    scoreDepth: 0.9f,
                    scoreReprojection: 0.9f,
                    hasSubscores: true,
                    depthValid: true,
                    reprojValid: true));

                AnchorPolicyDecision decision = host.AcceptPose(AnchorObservation.FromAlignedPose(
                    frameId: 3,
                    worldPose: new Pose(new Vector3(0.02f, 0.0f, 0.0f), Quaternion.identity),
                    sampleTimeSeconds: 10.8,
                    reliabilityScore: 0.48f,
                    captureTimeSeconds: 10.8,
                    scoreDepth: 0.9f,
                    scoreReprojection: 0.9f,
                    hasSubscores: true,
                    depthValid: true,
                    reprojValid: true));

                Assert.That(decision.Action, Is.Not.EqualTo(AnchorPolicyAction.Reacquire));
                Assert.That(host.ConsumeServerReacquireRequest(), Is.False);
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(go);
            }
        }

        /// <summary>
        /// 低总分持续超过阈值后必须本地重置；是否请求 Python 由独立开关控制。
        /// </summary>
        [TestCase(true, true)]
        [TestCase(false, false)]
        public void SustainedLowScoreSeparatesLocalResetFromServerRequest(
            bool emitServerReacquire,
            bool expectedServerRequest)
        {
            GameObject go = new GameObject("AnchorPolicyHostTests");
            try
            {
                AnchorPolicyHost host = go.AddComponent<AnchorPolicyHost>();
                ConstantVelocityModel model = go.AddComponent<ConstantVelocityModel>();
                RawPassthroughStrategy smoothing = go.AddComponent<RawPassthroughStrategy>();
                SetPrivateField(host, "motionModel", model);
                SetPrivateField(host, "smoothingStrategy", smoothing);
                SetPrivateField(host, "emitServerReacquire", emitServerReacquire);

                host.AcceptPose(AnchorObservation.FromAlignedPose(
                    frameId: 1,
                    worldPose: new Pose(Vector3.zero, Quaternion.identity),
                    sampleTimeSeconds: 10.0,
                    reliabilityScore: 1.0f,
                    captureTimeSeconds: 10.0));

                AnchorObservation lowScoreWithGoodGeometry = AnchorObservation.FromAlignedPose(
                    frameId: 2,
                    worldPose: new Pose(new Vector3(0.01f, 0.0f, 0.0f), Quaternion.identity),
                    sampleTimeSeconds: 10.1,
                    reliabilityScore: 0.44f,
                    captureTimeSeconds: 10.1,
                    scoreDepth: 0.9f,
                    scoreReprojection: 0.9f,
                    hasSubscores: true,
                    depthValid: true,
                    reprojValid: true);

                host.AcceptPose(lowScoreWithGoodGeometry);
                AnchorPolicyDecision decision = host.AcceptPose(AnchorObservation.FromAlignedPose(
                    frameId: 3,
                    worldPose: new Pose(new Vector3(0.02f, 0.0f, 0.0f), Quaternion.identity),
                    sampleTimeSeconds: 10.6,
                    reliabilityScore: 0.44f,
                    captureTimeSeconds: 10.6,
                    scoreDepth: 0.9f,
                    scoreReprojection: 0.9f,
                    hasSubscores: true,
                    depthValid: true,
                    reprojValid: true));

                Assert.That(decision.Action, Is.Not.EqualTo(AnchorPolicyAction.Reacquire));
                Assert.That(host.ConsumeServerReacquireRequest(), Is.False);

                decision = host.AcceptPose(AnchorObservation.FromAlignedPose(
                    frameId: 4,
                    worldPose: new Pose(new Vector3(0.03f, 0.0f, 0.0f), Quaternion.identity),
                    sampleTimeSeconds: 10.75,
                    reliabilityScore: 0.44f,
                    captureTimeSeconds: 10.75,
                    scoreDepth: 0.9f,
                    scoreReprojection: 0.9f,
                    hasSubscores: true,
                    depthValid: true,
                    reprojValid: true));

                Assert.That(decision.Action, Is.EqualTo(AnchorPolicyAction.Reacquire));
                Assert.That(host.ConsumeServerReacquireRequest(), Is.EqualTo(expectedServerRequest));
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(go);
            }
        }

        /// <summary>
        /// Lost/低分请求可能在 LateUpdate 中产生；hub 必须不依赖下一条 PoseResult 也能消费该请求。
        /// </summary>
        [Test]
        public void HubLateUpdateConsumesPendingServerReacquireRequests()
        {
            GameObject go = new GameObject("AnchorRuntimeHubTests");
            try
            {
                AnchorPolicyHost host = go.AddComponent<AnchorPolicyHost>();
                PoseToAnchorRuntime runtime = go.AddComponent<PoseToAnchorRuntime>();
                AnchorRuntimeHub hub = go.AddComponent<AnchorRuntimeHub>();
                SetPrivateField(runtime, "policyHost", host);
                SetPrivateField(hub, "runtimes", new List<PoseToAnchorRuntime> { runtime });
                SetPrivateField(host, "wantsServerReacquire", true);

                MethodInfo lateUpdate = typeof(AnchorRuntimeHub).GetMethod("LateUpdate", BindingFlags.Instance | BindingFlags.NonPublic);
                Assert.That(lateUpdate, Is.Not.Null, "AnchorRuntimeHub 应在 LateUpdate 中消费 runtime reacquire 请求。");
                lateUpdate.Invoke(hub, Array.Empty<object>());

                Assert.That(host.ConsumeServerReacquireRequest(), Is.False);
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(go);
            }
        }

        /// <summary>
        /// Python 合并状态 valid_no_valid_depth_overlap 表示颜色有效但深度无交集；Unity 几何仲裁也必须排除 D 项。
        /// </summary>
        [Test]
        public void MapperExcludesMergedInvalidDepthStatusFromGeometryEvidence()
        {
            PoseResult result = new PoseResult
            {
                ReliabilityScore = 0.4f,
                ScoreDepth = 0.0f,
                ScoreReprojection = 1.0f,
                ColorReprojection = -1.0f,
                DepthValidInMask = 1.0f,
                RenderQualityStatus = "valid_no_valid_depth_overlap",
                RenderQualityDepthAlignment = 0.0f,
                RenderQualityDepthInlier = 0.0f,
                RenderQualityDepthResidualM = 0.0f,
            };

            AnchorObservation observation = InvokePolicyMapper(result);

            Assert.That(observation.DepthValid, Is.False);
            Assert.That(observation.GeometryScore(0.2f, 0.8f, out bool hasEvidence), Is.EqualTo(1.0f));
            Assert.That(hasEvidence, Is.False);
        }

        /// <summary>
        /// 反射设置 MonoBehaviour 私有序列化字段，避免测试依赖场景 YAML。
        /// </summary>
        private static void SetPrivateField<T>(object instance, string fieldName, T value)
        {
            FieldInfo field = instance.GetType().GetField(fieldName, BindingFlags.Instance | BindingFlags.NonPublic);
            Assert.That(field, Is.Not.Null, $"missing field {fieldName}");
            field.SetValue(instance, value);
        }

        /// <summary>
        /// 反射读取私有字段，供不依赖场景 YAML 的契约测试复用。
        /// </summary>
        private static T GetPrivateField<T>(object instance, string fieldName)
        {
            FieldInfo field = instance.GetType().GetField(fieldName, BindingFlags.Instance | BindingFlags.NonPublic);
            Assert.That(field, Is.Not.Null, $"missing field {fieldName}");
            return (T)field.GetValue(instance);
        }

        /// <summary>反射调用私有静态格式化方法，避免为测试扩大运行时 API。</summary>
        private static T InvokePrivateStaticMethod<T>(Type type, string methodName, params object[] arguments)
        {
            MethodInfo method = type.GetMethod(methodName, BindingFlags.Static | BindingFlags.NonPublic);
            Assert.That(method, Is.Not.Null, $"missing method {methodName}");
            return (T)method.Invoke(null, arguments);
        }

        /// <summary>反射调用评估快照构建，避免为测试扩大生产 API。</summary>
        private static void InvokeBuildSnapshots(EvalRecorder recorder)
        {
            MethodInfo buildSnapshots = typeof(EvalRecorder).GetMethod("BuildSnapshots", BindingFlags.Instance | BindingFlags.NonPublic);
            Assert.That(buildSnapshots, Is.Not.Null);
            buildSnapshots.Invoke(recorder, Array.Empty<object>());
        }

        /// <summary>读取组件声明的 Unity 默认执行顺序。</summary>
        private static int ReadExecutionOrder<T>() where T : MonoBehaviour
        {
            DefaultExecutionOrder attribute = typeof(T).GetCustomAttribute<DefaultExecutionOrder>();
            Assert.That(attribute, Is.Not.Null, $"{typeof(T).Name} 缺少 DefaultExecutionOrder。");
            return attribute.order;
        }

        /// <summary>
        /// 构造包含新时间诊断字段的最小评估快照。
        /// </summary>
        private static EvalVariantSnapshot CreateTimingSnapshot(
            double policyOutputTargetMonoMs = 1880.0,
            double smoothingDelayMs = 120.0)
        {
            return new EvalVariantSnapshot(
                label: "primary", isPrimary: true, sourceFrameId: 42,
                hasRuntimeOutput: true, hasDisplayPose: true, displayPose: Pose.identity, anchorPoseSource: "transform",
                hasSourceCaptureTiming: true, sourceCaptureMonoMs: 1000.0, sourceCaptureUnityFrame: 10,
                observationAgeMs: 120.0, policyOutputTargetMonoMs: policyOutputTargetMonoMs, smoothingDelayMs: smoothingDelayMs,
                unityPoseHandleMonoMs: 1500.0,
                anchorState: "Tracking", policyAction: "Accept", policyReason: "accept",
                latestPhase: "TRACK", latestFailure: string.Empty, motionState: "Static", predictAheadMs: 120.0,
                strategyLabel: "test", qualityGate: "disabled", motionModel: "constant_velocity", smoothingStrategy: "raw_passthrough",
                configHash: "hash", residualMeters: float.NaN, residualDegrees: float.NaN, acceptedScore: 1.0f, staticLocked: false,
                hasAlignedRaw: true, alignedRawPose: Pose.identity,
                hasArrivalTimeRaw: false, arrivalTimeRawPose: Pose.identity,
                arrivalTimeRawMonoMs: double.NaN, arrivalTimeRawUnityFrame: -1, arrivalTimeCameraReference: "Left",
                reliabilityScore: 1.0f);
        }

        /// <summary>
        /// 通过反射调用 internal mapper，避免为了测试扩大运行时代码可见性。
        /// </summary>
        private static AnchorObservation InvokePolicyMapper(PoseResult result)
        {
            Type mapperType = typeof(AnchorObservation).Assembly.GetType("EgoAnchor.Runtime.PoseResultPolicyMapper");
            Assert.That(mapperType, Is.Not.Null, "missing PoseResultPolicyMapper");
            MethodInfo method = mapperType.GetMethod("FromAlignedPose", BindingFlags.Public | BindingFlags.Static);
            Assert.That(method, Is.Not.Null, "missing FromAlignedPose");

            object[] args =
            {
                42L,
                new Pose(Vector3.zero, Quaternion.identity),
                10.0,
                7.0,
                result,
                "TRACK",
                false,
                default(Pose),
            };
            return (AnchorObservation)method.Invoke(null, args);
        }
    }
}

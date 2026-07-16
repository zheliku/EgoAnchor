using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Text.RegularExpressions;
using EgoAnchor.Alignment;
using EgoAnchor.Eval;
using EgoAnchor.Policy;
using EgoAnchor.Protocol.Generated;
using EgoAnchor.Runtime;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;

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
        /// runtime 输出与显示 Transform 必须分别记录，不能因同帧采样而混用字段。
        /// </summary>
        [Test]
        public void RecorderSnapshotSeparatesRuntimeOutputAndDisplayPose()
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
                SetPrivateField(host, "enableQualityGate", true);
                SetPrivateField(runtime, "policyHost", host);
                host.Bind(runtime);

                Pose runtimePose = new Pose(Vector3.one, Quaternion.identity);
                runtime.AcceptWorldPose(42, runtimePose);
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
                Assert.That(snapshots[0].HasRuntimeOutput, Is.True);
                Assert.That(snapshots[0].RuntimeOutputPose.position, Is.EqualTo(runtimePose.position));
                Assert.That(Quaternion.Angle(snapshots[0].RuntimeOutputPose.rotation, runtimePose.rotation), Is.LessThan(1e-4f));
                Assert.That(snapshots[0].DisplayPose.position, Is.EqualTo(expected.position));
                Assert.That(Quaternion.Angle(snapshots[0].DisplayPose.rotation, expected.rotation), Is.LessThan(1e-4f));

                string json = EvalJson.BuildRenderLine(
                    renderMonoMs: 2000.0,
                    renderUnixMs: 3000.0,
                    renderUnityFrame: 20,
                    headPose: Pose.identity,
                    referencePose: new EvalReferencePose(false, false, false, Pose.identity, double.NaN),
                    referenceLinearSpeedMs: 0f,
                    referenceAngularSpeedDegS: 0f,
                    variant: snapshots[0]);
                StringAssert.Contains("\"output_pos\":[1,1,1]", json);
                StringAssert.Contains("\"display_pos\":[4,5,6]", json);
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

            string json = EvalJson.BuildRenderLine(
                renderMonoMs: 2000.0,
                renderUnixMs: 3000.0,
                renderUnityFrame: 20,
                headPose: Pose.identity,
                referencePose: new EvalReferencePose(false, false, false, Pose.identity, double.NaN),
                referenceLinearSpeedMs: 0f,
                referenceAngularSpeedDegS: 0f,
                variant: snapshot);

            StringAssert.Contains("\"policy_output_target_mono_ms\":null", json);
            StringAssert.Contains("\"smoothing_delay_ms\":null", json);
        }

        /// <summary>
        /// Transform 仍保留旧 pose 时，若 runtime 已没有 policy 输出，快照仍须保留显示来源帧且不得伪报有效输出。
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
                Assert.That(snapshots[0].HasRuntimeOutput, Is.False);
                Assert.That(snapshots[0].HasDisplayPose, Is.True);
                Assert.That(snapshots[0].SourceFrameId, Is.EqualTo(42L));
                Assert.That(snapshots[0].AnchorPoseSource, Is.EqualTo("hold_last"));
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

            string json = EvalJson.BuildRenderLine(
                renderMonoMs: 2000.0,
                renderUnixMs: 3000.0,
                renderUnityFrame: 20,
                headPose: Pose.identity,
                referencePose: new EvalReferencePose(false, false, false, Pose.identity, double.NaN),
                referenceLinearSpeedMs: 0f,
                referenceAngularSpeedDegS: 0f,
                variant: snapshot);

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
            string json = EvalJson.BuildReferenceLine(
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
                gtSample: new EvalReferencePose(true, true, false, Pose.identity, 0.0),
                cameraReference: "Left");

            StringAssert.Contains("\"image_time_basis\":\"camera_pose_history_proxy\"", json);
            StringAssert.Contains("\"image_time_offset_frames\":1", json);
            StringAssert.Contains("\"publish_attempt_mono_ms\":1040", json);
            StringAssert.Contains("\"publish_succeeded\":true", json);
            StringAssert.Contains("\"reference_pose_fresh\":true", json);
            StringAssert.Contains("\"reference_pose_keep_alive\":false", json);
            StringAssert.Contains("\"reference_pose_fresh_age_ms\":0", json);
        }

        /// <summary>动态模式必须在丢跟时立即判参考无效，静止模式仍可在窗口内复用最后新鲜 pose。</summary>
        [Test]
        public void ReferencePoseTrackerSeparatesFreshOnlyAndStaticKeepAlive()
        {
            var tracker = new EvalReferencePoseTracker();
            Pose pose = new Pose(new Vector3(1f, 2f, 3f), Quaternion.identity);

            EvalReferencePose fresh = tracker.Resolve(
                true, pose, true, 1000.0,
                EvalReferenceFreshnessMode.RequireFreshTracking, 30_000.0);
            EvalReferencePose dynamicLost = tracker.Resolve(
                true, pose, false, 1100.0,
                EvalReferenceFreshnessMode.RequireFreshTracking, 30_000.0);
            EvalReferencePose staticSleep = tracker.Resolve(
                true, pose, false, 1200.0,
                EvalReferenceFreshnessMode.AllowStaticKeepAlive, 30_000.0);

            Assert.That(fresh.Valid, Is.True);
            Assert.That(fresh.Fresh, Is.True);
            Assert.That(dynamicLost.Valid, Is.False);
            Assert.That(dynamicLost.FreshAgeMs, Is.EqualTo(100.0));
            Assert.That(staticSleep.Valid, Is.True);
            Assert.That(staticSleep.KeepAlive, Is.True);
            Assert.That(staticSleep.FreshAgeMs, Is.EqualTo(200.0));
            Assert.That(staticSleep.Pose.position, Is.EqualTo(pose.position));
        }

        /// <summary>后台日志使用有界队列，饱和时必须计数，关闭时必须写完已入队数据。</summary>
        [Test]
        public void EvalLogCountsDroppedRowsAndFlushesQueuedRowsOnDispose()
        {
            string directory = Path.Combine(Application.temporaryCachePath, $"egoanchor_eval_log_{Guid.NewGuid():N}");
            string path = Path.Combine(directory, "test.jsonl");
            Directory.CreateDirectory(directory);
            try
            {
                Type logType = typeof(EvalRecorder).Assembly.GetType("EgoAnchor.Eval.EvalLog");
                Assert.That(logType, Is.Not.Null);
                ConstructorInfo constructor = logType.GetConstructor(
                    BindingFlags.Instance | BindingFlags.NonPublic,
                    null,
                    new[] { typeof(string), typeof(int), typeof(int), typeof(int), typeof(bool) },
                    null);
                Assert.That(constructor, Is.Not.Null);
                object log = constructor.Invoke(new object[] { path, 1, 64, 1000, false });
                MethodInfo write = logType.GetMethod("Write", BindingFlags.Instance | BindingFlags.Public);
                MethodInfo dispose = logType.GetMethod("Dispose", BindingFlags.Instance | BindingFlags.Public);
                Assert.That(write, Is.Not.Null);
                Assert.That(dispose, Is.Not.Null);

                write.Invoke(log, new object[] { "{\"row\":1}" });
                write.Invoke(log, new object[] { "{\"row\":2}" });
                dispose.Invoke(log, Array.Empty<object>());

                object stats = logType.GetProperty("Stats", BindingFlags.Instance | BindingFlags.Public)?.GetValue(log);
                Assert.That(stats, Is.Not.Null);
                long dropped = (long)stats.GetType().GetField("DroppedRows")?.GetValue(stats);
                long written = (long)stats.GetType().GetField("RowsWritten")?.GetValue(stats);
                int peak = (int)stats.GetType().GetField("PeakQueueDepth")?.GetValue(stats);
                Assert.That(dropped, Is.EqualTo(1L));
                Assert.That(written, Is.EqualTo(1L));
                Assert.That(peak, Is.EqualTo(1));
                Assert.That(File.ReadAllLines(path), Is.EqualTo(new[] { "{\"row\":1}" }));
            }
            finally
            {
                if (Directory.Exists(directory)) Directory.Delete(directory, true);
            }
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
                SetPrivateField(host, "enableQualityGate", true);
                SetPrivateField(runtime, "policyHost", host);
                SetPrivateField(recorder, "variants", new List<EvalVariant>
                {
                    new EvalVariant
                    {
                        label = "ZOH",
                        runtime = runtime,
                        anchorTransform = runtimeGo.transform,
                        isPrimary = true,
                    },
                });

                string admissionPath = Path.Combine(directory, "unity_admission.jsonl");
                string eventsPath = Path.Combine(directory, "unity_events.jsonl");
                recorder.BeginRecording(capturePath, admissionPath, outputPath, eventsPath);
                var configsBeforeDestroy = new List<EvalVariantConfig>();
                recorder.CollectVariantConfigs(configsBeforeDestroy);
                Assert.That(configsBeforeDestroy, Has.Count.EqualTo(1));
                string expectedConfigHash = configsBeforeDestroy[0].ConfigHash;
                UnityEngine.Object.DestroyImmediate(runtimeGo);
                recorder.StopRecording();

                var labels = new List<string>();
                var configs = new List<EvalVariantConfig>();
                recorder.CollectVariantLabels(labels);
                recorder.CollectVariantConfigs(configs);

                Assert.That(labels, Is.EqualTo(new[] { "ZOH" }));
                Assert.That(configs, Has.Count.EqualTo(1));
                Assert.That(configs[0].MotionModel, Is.EqualTo("cv"));
                Assert.That(configs[0].SmoothingStrategy, Is.EqualTo("raw_passthrough"));
                Assert.That(configs[0].QualityGate, Is.EqualTo("enabled"));
                Assert.That(configs[0].UsesVcdAdmission, Is.True);
                Assert.That(configs[0].ConfigHash, Is.EqualTo(expectedConfigHash));
            }
            finally
            {
                if (runtimeGo != null) UnityEngine.Object.DestroyImmediate(runtimeGo);
                UnityEngine.Object.DestroyImmediate(recorderGo);
                if (Directory.Exists(directory)) Directory.Delete(directory, true);
            }
        }

        /// <summary>同一 Python session 的非空 Unity 日志存在时，重新开始录制必须拒绝覆盖。</summary>
        [Test]
        public void EvalSessionRefusesToOverwriteExistingPythonSessionLogs()
        {
            GameObject go = new GameObject("EvalSessionOverwriteTests");
            string root = Path.Combine(Application.temporaryCachePath, $"egoanchor_session_{Guid.NewGuid():N}");
            const string sessionId = "20260711_120000_controller_right";
            string sessionDir = Path.Combine(root, sessionId);
            string capturePath = Path.Combine(sessionDir, "unity_reference.jsonl");
            string outputPath = Path.Combine(sessionDir, "unity_render.jsonl");
            Directory.CreateDirectory(sessionDir);
            File.WriteAllText(capturePath, "capture-existing");
            File.WriteAllText(outputPath, "output-existing");

            try
            {
                EvalRecorder recorder = go.AddComponent<EvalRecorder>();
                AnchorRuntimeHub hub = go.AddComponent<AnchorRuntimeHub>();
                EvalSession session = go.AddComponent<EvalSession>();
                SetPrivateField(hub, "latestPythonSessionId", sessionId);
                SetPrivateField(session, "recorder", recorder);
                SetPrivateField(session, "runtimeHub", hub);
                SetPrivateField(session, "outputRoot", root);

                LogAssert.Expect(LogType.Error, new Regex("Session 启动已拒绝.*禁止覆盖"));
                session.StartSession();

                Assert.That(session.IsRecording, Is.False);
                Assert.That(File.ReadAllText(capturePath), Is.EqualTo("capture-existing"));
                Assert.That(File.ReadAllText(outputPath), Is.EqualTo("output-existing"));
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(go);
                if (Directory.Exists(root)) Directory.Delete(root, true);
            }
        }

        /// <summary>同一个已拒绝的 Python session 只记录一次阻断，避免 LateUpdate 每秒刷屏。</summary>
        [Test]
        public void EvalSessionSuppressesRepeatedRejectForSamePythonSession()
        {
            GameObject go = new GameObject("EvalSessionRepeatedRejectTests");
            string root = Path.Combine(Application.temporaryCachePath, $"egoanchor_session_repeat_{Guid.NewGuid():N}");
            const string sessionId = "20260711_120500_controller_right";
            string sessionDir = Path.Combine(root, sessionId);
            Directory.CreateDirectory(sessionDir);
            File.WriteAllText(Path.Combine(sessionDir, "unity_reference.jsonl"), "capture-existing");

            try
            {
                EvalRecorder recorder = go.AddComponent<EvalRecorder>();
                AnchorRuntimeHub hub = go.AddComponent<AnchorRuntimeHub>();
                EvalSession session = go.AddComponent<EvalSession>();
                SetPrivateField(hub, "latestPythonSessionId", sessionId);
                SetPrivateField(session, "recorder", recorder);
                SetPrivateField(session, "runtimeHub", hub);
                SetPrivateField(session, "outputRoot", root);

                LogAssert.Expect(LogType.Error, new Regex("Session 启动已拒绝.*禁止覆盖"));
                session.StartSession();
                session.StartSession();

                Assert.That(session.IsRecording, Is.False);
                Assert.That(
                    session.SessionStatusMessage,
                    Is.EqualTo("PYTHON SESSION ALREADY HAS UNITY LOGS - RESTART PYTHON"));

                const string nextSessionId = "20260711_120501_controller_right";
                SetPrivateField(hub, "latestPythonSessionId", nextSessionId);
                session.StartSession();
                Assert.That(session.IsRecording, Is.True);
                session.StopSession();
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(go);
                if (Directory.Exists(root)) Directory.Delete(root, true);
            }
        }

        /// <summary>已有 manifest 即代表 session 已结束，Unity 不得覆盖审计元数据后重新录制。</summary>
        [Test]
        public void EvalSessionRefusesToOverwriteExistingManifest()
        {
            GameObject go = new GameObject("EvalSessionManifestOverwriteTests");
            string root = Path.Combine(Application.temporaryCachePath, $"egoanchor_manifest_{Guid.NewGuid():N}");
            const string sessionId = "20260711_121000_controller_right";
            string sessionDir = Path.Combine(root, sessionId);
            string manifestPath = Path.Combine(sessionDir, "manifest.json");
            Directory.CreateDirectory(sessionDir);
            File.WriteAllText(manifestPath, "{\"schema_version\":2}");

            try
            {
                EvalRecorder recorder = go.AddComponent<EvalRecorder>();
                AnchorRuntimeHub hub = go.AddComponent<AnchorRuntimeHub>();
                EvalSession session = go.AddComponent<EvalSession>();
                SetPrivateField(hub, "latestPythonSessionId", sessionId);
                SetPrivateField(session, "recorder", recorder);
                SetPrivateField(session, "runtimeHub", hub);
                SetPrivateField(session, "outputRoot", root);

                LogAssert.Expect(LogType.Error, new Regex("Session 启动已拒绝.*禁止覆盖"));
                session.StartSession();

                Assert.That(session.IsRecording, Is.False);
                Assert.That(File.ReadAllText(manifestPath), Is.EqualTo("{\"schema_version\":2}"));
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(go);
                if (Directory.Exists(root)) Directory.Delete(root, true);
            }
        }

        /// <summary>Python 已写入远端事件分片时，Unity 只写本机独占分片。</summary>
        [Test]
        public void EvalSessionWritesIndependentUnityEventFragment()
        {
            GameObject go = new GameObject("EvalSessionEventFragmentTests");
            string root = Path.Combine(Application.temporaryCachePath, $"egoanchor_events_{Guid.NewGuid():N}");
            const string sessionId = "20260711_130000_controller_right";
            string sessionDir = Path.Combine(root, sessionId);
            string pythonEventsPath = Path.Combine(sessionDir, "python_events.jsonl");
            string unityEventsPath = Path.Combine(sessionDir, "unity_events.jsonl");
            Directory.CreateDirectory(sessionDir);
            const string pythonEvent = "{\"schema_version\":2,\"event\":\"runtime_started\",\"event_type\":\"runtime_started\",\"session_id\":\"20260711_130000_controller_right\",\"source\":\"python_runtime\",\"created_unix_ms\":1,\"mono_ms\":1,\"unity_frame\":-1,\"severity\":\"info\",\"experiment_id\":\"\",\"scenario_id\":\"\",\"trial_id\":\"\",\"event_id\":\"\",\"variant_id\":\"\",\"message\":\"\",\"payload\":{}}";
            File.WriteAllText(pythonEventsPath, pythonEvent + Environment.NewLine);

            try
            {
                EvalRecorder recorder = go.AddComponent<EvalRecorder>();
                AnchorRuntimeHub hub = go.AddComponent<AnchorRuntimeHub>();
                EvalSession session = go.AddComponent<EvalSession>();
                SetPrivateField(hub, "latestPythonSessionId", sessionId);
                SetPrivateField(session, "recorder", recorder);
                SetPrivateField(session, "runtimeHub", hub);
                SetPrivateField(session, "outputRoot", root);

                session.StartSession();
                Assert.That(session.IsRecording, Is.True);
                session.StopSession();

                Assert.That(File.ReadAllText(pythonEventsPath), Is.EqualTo(pythonEvent + Environment.NewLine));
                string unityEvents = File.ReadAllText(unityEventsPath);
                StringAssert.Contains("\"event\":\"session_started\"", unityEvents);
                StringAssert.Contains("\"event\":\"session_stopped\"", unityEvents);
                Assert.That(File.Exists(Path.Combine(sessionDir, "events.jsonl")), Is.False);
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(go);
                if (Directory.Exists(root)) Directory.Delete(root, true);
            }
        }

        /// <summary>Formal 现场不再暴露需要逐次填写的审计字段。</summary>
        [Test]
        public void FormalSessionDoesNotExposeManualMetadataFields()
        {
            foreach (string fieldName in new[]
            {
                "runMode",
                "operatorId",
                "frozenParameterSetId",
                "objectModelId",
                "egoanchorGitCommit",
                "protocolVersion",
                "notes",
            })
            {
                Assert.That(
                    typeof(EvalSession).GetField(fieldName, BindingFlags.Instance | BindingFlags.NonPublic),
                    Is.Null,
                    $"manual field should not be serialized: {fieldName}");
            }
        }

        /// <summary>即使 Formal 元数据齐全，没有任何变体配置也不得开始正式采集。</summary>
        [Test]
        public void FormalSessionRejectsMissingVariantConfigs()
        {
            GameObject go = new GameObject("EvalFormalVariantConfigTests");
            try
            {
                EvalRecorder recorder = go.AddComponent<EvalRecorder>();
                EvalSession session = go.AddComponent<EvalSession>();
                SetPrivateField(session, "recorder", recorder);
                SetPrivateField(session, "runKind", EvalRunKind.Formal);

                LogAssert.Expect(LogType.Error, new Regex("Formal session 启动已拒绝.*variantConfigs"));
                session.StartSession();

                Assert.That(session.IsRecording, Is.False);
                Assert.That(session.SessionId, Is.Null.Or.Empty);
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(go);
            }
        }

        /// <summary>重复 label 会破坏 admission 去重和 config hash 映射，正式采集前必须拒绝。</summary>
        [Test]
        public void RecorderRejectsDuplicateVariantLabels()
        {
            GameObject go = new GameObject("EvalDuplicateVariantTests");
            try
            {
                EvalRecorder recorder = go.AddComponent<EvalRecorder>();
                PoseToAnchorRuntime runtimeA = go.AddComponent<PoseToAnchorRuntime>();
                PoseToAnchorRuntime runtimeB = go.AddComponent<PoseToAnchorRuntime>();
                SetPrivateField(recorder, "variants", new List<EvalVariant>
                {
                    new EvalVariant { label = "duplicate", runtime = runtimeA },
                    new EvalVariant { label = "duplicate", runtime = runtimeB },
                });

                Assert.That(recorder.TryValidateCurrentVariants(out string error), Is.False);
                Assert.That(error, Is.EqualTo("duplicateVariantLabel[duplicate]"));
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(go);
            }
        }

        /// <summary>admission 必须表达策略是否接纳，而不是只表达 world alignment 是否成功。</summary>
        [TestCase("Accept", "accepted")]
        [TestCase("Snap", "accepted")]
        [TestCase("Reject", "rejected")]
        [TestCase("Reacquire", "rejected")]
        public void AdmissionDecisionUsesPolicyOutcome(string policyAction, string expected)
        {
            MethodInfo method = typeof(EvalRecorder).GetMethod(
                "ToAdmissionDecision", BindingFlags.Static | BindingFlags.NonPublic);
            Assert.That(method, Is.Not.Null);
            Assert.That(
                method.Invoke(null, new object[] { PoseToAnchorRuntime.AcceptResult.Aligned, policyAction }),
                Is.EqualTo(expected));
        }

        /// <summary>同一 PoseResult 的八个回调共用 ID，同 frame 的下一候选序号递增。</summary>
        [Test]
        public void RecorderCandidateIdUsesResultIdentityAndFrameLocalSequence()
        {
            GameObject go = new GameObject("EvalCandidateIdTests");
            try
            {
                EvalRecorder recorder = go.AddComponent<EvalRecorder>();
                SetPrivateField(recorder, "_sessionId", "session");
                MethodInfo build = typeof(EvalRecorder).GetMethod(
                    "BuildCandidateId", BindingFlags.Instance | BindingFlags.NonPublic);
                Assert.That(build, Is.Not.Null);

                PoseResult first = NewPoseResult(11);
                PoseResult second = NewPoseResult(11);
                PoseResult otherFrame = NewPoseResult(12);
                Assert.That(build.Invoke(recorder, new object[] { first }), Is.EqualTo("session:11:1"));
                Assert.That(build.Invoke(recorder, new object[] { first }), Is.EqualTo("session:11:1"));
                Assert.That(build.Invoke(recorder, new object[] { second }), Is.EqualTo("session:11:2"));
                Assert.That(build.Invoke(recorder, new object[] { otherFrame }), Is.EqualTo("session:12:1"));
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(go);
            }
        }

        /// <summary>manifest 必须持久化后台队列丢行数与峰值，供正式采集后验收。</summary>
        [Test]
        public void EvalManifestWritesLogQueueStats()
        {
            string json = EvalJson.BuildManifest(
                new EvalManifestMetadata(
                    "session", "object", "debug", string.Empty, 1, "editor",
                    string.Empty, "unity", string.Empty, "commit", "v1", string.Empty, string.Empty, string.Empty),
                Array.Empty<string>(), Array.Empty<EvalVariantConfig>(),
                referenceStats: new EvalLogStats(2, 8, null, 10),
                admissionStats: new EvalLogStats(1, 4, null, 20),
                renderStats: new EvalLogStats(3, 16, null, 30),
                eventsStats: new EvalLogStats(0, 2, null, 4));

            StringAssert.Contains("\"unity_reference.jsonl\":{\"rows_written\":10,\"dropped_rows\":2,\"peak_queue_depth\":8", json);
            StringAssert.Contains("\"unity_admission.jsonl\":{\"rows_written\":20,\"dropped_rows\":1,\"peak_queue_depth\":4", json);
            StringAssert.Contains("\"unity_render.jsonl\":{\"rows_written\":30,\"dropped_rows\":3,\"peak_queue_depth\":16", json);
            StringAssert.Contains("\"events.jsonl\":{\"rows_written\":null,\"dropped_rows\":null", json);
            StringAssert.Contains("\"unity\":{\"rows_written\":4,\"dropped_rows\":0,\"peak_queue_depth\":2", json);
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

        /// <summary>构造带 frame id 的最小 PoseResult。</summary>
        private static PoseResult NewPoseResult(long frameId)
        {
            return new PoseResult { Header = new MessageHeader { FrameId = frameId } };
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
                hasRuntimeOutput: true, runtimeOutputPose: Pose.identity,
                hasDisplayPose: true, displayPose: Pose.identity, anchorPoseSource: "transform",
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

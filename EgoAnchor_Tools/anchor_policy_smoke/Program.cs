using System;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Threading;
using System.Threading.Tasks;
using EgoAnchor.Alignment;
using EgoAnchor.Client;
using EgoAnchor.Diagnostics;
using EgoAnchor.Policy;
using EgoAnchor.Protocol.Generated;
using EgoAnchor.Runtime;
using EgoAnchor.Transport;
using UnityEngine;

static class Program
{
    /// <summary>pose 消息间隔（约 15Hz 感知流）。</summary>
    private const double MsgDt = 1.0 / 15.0;

    /// <summary>渲染帧间隔（约 90Hz Advance）。</summary>
    private const double FrameDt = 1.0 / 90.0;

    private static int Main()
    {
        // ===== 统一自适应控制器场景断言 =====
        AssertFirstPoseSnaps();
        AssertStaticJitterSuppression();
        AssertMovingResponseAndPerFrameOutput();
        AssertScoreHysteresis();
        AssertLowScoreDoesNotDrag();
        AssertTeleportRecovery();
        AssertCoastWithoutMessages();
        AssertRelocalizeSnap();
        AssertStaleMeasurementIgnored();
        AssertConfigHotReload();
        AssertRotationFilterGates();
        AssertNotifyChain();

        // ===== frame-aligned 数学与坐标补偿断言 =====
        Pose objectWorldPose = new Pose(new Vector3(0.35f, 0.05f, 1.2f), YawDegrees(25f));
        Pose firstCameraPose = new Pose(Vector3.zero, Quaternion.identity);
        Pose rotatedCameraPose = new Pose(Vector3.zero, YawDegrees(35f));
        Pose firstLocalPose = WorldToCameraLocal(firstCameraPose, objectWorldPose);
        Pose rotatedLocalPose = WorldToCameraLocal(rotatedCameraPose, objectWorldPose);
        Pose alignedFirst = CameraLocalToWorld(firstCameraPose, firstLocalPose);
        Pose alignedRotated = CameraLocalToWorld(rotatedCameraPose, rotatedLocalPose);
        Assert(Vector3.Distance(alignedFirst.position, alignedRotated.position) < 0.001f, "frame-aligned position should not follow pure head rotation");
        Assert(QuaternionAngleDegrees(alignedFirst.rotation, alignedRotated.rotation) < 0.1f, "frame-aligned rotation should not follow pure head rotation");
        AssertParallelPoseOffsets();
        AssertLegacyOffsetApiRemoved();

        // ===== 服务器心跳/状态事件静态判定断言 =====
        ServerHeartbeat heartbeat = new ServerHeartbeat
        {
            State = "WAITING_CALIBRATION",
            InputReady = false,
            LatestStereoFrameId = 12,
            CameraInfoVersion = 0,
            CommandQueueLength = 2,
        };
        Assert(!heartbeat.InputReady, "heartbeat smoke should expose input readiness");
        Assert(!PoseToAnchorRuntime.IsErrorHeartbeat(heartbeat), "input-not-ready heartbeat without server error should not be treated as error");

        ServerHeartbeat errorStateHeartbeat = new ServerHeartbeat
        {
            State = "ERROR",
            InputReady = true,
        };
        Assert(PoseToAnchorRuntime.IsErrorHeartbeat(errorStateHeartbeat), "heartbeat ERROR state should enter local error flow even without last_error");

        ServerHeartbeat lastErrorHeartbeat = new ServerHeartbeat
        {
            State = "TRACKING",
            InputReady = true,
            LastError = new ErrorInfo { Code = "NATS_DOWN" },
        };
        Assert(PoseToAnchorRuntime.IsErrorHeartbeat(lastErrorHeartbeat), "heartbeat last_error.code should enter local error flow");

        AnchorStatusEvent status = new AnchorStatusEvent
        {
            State = "REACQUIRING",
            Event = "REACQUIRE_STARTED",
            Message = "smoke",
        };
        Assert(status.Event == "REACQUIRE_STARTED", "status smoke should expose event name");
        Assert(PoseToAnchorRuntime.IsReacquireStartedStatus(status.Event), "REACQUIRE_STARTED should enter local relocalizing flow");
        Assert(!PoseToAnchorRuntime.IsReacquireStartedStatus("REACQUIRE_SUCCEEDED"), "REACQUIRE_SUCCEEDED should not be treated as a new reacquire start");
        Assert(!PoseToAnchorRuntime.IsReacquireStartedStatus("REACQUIRE_RESTARTED"), "only the exact started event should enter local relocalizing flow");
        Assert(PoseToAnchorRuntime.IsResetAppliedStatus("RESET_APPLIED"), "RESET_APPLIED should enter local reset flow");
        Assert(!PoseToAnchorRuntime.IsResetAppliedStatus("RESET_FAILED"), "RESET_FAILED should not be treated as an applied reset");
        Assert(PoseToAnchorRuntime.IsPauseAppliedStatus("PAUSE_APPLIED"), "PAUSE_APPLIED should enter local pause flow");
        Assert(!PoseToAnchorRuntime.IsPauseAppliedStatus("PAUSE_REJECTED"), "PAUSE_REJECTED should not be treated as an applied pause");
        Assert(PoseToAnchorRuntime.IsResumeAppliedStatus("RESUME_APPLIED"), "RESUME_APPLIED should enter local resume flow");
        Assert(!PoseToAnchorRuntime.IsResumeAppliedStatus("RESUME_FAILED"), "RESUME_FAILED should not be treated as an applied resume");

        // ===== Hub / NATS / 队列 / runtime 集成断言 =====
        AssertAnchorRuntimeHubCountsOnlyActiveTargets();
        AssertAnchorRuntimeHubIsolatesRuntimeExceptions();
        AssertNatsBytesClientSubscriptionOrder();
        AssertNatsBytesClientRequestCancelsOnStop();
        AssertQueuesCanBeCleared();
        AssertNatsControlClientStopClearsPayloadQueues();
        AssertPoseRuntimeIgnoresPoseWhilePaused();
        AssertPoseRuntimeRejectsNonFinitePoseMatrix();
        AssertPolicyPathSkipsProcessors();

        Console.WriteLine("Anchor policy smoke passed.");
        return 0;
    }

    // ===================== 控制器场景 =====================

    /// <summary>S1：首条高分测量应贴合接受并进入 Tracking，输出与测量一致。</summary>
    private static void AssertFirstPoseSnaps()
    {
        PolicyController controller = new PolicyController();
        Pose pose = new Pose(new Vector3(0.3f, -0.2f, 1.0f), YawDegrees(30f));
        AnchorPolicyDecision first = controller.AcceptPose(MakeTrackObservation(1, pose, 0.0, 0.9f));
        Assert(first.Action == AnchorPolicyAction.Snap, "first reliable pose should snap-accept");
        Assert(first.State == AnchorState.Tracking, "first reliable pose should enter Tracking");

        AnchorPolicyOutput output = controller.Advance(0.01);
        Assert(output.HasPose, "first pose should produce an output");
        Assert(Vector3.Distance(output.Pose.position, pose.position) < 1e-4f, "first output should match the snapped measurement position");
        Assert(QuaternionAngleDegrees(output.Pose.rotation, pose.rotation) < 0.1f, "first output should match the snapped measurement rotation");
    }

    /// <summary>
    /// S2（PRIMARY 闸门）：静止物体 + 测量噪声下，输出抖动必须显著低于输入，
    /// 且旋转抖动必须优于旧 8/s 指数 Slerp 基线（对应实测 1.27° 问题）。
    /// </summary>
    private static void AssertStaticJitterSuppression()
    {
        PolicyController controller = new PolicyController();
        Pose truth = new Pose(new Vector3(0.3f, -0.2f, 1.0f), YawDegrees(30f));
        Lcg rng = new Lcg(20260612);
        const int messageCount = 200;
        const int warmupMessages = 100;
        const float posSigma = 0.002f;
        const float rotSigmaDeg = 0.5f;

        List<Pose> measurements = new List<Pose>(messageCount);
        for (int i = 0; i < messageCount; i++)
        {
            measurements.Add(MakeNoisyPose(truth, posSigma, rotSigmaDeg, ref rng));
        }

        List<float> inputPosErrors = new List<float>();
        List<float> inputRotErrors = new List<float>();
        List<float> outputPosErrors = new List<float>();
        List<float> outputRotErrors = new List<float>();
        double firstStaticTime = -1.0;
        Pose lastOutputPose = Pose.identity;

        for (int i = 0; i < messageCount; i++)
        {
            double t = i * MsgDt;
            controller.AcceptPose(MakeTrackObservation(i + 1, measurements[i], t, 0.9f));
            if (firstStaticTime < 0.0 && controller.MotionState == AnchorMotionState.Static)
            {
                firstStaticTime = t;
            }

            for (double ta = t + FrameDt; ta < t + MsgDt; ta += FrameDt)
            {
                AnchorPolicyOutput output = controller.Advance(ta);
                lastOutputPose = output.Pose;
                if (i >= warmupMessages)
                {
                    outputPosErrors.Add(Vector3.Distance(output.Pose.position, truth.position));
                    outputRotErrors.Add(QuaternionAngleDegrees(output.Pose.rotation, truth.rotation));
                }
            }

            if (i >= warmupMessages)
            {
                inputPosErrors.Add(Vector3.Distance(measurements[i].position, truth.position));
                inputRotErrors.Add(QuaternionAngleDegrees(measurements[i].rotation, truth.rotation));
            }
        }

        // 旧基线：8/s 指数 Slerp（AnchorKalmanPoseProcessor 的旋转通道），同一测量序列。
        Quaternion slerpRotation = measurements[0].rotation;
        List<float> slerpRotErrors = new List<float>();
        float slerpBlend = 1f - (float)Math.Exp(-8.0 * MsgDt);
        for (int i = 1; i < messageCount; i++)
        {
            slerpRotation = NlerpStep(slerpRotation, measurements[i].rotation, slerpBlend);
            if (i >= warmupMessages)
            {
                slerpRotErrors.Add(QuaternionAngleDegrees(slerpRotation, truth.rotation));
            }
        }

        float inputPosRms = Rms(inputPosErrors);
        float inputRotRms = Rms(inputRotErrors);
        float outputPosRms = Rms(outputPosErrors);
        float outputRotRms = Rms(outputRotErrors);
        float slerpRotRms = Rms(slerpRotErrors);

        Assert(firstStaticTime >= 0.0 && firstStaticTime <= 1.0, $"static mode should engage within 1s, got {firstStaticTime:F2}s");
        Assert(outputPosRms < inputPosRms * 0.3f, $"static position jitter should drop below 0.3x input (out={outputPosRms * 1000:F3}mm, in={inputPosRms * 1000:F3}mm)");
        Assert(outputRotRms < inputRotRms * 0.3f, $"static rotation jitter should drop below 0.3x input (out={outputRotRms:F3}deg, in={inputRotRms:F3}deg)");
        Assert(outputRotRms < slerpRotRms, $"static rotation jitter must beat the 8/s slerp baseline (filter={outputRotRms:F3}deg, slerp={slerpRotRms:F3}deg)");
        Assert(Vector3.Distance(lastOutputPose.position, truth.position) < 0.001f, "static output should not drift away from truth");
    }

    /// <summary>
    /// S3：匀速运动 + 120ms 管线延迟下，渲染时刻预测应显著降低误差，
    /// 且无新消息时相邻两帧输出仍连续变化（逐帧运动，而不是消息阶梯）。
    /// </summary>
    private static void AssertMovingResponseAndPerFrameOutput()
    {
        PolicyController controller = new PolicyController();
        Vector3 startPos = new Vector3(0f, 0f, 1f);
        Vector3 velocity = new Vector3(0.5f, 0f, 0f);
        Quaternion rotation = YawDegrees(10f);
        const double latency = 0.12;
        const int messageCount = 60;
        Lcg rng = new Lcg(42);

        List<float> filterErrors = new List<float>();
        List<float> rawLatchedErrors = new List<float>();
        bool sawMoving = false;
        bool sawPerFrameMotion = false;

        Pose latestArrived = Pose.identity;
        for (int k = 0; k < messageCount; k++)
        {
            double capture = k * MsgDt;
            double arrival = capture + latency;
            Pose truthAtCapture = new Pose(startPos + velocity * (float)capture, rotation);
            Pose measured = MakeNoisyPose(truthAtCapture, 0.002f, 0.3f, ref rng);
            controller.AcceptPose(MakeTrackObservation(k + 1, measured, arrival, 0.9f, capture));
            latestArrived = measured;
            sawMoving |= controller.MotionState == AnchorMotionState.Moving;

            Pose previousOutput = Pose.identity;
            bool hasPreviousOutput = false;
            double nextArrival = arrival + MsgDt;
            for (double ta = arrival + FrameDt; ta < nextArrival; ta += FrameDt)
            {
                AnchorPolicyOutput output = controller.Advance(ta);
                Vector3 truthNow = startPos + velocity * (float)ta;
                if (capture > 1.5)
                {
                    filterErrors.Add(Vector3.Distance(output.Pose.position, truthNow));
                    rawLatchedErrors.Add(Vector3.Distance(latestArrived.position, truthNow));
                    if (hasPreviousOutput && ta - arrival < 0.02 + FrameDt
                        && Vector3.Distance(output.Pose.position, previousOutput.position) > 0.001f)
                    {
                        sawPerFrameMotion = true;
                    }
                }

                previousOutput = output.Pose;
                hasPreviousOutput = true;
            }
        }

        float filterP90 = Percentile(filterErrors, 0.90f);
        float rawP90 = Percentile(rawLatchedErrors, 0.90f);
        Assert(sawMoving, "uniform motion should classify as Moving");
        Assert(sawPerFrameMotion, "consecutive Advance outputs without a new message should still move (per-frame prediction)");
        Assert(filterP90 < rawP90 * 0.5f, $"predicted output P90 error should beat arrival-latched raw by 2x (filter={filterP90 * 1000:F1}mm, raw={rawP90 * 1000:F1}mm)");
    }

    /// <summary>S4：分数滞回——已跟踪时 0.30 分仍接受；冷启动 0.30 分不接受。</summary>
    private static void AssertScoreHysteresis()
    {
        PolicyController controller = new PolicyController();
        Pose pose = new Pose(new Vector3(0.2f, 0f, 1f), Quaternion.identity);
        controller.AcceptPose(MakeTrackObservation(1, pose, 0.0, 0.9f));
        controller.AcceptPose(MakeTrackObservation(2, pose, MsgDt, 0.9f));

        AnchorPolicyDecision stayBand = controller.AcceptPose(MakeTrackObservation(3, pose, 2 * MsgDt, 0.30f));
        Assert(stayBand.Action == AnchorPolicyAction.Accept, "score 0.30 within stay band should remain accepted while tracking");

        controller.NotifyReset(1.0, "smoke");
        AnchorPolicyDecision coldStart = controller.AcceptPose(MakeTrackObservation(4, pose, 1.1, 0.30f));
        Assert(coldStart.Action == AnchorPolicyAction.Reject, "score 0.30 below enter threshold should not start tracking after reset");
    }

    /// <summary>S5：低分测量不得拖拽输出——中间带冻结保持，强低分拒绝。</summary>
    private static void AssertLowScoreDoesNotDrag()
    {
        PolicyController controller = new PolicyController();
        Pose basePose = new Pose(new Vector3(0.2f, 0f, 1f), Quaternion.identity);
        for (int i = 0; i < 5; i++)
        {
            controller.AcceptPose(MakeTrackObservation(i + 1, basePose, i * MsgDt, 0.9f));
        }

        Pose offsetPose = new Pose(basePose.position + new Vector3(0.5f, 0f, 0f), Quaternion.identity);
        AnchorPolicyDecision hold = controller.AcceptPose(MakeTrackObservation(6, offsetPose, 5 * MsgDt, 0.2f));
        Assert(hold.Action == AnchorPolicyAction.Hold, "mid-band low score should hold without updating");
        AnchorPolicyOutput heldOutput = controller.Advance(5 * MsgDt + 0.01);
        Assert(Vector3.Distance(heldOutput.Pose.position, offsetPose.position) > 0.4f, "held output should not be dragged toward the low-score measurement");
        Assert(Vector3.Distance(heldOutput.Pose.position, basePose.position) < 0.05f, "held output should stay near the last trusted pose");

        AnchorPolicyDecision reject = controller.AcceptPose(MakeTrackObservation(7, offsetPose, 6 * MsgDt, 0.05f));
        Assert(reject.Action == AnchorPolicyAction.Reject, "score below hold minimum should reject outright");
    }

    /// <summary>S6：单帧大跳变拒绝；连续高分且互相一致的新位置达到次数后判定真实瞬移并贴合恢复。</summary>
    private static void AssertTeleportRecovery()
    {
        PolicyController controller = new PolicyController();
        Pose basePose = new Pose(new Vector3(0.2f, 0f, 1f), Quaternion.identity);
        for (int i = 0; i < 5; i++)
        {
            controller.AcceptPose(MakeTrackObservation(i + 1, basePose, i * MsgDt, 0.9f));
        }

        Vector3 teleportedCenter = basePose.position + new Vector3(2f, 0f, 0f);
        AnchorPolicyDecision lastDecision = default;
        for (int j = 0; j < 5; j++)
        {
            Vector3 jitter = new Vector3(0.01f * (j % 2 == 0 ? 1f : -1f), 0f, 0f);
            Pose teleported = new Pose(teleportedCenter + jitter, Quaternion.identity);
            lastDecision = controller.AcceptPose(MakeTrackObservation(10 + j, teleported, (5 + j) * MsgDt, 0.9f));
            if (j < 4)
            {
                Assert(lastDecision.Action == AnchorPolicyAction.Reject, $"teleport measurement {j + 1} should be rejected by the innovation gate");
                Assert(lastDecision.Reason.StartsWith("translation", StringComparison.Ordinal), "teleport rejection reason should name the translation gate");
            }
        }

        Assert(lastDecision.Action == AnchorPolicyAction.Snap, "5th consistent high-score teleport measurement should snap-accept");
        Assert(lastDecision.Reason == "teleport_recovery", "teleport recovery should be labeled");
        AnchorPolicyOutput output = controller.Advance(10 * MsgDt + 0.01);
        Assert(Vector3.Distance(output.Pose.position, teleportedCenter) < 0.02f, "output should land at the teleported position after recovery");
        Assert(lastDecision.State == AnchorState.Tracking, "teleport recovery should return to Tracking");
    }

    /// <summary>
    /// S7：消息完全停发后，仅靠每帧 Advance 推进：Tracking -> Coasting（阻尼外推、位移有界）
    /// -> FrozenUncertain（封账冻结，输出连续且不再移动）-> Lost（仍保留输出）。
    /// </summary>
    private static void AssertCoastWithoutMessages()
    {
        PolicyController controller = new PolicyController();
        AnchorPolicyConfig config = new AnchorPolicyConfig();
        Vector3 startPos = new Vector3(0f, 0f, 1f);
        Vector3 velocity = new Vector3(0.5f, 0f, 0f);
        const int messageCount = 30;
        double lastTime = 0.0;
        Vector3 lastTruth = startPos;
        for (int k = 0; k < messageCount; k++)
        {
            double t = k * MsgDt;
            Pose truth = new Pose(startPos + velocity * (float)t, Quaternion.identity);
            controller.AcceptPose(MakeTrackObservation(k + 1, truth, t, 0.9f));
            lastTime = t;
            lastTruth = truth.position;
        }

        AnchorPolicyOutput tracking = controller.Advance(lastTime + 0.1);
        Assert(tracking.State == AnchorState.Tracking, "within coast grace the state should remain Tracking");

        AnchorPolicyOutput coastA = controller.Advance(lastTime + 0.25);
        AnchorPolicyOutput coastB = controller.Advance(lastTime + 0.30);
        Assert(coastA.State == AnchorState.Coasting && coastB.State == AnchorState.Coasting, "between grace and max coast the state should be Coasting");
        Assert(Vector3.Distance(coastB.Pose.position, coastA.Pose.position) > 0.001f, "coasting output should keep moving along the damped velocity");
        Assert(Vector3.Distance(coastB.Pose.position, lastTruth) < velocity.magnitude * (config.maxPredictAheadSeconds + config.velocityDampingTauSeconds) + 0.01f, "coast displacement should stay bounded");

        AnchorPolicyOutput frozenA = controller.Advance(lastTime + 0.50);
        AnchorPolicyOutput frozenB = controller.Advance(lastTime + 0.52);
        Assert(frozenA.State == AnchorState.FrozenUncertain, "beyond max coast the state should be FrozenUncertain");
        Assert(Vector3.Distance(frozenB.Pose.position, frozenA.Pose.position) < 0.0001f, "frozen output should stop moving");
        Assert(Vector3.Distance(frozenA.Pose.position, coastB.Pose.position) < velocity.magnitude * 0.25f, "freeze must stay continuous with the last coast output, not jump back");

        AnchorPolicyOutput lost = controller.Advance(lastTime + 2.5);
        Assert(lost.State == AnchorState.Lost, "after lost timeout the state should be Lost");
        Assert(lost.HasPose, "Lost should keep the last pose for display policy to decide");
    }

    /// <summary>S8：Lost 后 RE_REGISTER 低分测量应贴合接受并回到 Tracking。</summary>
    private static void AssertRelocalizeSnap()
    {
        PolicyController controller = new PolicyController();
        Pose basePose = new Pose(new Vector3(0.2f, 0f, 1f), Quaternion.identity);
        controller.AcceptPose(MakeTrackObservation(1, basePose, 0.0, 0.9f));
        AnchorPolicyOutput lost = controller.Advance(2.5);
        Assert(lost.State == AnchorState.Lost, "no measurements for 2.5s should reach Lost");

        Pose relocalized = new Pose(basePose.position + new Vector3(1.5f, 0f, 0f), YawDegrees(40f));
        AnchorPolicyDecision decision = controller.AcceptPose(
            AnchorObservation.FromAlignedPose(99, relocalized, 2.6, 0.2f, null, "RE_REGISTER", "RE_REGISTER", 2.6)
        );
        Assert(decision.Action == AnchorPolicyAction.Snap, "re-register pose should snap-accept even at low score");
        Assert(decision.Reason == "relocalize_accept", "re-register acceptance should be labeled");
        Assert(decision.State == AnchorState.Tracking, "re-register should return to Tracking");

        AnchorPolicyOutput output = controller.Advance(2.61);
        Assert(Vector3.Distance(output.Pose.position, relocalized.position) < 1e-3f, "output should land at the relocalized position");
    }

    /// <summary>S9：时序守卫——capture 时间乱序或超龄的测量被忽略，输出不受影响。</summary>
    private static void AssertStaleMeasurementIgnored()
    {
        PolicyController controller = new PolicyController();
        Pose basePose = new Pose(new Vector3(0.2f, 0f, 1f), Quaternion.identity);
        controller.AcceptPose(MakeTrackObservation(1, basePose, 10.0, 0.9f, 10.0));
        AnchorPolicyOutput before = controller.Advance(10.02);

        Pose stalePose = new Pose(basePose.position + new Vector3(0.3f, 0f, 0f), Quaternion.identity);
        AnchorPolicyDecision outOfOrder = controller.AcceptPose(MakeTrackObservation(2, stalePose, 10.05, 0.9f, 9.8));
        Assert(outOfOrder.Action == AnchorPolicyAction.Reject && outOfOrder.Reason == "stale_measurement", "out-of-order capture time should be rejected as stale");

        AnchorPolicyDecision tooOld = controller.AcceptPose(MakeTrackObservation(3, stalePose, 10.1, 0.9f, 8.0));
        Assert(tooOld.Action == AnchorPolicyAction.Reject && tooOld.Reason == "stale_measurement", "over-aged capture time should be rejected as stale");

        AnchorPolicyOutput after = controller.Advance(10.02);
        Assert(Vector3.Distance(after.Pose.position, before.Pose.position) < 1e-5f, "stale measurements must not affect the output");
    }

    /// <summary>S10：参数热更不清空滤波历史，新阈值即时生效，coast/lost 改变时状态机回填。</summary>
    private static void AssertConfigHotReload()
    {
        PolicyController controller = new PolicyController();
        Pose basePose = new Pose(new Vector3(0.2f, 0f, 1f), Quaternion.identity);
        for (int i = 0; i < 5; i++)
        {
            controller.AcceptPose(MakeTrackObservation(i + 1, basePose, i * MsgDt, 0.9f));
        }

        double probeTime = 5 * MsgDt;
        AnchorPolicyOutput before = controller.Advance(probeTime);

        AnchorPolicyConfig updated = new AnchorPolicyConfig
        {
            acceptScoreStay = 0.32f,
            maxCoastSeconds = 0.6f,
        };
        controller.ApplyConfig(updated);

        Assert(controller.State == AnchorState.Tracking, "config hot reload should preserve the lifecycle state");
        AnchorPolicyOutput after = controller.Advance(probeTime);
        Assert(Vector3.Distance(after.Pose.position, before.Pose.position) < 1e-5f, "config hot reload should preserve the filter state");

        AnchorPolicyDecision belowNewStay = controller.AcceptPose(MakeTrackObservation(9, basePose, probeTime + MsgDt, 0.30f));
        Assert(belowNewStay.Action == AnchorPolicyAction.Hold, "raised stay threshold should take effect immediately");
    }

    /// <summary>
    /// S11（旋转通道 go/no-go 闸门）：恒速旋转跟踪误差有界，静止时角速度估计收敛到零。
    /// 任一不达标说明常角速度模型不成立，应降级 One-Euro 实现。
    /// </summary>
    private static void AssertRotationFilterGates()
    {
        // (a) 恒速偏航 45 度/秒。
        PolicyController controller = new PolicyController();
        Vector3 position = new Vector3(0.2f, 0f, 1f);
        const float yawRate = 45f;
        const int messageCount = 45;
        List<float> angularErrors = new List<float>();
        for (int k = 0; k < messageCount; k++)
        {
            double t = k * MsgDt;
            Pose truth = new Pose(position, YawDegrees(yawRate * (float)t));
            controller.AcceptPose(MakeTrackObservation(k + 1, truth, t, 0.9f));
            for (double ta = t + FrameDt; ta < t + MsgDt; ta += FrameDt)
            {
                if (ta <= 1.5)
                {
                    controller.Advance(ta);
                    continue;
                }

                AnchorPolicyOutput output = controller.Advance(ta);
                angularErrors.Add(QuaternionAngleDegrees(output.Pose.rotation, YawDegrees(yawRate * (float)ta)));
            }
        }

        float angularP90 = Percentile(angularErrors, 0.90f);
        Assert(angularP90 < 3f, $"constant-rate rotation tracking P90 error should stay under 3 degrees, got {angularP90:F2}");

        // (b) 静止噪声流下角速度估计收敛。
        PolicyController staticController = new PolicyController();
        Pose truthStatic = new Pose(position, YawDegrees(30f));
        Lcg rng = new Lcg(7);
        for (int i = 0; i < 45; i++)
        {
            double t = i * MsgDt;
            staticController.AcceptPose(MakeTrackObservation(i + 1, MakeNoisyPose(truthStatic, 0.002f, 0.5f, ref rng), t, 0.9f));
        }

        Assert(staticController.AngularSpeedDps < 1f, $"static angular velocity estimate should converge below 1 deg/s, got {staticController.AngularSpeedDps:F2}");
    }

    /// <summary>S13：Notify 链——reacquire 清空输出、pause 冻结、resume 后按真实时间差退化、reset 回到 Searching。</summary>
    private static void AssertNotifyChain()
    {
        PolicyController controller = new PolicyController();
        Pose basePose = new Pose(new Vector3(0.2f, 0f, 1f), Quaternion.identity);
        controller.AcceptPose(MakeTrackObservation(1, basePose, 0.0, 0.9f));

        controller.NotifyReacquire(0.1, "smoke");
        Assert(controller.State == AnchorState.Relocalizing, "reacquire should enter Relocalizing");
        AnchorPolicyOutput cleared = controller.Advance(0.11);
        Assert(!cleared.HasPose, "reacquire should clear the output pose");

        AnchorPolicyDecision reregister = controller.AcceptPose(
            AnchorObservation.FromAlignedPose(2, basePose, 0.2, 0.5f, null, "REGISTER", "REGISTER", 0.2)
        );
        Assert(reregister.Action == AnchorPolicyAction.Snap, "register after reacquire should snap-accept");

        controller.NotifyPause(0.3, "smoke");
        AnchorPolicyOutput pausedEarly = controller.Advance(0.4);
        AnchorPolicyOutput pausedLate = controller.Advance(5.4);
        Assert(pausedEarly.State == AnchorState.Paused && pausedLate.State == AnchorState.Paused, "pause should freeze the lifecycle");
        Assert(Vector3.Distance(pausedLate.Pose.position, pausedEarly.Pose.position) < 1e-5f, "pause should freeze the output pose");

        controller.NotifyResume(5.5, "smoke");
        AnchorPolicyOutput resumed = controller.Advance(5.51);
        Assert(resumed.State == AnchorState.Lost, "after a long pause the stale data should honestly degrade to Lost");

        controller.NotifyReset(5.6, "smoke");
        AnchorPolicyOutput reset = controller.Advance(5.61);
        Assert(!reset.HasPose && reset.State == AnchorState.Searching, "reset should clear output and return to Searching");
    }

    /// <summary>构造一帧 TRACK 观测；captureTime 为负时与到达时间一致（零延迟场景）。</summary>
    private static AnchorObservation MakeTrackObservation(long frameId, Pose pose, double sampleTime, float score, double captureTime = double.NaN)
    {
        double capture = double.IsNaN(captureTime) ? sampleTime : captureTime;
        return AnchorObservation.FromAlignedPose(frameId, pose, sampleTime, score, null, "TRACK", "TRACK", capture);
    }

    // ===================== 工具：噪声与统计 =====================

    /// <summary>固定种子线性同余随机源，保证 smoke 结果可复现。</summary>
    private struct Lcg
    {
        private uint state;

        public Lcg(uint seed)
        {
            state = seed == 0 ? 1u : seed;
        }

        /// <summary>返回 (0,1) 均匀随机数。</summary>
        public float Next01()
        {
            state = state * 1664525u + 1013904223u;
            return ((state >> 8) + 1f) / 16777217f;
        }

        /// <summary>返回标准正态随机数（Box-Muller）。</summary>
        public float NextGaussian()
        {
            float u1 = Next01();
            float u2 = Next01();
            return (float)(Math.Sqrt(-2.0 * Math.Log(u1)) * Math.Cos(2.0 * Math.PI * u2));
        }
    }

    /// <summary>给真值 pose 叠加高斯位置噪声与小角度旋转噪声。</summary>
    private static Pose MakeNoisyPose(Pose truth, float posSigma, float rotSigmaDeg, ref Lcg rng)
    {
        Vector3 positionNoise = new Vector3(
            rng.NextGaussian() * posSigma,
            rng.NextGaussian() * posSigma,
            rng.NextGaussian() * posSigma
        );
        Vector3 axis = new Vector3(rng.NextGaussian(), rng.NextGaussian(), rng.NextGaussian());
        if (axis.sqrMagnitude < 1e-12f)
        {
            axis = new Vector3(0f, 1f, 0f);
        }

        axis = axis / axis.magnitude;
        float angle = rng.NextGaussian() * rotSigmaDeg;
        Quaternion rotationNoise = AxisAngle(axis, angle);
        return new Pose(truth.position + positionNoise, Normalize(Multiply(rotationNoise, truth.rotation)));
    }

    /// <summary>归一化线性插值，小角度下等价于 Slerp，用于离线复现旧 Slerp 基线。</summary>
    private static Quaternion NlerpStep(Quaternion from, Quaternion to, float t)
    {
        float dot = from.x * to.x + from.y * to.y + from.z * to.z + from.w * to.w;
        float sign = dot >= 0f ? 1f : -1f;
        return Normalize(new Quaternion(
            from.x + (to.x * sign - from.x) * t,
            from.y + (to.y * sign - from.y) * t,
            from.z + (to.z * sign - from.z) * t,
            from.w + (to.w * sign - from.w) * t
        ));
    }

    /// <summary>计算均方根。</summary>
    private static float Rms(List<float> values)
    {
        if (values.Count == 0)
        {
            return 0f;
        }

        double sum = 0.0;
        foreach (float value in values)
        {
            sum += (double)value * value;
        }

        return (float)Math.Sqrt(sum / values.Count);
    }

    /// <summary>计算给定分位数（0..1）。</summary>
    private static float Percentile(List<float> values, float percentile)
    {
        if (values.Count == 0)
        {
            return 0f;
        }

        List<float> sorted = new List<float>(values);
        sorted.Sort();
        int index = (int)Math.Ceiling(percentile * sorted.Count) - 1;
        index = Math.Max(0, Math.Min(sorted.Count - 1, index));
        return sorted[index];
    }

    // ===================== 队列 / NATS / Hub / Runtime 断言 =====================

    private static void AssertQueuesCanBeCleared()
    {
        LatestOnlyQueue<byte[]> latest = new LatestOnlyQueue<byte[]>(4);
        latest.Enqueue(new byte[] { 1 });
        latest.Enqueue(new byte[] { 2 });
        latest.Clear();
        Assert(!latest.TryDequeueLatest(out _, out int skippedOlder), "latest-only queue Clear should remove pending payloads");
        Assert(skippedOlder == 0, "empty latest-only queue should report no skipped payloads");

        EventQueue<byte[]> events = new EventQueue<byte[]>(4);
        events.Enqueue(new byte[] { 1 });
        events.Enqueue(new byte[] { 2 });
        events.Clear();
        Assert(!events.TryDequeue(out _), "event queue Clear should remove pending events");
    }

    private static void AssertNatsControlClientStopClearsPayloadQueues()
    {
        NatsControlClient controlClient = (NatsControlClient)RuntimeHelpers.GetUninitializedObject(typeof(NatsControlClient));
        MakeUnityObjectNonNull(controlClient);
        BindingFlags flags = BindingFlags.Instance | BindingFlags.NonPublic;
        typeof(NatsControlClient).GetField("poseResultPayloads", flags).SetValue(controlClient, SeedLatestQueue());
        typeof(NatsControlClient).GetField("statusPayloads", flags).SetValue(controlClient, SeedEventQueue());
        typeof(NatsControlClient).GetField("heartbeatPayloads", flags).SetValue(controlClient, SeedLatestQueue());
        typeof(NatsControlClient).GetField("bytesClient", flags).SetValue(
            controlClient,
            new NatsBytesClient(new NatsBytesClient.Settings("nats://127.0.0.1:4222", 1, false, 0.1f, 0.1f), null)
        );

        controlClient.StopClient();

        Assert(controlClient.PendingPoseResultCount == 0, "StopClient should clear stale pose payloads");
        Assert(controlClient.PendingStatusEventCount == 0, "StopClient should clear stale status events");
        Assert(controlClient.PendingHeartbeatCount == 0, "StopClient should clear stale heartbeat payloads");
    }

    private static LatestOnlyQueue<byte[]> SeedLatestQueue()
    {
        LatestOnlyQueue<byte[]> queue = new LatestOnlyQueue<byte[]>(4);
        queue.Enqueue(new byte[] { 1 });
        return queue;
    }

    private static EventQueue<byte[]> SeedEventQueue()
    {
        EventQueue<byte[]> queue = new EventQueue<byte[]>(4);
        queue.Enqueue(new byte[] { 1 });
        return queue;
    }

    private static void AssertPoseRuntimeIgnoresPoseWhilePaused()
    {
        PoseToAnchorRuntime runtime = CreatePoseRuntimeForSmoke();
        Pose firstPose = new Pose(Vector3.zero, Quaternion.identity);
        Pose pausedPose = new Pose(new Vector3(3f, 0f, 0f), Quaternion.identity);

        InvokeAlignedWorldPose(runtime, 1, firstPose, sampleTime: 0.0);
        RuntimeDiagnostics(runtime).currentAnchorState = AnchorState.Paused;
        InvokeAlignedWorldPose(runtime, 2, pausedPose, sampleTime: 0.1);

        Assert(runtime.CurrentAnchorState == AnchorState.Paused, "paused runtime should remain Paused after receiving a pose");
        Assert(runtime.TryGetStablePose(out Pose stablePose), "paused runtime should keep previous stable pose");
        Assert(Vector3.Distance(stablePose.position, firstPose.position) < 0.001f, "paused runtime should ignore later pose updates");
    }

    private static void AssertPoseRuntimeRejectsNonFinitePoseMatrix()
    {
        PoseResult result = new PoseResult
        {
            Header = new MessageHeader { FrameId = 12 },
            HasPose = true,
            PoseMatrixCvCamera = new EgoAnchor.Protocol.Generated.Matrix4x4(),
        };
        for (int i = 0; i < 16; i++)
        {
            result.PoseMatrixCvCamera.Values.Add(i == 0 ? float.NaN : 0f);
        }

        Assert(!PoseToAnchorRuntime.HasFinitePoseMatrix(result), "non-finite pose matrix should be rejected before frame alignment");

        result.PoseMatrixCvCamera.Values[0] = 1f;
        result.PoseMatrixCvCamera.Values[5] = 1f;
        result.PoseMatrixCvCamera.Values[10] = 1f;
        result.PoseMatrixCvCamera.Values[15] = 1f;
        Assert(PoseToAnchorRuntime.HasFinitePoseMatrix(result), "finite 4x4 pose matrix should pass validation");
    }

    /// <summary>
    /// S12：policy 路径不得再经过 processor 链——旧的 ShouldAdvanceProcessors 必须被移除，
    /// 且 runtime 的 stable pose 与控制器 Advance 输出逐位一致。
    /// </summary>
    private static void AssertPolicyPathSkipsProcessors()
    {
        MethodInfo legacy = typeof(PoseToAnchorRuntime).GetMethod("ShouldAdvanceProcessors", BindingFlags.Static | BindingFlags.NonPublic);
        Assert(legacy == null, "policy outputs must not pass through processors anymore (ShouldAdvanceProcessors removed)");

        PoseToAnchorRuntime runtime = CreatePoseRuntimeForSmoke();
        AnchorPolicyHost host = (AnchorPolicyHost)RuntimeHelpers.GetUninitializedObject(typeof(AnchorPolicyHost));
        MakeUnityObjectNonNull(host);
        typeof(PoseToAnchorRuntime)
            .GetField("policyHost", BindingFlags.Instance | BindingFlags.NonPublic)
            .SetValue(runtime, host);

        Pose pose = new Pose(new Vector3(0.5f, 0.2f, 1.0f), YawDegrees(15f));
        InvokeAlignedWorldPose(runtime, 7, pose, sampleTime: 0.0);
        runtime.AdvanceAnchorOutput(0.05);

        Assert(runtime.TryGetStablePose(out Pose stable), "policy runtime should expose a stable pose after Advance");
        AnchorPolicyOutput direct = host.Advance(0.05);
        Assert(Vector3.Distance(stable.position, direct.Pose.position) < 1e-6f, "stable pose position must equal the controller Advance output (no processor pass)");
        Assert(QuaternionAngleDegrees(stable.rotation, direct.Pose.rotation) < 1e-3f, "stable pose rotation must equal the controller Advance output (no processor pass)");
        Assert(runtime.CurrentMotionStateName.Length > 0, "policy runtime should publish the motion state diagnostic");
    }

    private static PoseToAnchorRuntime CreatePoseRuntimeForSmoke()
    {
        PoseToAnchorRuntime runtime = (PoseToAnchorRuntime)RuntimeHelpers.GetUninitializedObject(typeof(PoseToAnchorRuntime));
        MakeUnityObjectNonNull(runtime);
        typeof(PoseToAnchorRuntime)
            .GetField("diagnostics", BindingFlags.Instance | BindingFlags.NonPublic)
            .SetValue(runtime, new PoseToAnchorRuntime.RuntimeDiagnostics());
        return runtime;
    }

    private static PoseToAnchorRuntime.RuntimeDiagnostics RuntimeDiagnostics(PoseToAnchorRuntime runtime)
    {
        return (PoseToAnchorRuntime.RuntimeDiagnostics)typeof(PoseToAnchorRuntime)
            .GetField("diagnostics", BindingFlags.Instance | BindingFlags.NonPublic)
            .GetValue(runtime);
    }

    private static void InvokeAlignedWorldPose(PoseToAnchorRuntime runtime, long frameId, Pose pose, double sampleTime)
    {
        MethodInfo method = typeof(PoseToAnchorRuntime).GetMethod(
            "AcceptWorldPose",
            BindingFlags.Instance | BindingFlags.NonPublic,
            null,
            new[] { typeof(long), typeof(Pose), typeof(PoseResult), typeof(double) },
            null
        );
        method.Invoke(runtime, new object[] { frameId, pose, null, sampleTime });
    }

    private static void AssertNatsBytesClientSubscriptionOrder()
    {
        NatsBytesClient client = new NatsBytesClient(
            new NatsBytesClient.Settings("nats://127.0.0.1:4222", 1, false, 0.1f, 0.1f),
            null
        );
        client.Subscribe("egoanchor.test", _ => { });

        FieldInfo isRunningField = typeof(NatsBytesClient).GetField("isRunning", BindingFlags.Instance | BindingFlags.NonPublic);
        isRunningField.SetValue(client, true);

        bool failedFast = false;
        try
        {
            client.Subscribe("egoanchor.late", _ => { });
        }
        catch (InvalidOperationException ex)
        {
            failedFast = ex.Message.Contains("Start 前调用", StringComparison.Ordinal);
        }

        Assert(failedFast, "NatsBytesClient should reject subscriptions registered after Start");
    }

    private static void AssertNatsBytesClientRequestCancelsOnStop()
    {
        NatsBytesClient client = new NatsBytesClient(
            new NatsBytesClient.Settings("nats://127.0.0.1:4222", 1, false, 0.1f, 0.1f),
            null
        );
        BindingFlags flags = BindingFlags.Instance | BindingFlags.NonPublic;
        typeof(NatsBytesClient).GetField("isRunning", flags).SetValue(client, true);
        typeof(NatsBytesClient).GetField("cts", flags).SetValue(client, new CancellationTokenSource());
        typeof(NatsBytesClient)
            .GetField("connectReady", flags)
            .SetValue(client, new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously));

        Task<byte[]> request = client.RequestAsync("egoanchor.test", new byte[] { 1 }, 5.0f);
        client.Stop();
        Task completed = Task.WhenAny(request, Task.Delay(TimeSpan.FromSeconds(1))).GetAwaiter().GetResult();

        Assert(ReferenceEquals(completed, request), "NatsBytesClient.Stop should cancel a request waiting for connection readiness");
        Assert(request.IsCanceled || request.IsFaulted && request.Exception?.GetBaseException() is OperationCanceledException, "stopped request should finish as cancellation");
    }

    private static void AssertAnchorRuntimeHubCountsOnlyActiveTargets()
    {
        AnchorRuntimeHub hub = (AnchorRuntimeHub)RuntimeHelpers.GetUninitializedObject(typeof(AnchorRuntimeHub));
        Type type = typeof(AnchorRuntimeHub);
        BindingFlags flags = BindingFlags.Instance | BindingFlags.NonPublic;
        FieldInfo runtimesField = type.GetField("runtimes", flags);
        FieldInfo failedField = type.GetField("failed", flags);

        runtimesField.SetValue(hub, new List<PoseToAnchorRuntime> { null });
        Assert(hub.RuntimeCount == 0, "hub runtime count should ignore null inspector slots");

        hub.Publish(new PoseResult());
        Assert((int)failedField.GetValue(hub) == 1, "pose publish without active runtime should count as dispatch failure");
    }

    private static void AssertAnchorRuntimeHubIsolatesRuntimeExceptions()
    {
        bool oldLoggingEnabled = EgoAnchorLog.Enabled;
        EgoAnchorLog.Enabled = false;
        try
        {
            AnchorRuntimeHub hub = (AnchorRuntimeHub)RuntimeHelpers.GetUninitializedObject(typeof(AnchorRuntimeHub));
            Type type = typeof(AnchorRuntimeHub);
            BindingFlags flags = BindingFlags.Instance | BindingFlags.NonPublic;
            FieldInfo poseExceptionsField = type.GetField("poseDispatchExceptions", flags);
            FieldInfo statusExceptionsField = type.GetField("statusDispatchExceptions", flags);
            MethodInfo tryAcceptPose = type.GetMethod("TryAcceptPose", flags);
            MethodInfo tryNotifyStatus = type.GetMethod("TryNotifyStatus", flags);
            PoseToAnchorRuntime brokenRuntime = (PoseToAnchorRuntime)RuntimeHelpers.GetUninitializedObject(typeof(PoseToAnchorRuntime));

            object[] brokenPoseArgs =
            {
                brokenRuntime,
                new PoseResult { Header = new MessageHeader { FrameId = 1 }, HasPose = false },
                null,
            };
            bool brokenPoseOk = (bool)tryAcceptPose.Invoke(hub, brokenPoseArgs);

            Assert(!brokenPoseOk, "hub should isolate a pose dispatch exception");
            Assert((int)poseExceptionsField.GetValue(hub) == 1, "hub should count pose dispatch exceptions per runtime");

            AnchorStatusEvent status = new AnchorStatusEvent { State = "LOST", Event = "LOST", Message = "smoke" };
            bool brokenStatusOk = (bool)tryNotifyStatus.Invoke(hub, new object[] { brokenRuntime, status });
            Assert(!brokenStatusOk, "hub should isolate a status dispatch exception");
            Assert((int)statusExceptionsField.GetValue(hub) == 1, "hub should count status dispatch exceptions per runtime");
        }
        finally
        {
            EgoAnchorLog.Enabled = oldLoggingEnabled;
        }
    }

    private static void MakeUnityObjectNonNull(UnityEngine.Object unityObject)
    {
        BindingFlags flags = BindingFlags.Instance | BindingFlags.NonPublic;
        typeof(UnityEngine.Object).GetField("m_CachedPtr", flags)?.SetValue(unityObject, new IntPtr(1));
        typeof(UnityEngine.Object).GetField("m_InstanceID", flags)?.SetValue(unityObject, 1);
    }

    private static void AssertParallelPoseOffsets()
    {
        AnchorPoseTransform transform = AnchorPoseTransform.OpenCvToUnityDefault;
        Vector3 cameraLocalOffset = new Vector3(0.10f, 0.02f, -0.03f);
        Vector3 anchorLocalOffset = new Vector3(-0.04f, 0.05f, 0.06f);
        Vector3 worldOffset = new Vector3(0.07f, -0.08f, 0.09f);
        Vector3 cameraLocalRotation = new Vector3(7f, -11f, 13f);
        Vector3 anchorLocalRotation = new Vector3(-5f, 9f, 4f);
        Vector3 worldRotation = new Vector3(3f, 6f, -8f);
        transform.SetPositionOffsets(cameraLocalOffset, anchorLocalOffset, worldOffset);
        transform.SetRotationOffsets(cameraLocalRotation, anchorLocalRotation, worldRotation);

        Pose cameraWorldPose = new Pose(new Vector3(1.0f, 0.5f, -0.25f), YawDegrees(90f));
        Pose cameraLocalPose = new Pose(new Vector3(0.2f, 0.3f, 1.2f), YawDegrees(20f));
        Pose cameraOffsetPose = transform.ApplyCameraLocalOffsets(cameraLocalPose);
        Pose alignedPose = CameraLocalToWorld(cameraWorldPose, cameraOffsetPose);
        Pose finalPose = transform.ApplyFrameAlignedOffsets(alignedPose);

        Vector3 expectedPosition = CameraLocalToWorld(cameraWorldPose, cameraLocalPose).position
            + Rotate(cameraWorldPose.rotation, cameraLocalOffset)
            + Rotate(alignedPose.rotation, anchorLocalOffset)
            + worldOffset;
        Quaternion expectedRotation = Multiply(
            Multiply(
                EulerZxy(worldRotation),
                Multiply(cameraWorldPose.rotation, Multiply(EulerZxy(cameraLocalRotation), cameraLocalPose.rotation))
            ),
            EulerZxy(anchorLocalRotation)
        );
        Assert(Vector3.Distance(finalPose.position, expectedPosition) < 0.001f, "camera/anchor/world position offsets should all apply in parallel");
        Assert(QuaternionAngleDegrees(finalPose.rotation, expectedRotation) < 0.1f, "camera/anchor/world rotation offsets should all apply in parallel");
    }

    private static void AssertLegacyOffsetApiRemoved()
    {
        Type type = typeof(AnchorPoseTransform);
        BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;

        foreach (string fieldName in new[] { "applyOffset", "positionOffset", "rotationOffsetEuler", "offsetInAnchorLocal" })
        {
            Assert(type.GetField(fieldName, flags) == null, $"legacy offset field should be removed: {fieldName}");
        }

        foreach (string propertyName in new[] { "ApplyOffsetEnabled", "PositionOffset", "RotationOffsetEuler", "OffsetInAnchorLocal" })
        {
            Assert(type.GetProperty(propertyName, flags) == null, $"legacy offset property should be removed: {propertyName}");
        }

        foreach (string methodName in new[] { "SetOffset", "ApplyFixedOffset", "ApplyCameraLocalPositionOffset" })
        {
            Assert(type.GetMethod(methodName, flags) == null, $"legacy offset method should be removed: {methodName}");
        }
    }

    private static void Assert(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }

    private static Pose WorldToCameraLocal(Pose cameraWorldPose, Pose objectWorldPose)
    {
        Quaternion inverseCameraRotation = Inverse(cameraWorldPose.rotation);
        return new Pose(
            Rotate(inverseCameraRotation, objectWorldPose.position - cameraWorldPose.position),
            Multiply(inverseCameraRotation, objectWorldPose.rotation)
        );
    }

    private static Pose CameraLocalToWorld(Pose cameraWorldPose, Pose cameraLocalPose)
    {
        return new Pose(
            cameraWorldPose.position + Rotate(cameraWorldPose.rotation, cameraLocalPose.position),
            Multiply(cameraWorldPose.rotation, cameraLocalPose.rotation)
        );
    }

    private static Quaternion YawDegrees(float degrees)
    {
        double radians = degrees * Math.PI / 180.0;
        return new Quaternion(0f, (float)Math.Sin(radians * 0.5), 0f, (float)Math.Cos(radians * 0.5));
    }

    private static Quaternion EulerZxy(Vector3 eulerDeg)
    {
        Quaternion z = AxisAngle(new Vector3(0f, 0f, 1f), eulerDeg.z);
        Quaternion x = AxisAngle(new Vector3(1f, 0f, 0f), eulerDeg.x);
        Quaternion y = AxisAngle(new Vector3(0f, 1f, 0f), eulerDeg.y);
        return Normalize(Multiply(y, Multiply(x, z)));
    }

    private static Quaternion AxisAngle(Vector3 axis, float degrees)
    {
        double halfRad = degrees * Math.PI / 360.0;
        float sin = (float)Math.Sin(halfRad);
        float cos = (float)Math.Cos(halfRad);
        return new Quaternion(axis.x * sin, axis.y * sin, axis.z * sin, cos);
    }

    private static Quaternion Inverse(Quaternion q)
    {
        float norm = q.x * q.x + q.y * q.y + q.z * q.z + q.w * q.w;
        return new Quaternion(-q.x / norm, -q.y / norm, -q.z / norm, q.w / norm);
    }

    private static Quaternion Multiply(Quaternion a, Quaternion b)
    {
        return new Quaternion(
            a.w * b.x + a.x * b.w + a.y * b.z - a.z * b.y,
            a.w * b.y - a.x * b.z + a.y * b.w + a.z * b.x,
            a.w * b.z + a.x * b.y - a.y * b.x + a.z * b.w,
            a.w * b.w - a.x * b.x - a.y * b.y - a.z * b.z
        );
    }

    private static Quaternion Normalize(Quaternion q)
    {
        double norm = Math.Sqrt(q.x * q.x + q.y * q.y + q.z * q.z + q.w * q.w);
        if (norm <= 1e-12)
        {
            return Quaternion.identity;
        }

        float inv = (float)(1.0 / norm);
        return new Quaternion(q.x * inv, q.y * inv, q.z * inv, q.w * inv);
    }

    private static Vector3 Rotate(Quaternion q, Vector3 v)
    {
        Quaternion vector = new Quaternion(v.x, v.y, v.z, 0f);
        Quaternion rotated = Multiply(Multiply(q, vector), Inverse(q));
        return new Vector3(rotated.x, rotated.y, rotated.z);
    }

    private static float QuaternionAngleDegrees(Quaternion a, Quaternion b)
    {
        float dot = Math.Abs(a.x * b.x + a.y * b.y + a.z * b.z + a.w * b.w);
        dot = Math.Min(1f, Math.Max(-1f, dot));
        return (float)(2.0 * Math.Acos(dot) * 180.0 / Math.PI);
    }
}

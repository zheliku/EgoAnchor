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

static partial class Program
{
    /// <summary>渲染帧间隔（约 90Hz Advance）。</summary>
    private const double FrameDt = 1.0 / 90.0;

    private static int Main()
    {
        // ===== 模块化 anchor policy 断言 =====
        AssertAnchorModulesAreMonoBehaviours();
        AssertAnchorModulesDoNotExposeModeEnums();
        AssertAnchorModulesDoNotExposeCreateFactories();
        AssertAnchorModulesImplementRuntimeMethodsDirectly();
        AssertAnchorModulesKeepParametersOnMonoBehaviourFields();
        AssertQuaternionLogExpRoundTrips();
        AssertQuaternionHemisphereAlignmentUsesShortestArc();
        AssertEstimatorRotationsPredictBetweenSamples();
        AssertNullGateIgnoresScore();
        AssertScoreGateRejectsInvalidFlag();
        AssertScoreGateHoldsLowScore();
        AssertScoreGateRejectsAbsoluteJump();
        AssertAllEstimatorsSnapThenOutputPose();
        AssertRawEstimatorIsZeroOrderHold();
        AssertLowPassEstimatorMovesBetweenSamplesWhenPredictionEnabled();
        AssertKalmanEstimatorPredictsConstantVelocityBetweenSamples();
        AssertKalmanEstimatorPredictsRotationBetweenSamples();
        AssertOneEuroEstimatorProducesContinuousRenderOutput();
        AssertOneEuroEstimatorSmoothsRotationWithoutEulerArtifacts();
        AssertEgoAnchorEstimatorModuleDampsPredictionWhenScoreDrops();
        AssertBaselineEstimatorsIgnoreReliabilityScore();
        AssertEstimatorModulesCreateExpectedEstimatorNames();
        AssertStaticOutputStageLocksSmallResidualSlip();
        AssertStaticOutputStageReleasesOnRealMotion();
        AssertRateLimitPreventsSingleFrameJump();
        AssertPassThroughDoesNotModifyPose();
        AssertPolicyHostMapsGateActionsToPolicyDecision();
        AssertPolicyHostAdvancesEveryRenderFrame();
        AssertPolicyHostCoastsThenFreezesThenLost();
        AssertPolicyHostRequiresExplicitModules();
        AssertPolicyHostDoesNotUseEnumSelection();
        AssertPoseToAnchorRuntimeUsesPolicyHostField();
        AssertPolicyRuntimeUsesPolicyHostOnly();
        AssertDynamicObjectAnchorReadsRuntimeStablePoseOnly();
        AssertDynamicObjectAnchorHasNoRawSmoothedEnum();

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
        AssertFramePoseDelayBuffer();
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
        Assert(PoseToAnchorRuntime.IsResetAppliedStatus("RESET_APPLIED"), "RESET_APPLIED should enter local reset flow");
        Assert(PoseToAnchorRuntime.IsPauseAppliedStatus("PAUSE_APPLIED"), "PAUSE_APPLIED should enter local pause flow");
        Assert(PoseToAnchorRuntime.IsResumeAppliedStatus("RESUME_APPLIED"), "RESUME_APPLIED should enter local resume flow");

        // ===== Hub / NATS / 队列 / runtime 集成断言 =====
        AssertAnchorRuntimeHubCountsOnlyActiveTargets();
        AssertNatsBytesClientSubscriptionOrder();
        AssertNatsBytesClientRequestCancelsOnStop();
        AssertQueuesCanBeCleared();
        AssertNatsControlClientStopClearsPayloadQueues();
        AssertPoseRuntimeIgnoresPoseWhilePaused();
        AssertPoseRuntimeRejectsNonFinitePoseMatrix();
        AssertPolicyPathUsesPolicyHostOnly();
        AssertRecoveryControllerDoesNothingWhenDisabled();
        AssertRecoveryControllerTriggersOnLostWhenEnabled();
        AssertRecoveryControllerTriggersOnLowScoreOnlyWhenEnabled();
        AssertRecoveryControllerHonorsCooldownAndInFlight();
        AssertRecoveryControllerWaitsWhenInputNotReady();

        Console.WriteLine("Anchor policy smoke passed.");
        return 0;
    }

    private static AnchorObservation MakeTrackObservation(long frameId, Pose pose, double sampleTime, float score, double captureTime = double.NaN)
    {
        double resolvedCaptureTime = double.IsNaN(captureTime) ? sampleTime : captureTime;
        return AnchorObservation.FromAlignedPose(frameId, pose, sampleTime, score, Array.Empty<string>(), "TRACK", "TRACK", resolvedCaptureTime);
    }

    private static void AssertQueuesCanBeCleared()
    {
        LatestOnlyQueue<int> latest = new LatestOnlyQueue<int>(2);
        latest.Enqueue(1);
        latest.Enqueue(2);
        latest.Clear();
        Assert(!latest.TryDequeueLatest(out _, out _), "LatestOnlyQueue.Clear should remove pending payloads");

        EventQueue<int> events = new EventQueue<int>(2);
        events.Enqueue(1);
        events.Enqueue(2);
        events.Clear();
        Assert(!events.TryDequeue(out _), "EventQueue.Clear should remove pending payloads");
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
        AnchorPolicyHost host = CreatePolicyHost(CreateModule<NullGateModule>(), CreateModule<RawEstimatorModule>(), CreateModule<PassThroughOutputModule>());
        SetRuntimeField(runtime, "policyHost", host);

        Pose firstPose = new Pose(Vector3.zero, Quaternion.identity);
        Pose pausedPose = new Pose(new Vector3(3f, 0f, 0f), Quaternion.identity);
        InvokeAlignedWorldPose(runtime, 1, firstPose, sampleTime: 0.0);
        runtime.AdvanceAnchorOutput(0.01);
        host.NotifyPause(0.02, "smoke_pause");
        InvokeAlignedWorldPose(runtime, 2, pausedPose, sampleTime: 0.1);
        runtime.AdvanceAnchorOutput(0.12);

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

    private static void AssertPolicyPathUsesPolicyHostOnly()
    {
        PoseToAnchorRuntime runtime = CreatePoseRuntimeForSmoke();
        AnchorPolicyHost host = CreatePolicyHost(CreateModule<NullGateModule>(), CreateModule<RawEstimatorModule>(), CreateModule<PassThroughOutputModule>());
        SetRuntimeField(runtime, "policyHost", host);

        Pose pose = new Pose(new Vector3(0.5f, 0.2f, 1.0f), YawDegrees(15f));
        InvokeAlignedWorldPose(runtime, 7, pose, sampleTime: 0.0);
        runtime.AdvanceAnchorOutput(0.05);

        Assert(runtime.TryGetStablePose(out Pose stable), "policy runtime should expose a stable pose after Advance");
        Assert(Vector3.Distance(stable.position, pose.position) < 1e-6f, "stable pose position must come from AnchorPolicyHost output");
        Assert(QuaternionAngleDegrees(stable.rotation, pose.rotation) < 1e-3f, "stable pose rotation must come from AnchorPolicyHost output");
        Assert(runtime.CurrentMotionStateName.Length > 0, "policy runtime should publish the motion state diagnostic");
    }

    private static PoseToAnchorRuntime CreatePoseRuntimeForSmoke()
    {
        PoseToAnchorRuntime runtime = (PoseToAnchorRuntime)RuntimeHelpers.GetUninitializedObject(typeof(PoseToAnchorRuntime));
        MakeUnityObjectNonNull(runtime);
        return runtime;
    }

    private static void SetRuntimeStateForSmoke(
        PoseToAnchorRuntime runtime,
        bool? inputReady = null,
        AnchorState? state = null,
        long? frameId = null,
        float? score = null,
        string failure = null,
        string policyAction = null,
        string serverState = null)
    {
        if (inputReady.HasValue)
        {
            SetRuntimeField(runtime, "latestHeartbeatInputReady", inputReady.Value);
        }

        if (state.HasValue)
        {
            SetRuntimeField(runtime, "currentAnchorState", state.Value);
        }

        if (frameId.HasValue)
        {
            SetRuntimeField(runtime, "latestAlignedFrameId", frameId.Value);
        }

        if (score.HasValue)
        {
            SetRuntimeField(runtime, "latestReliabilityScore", score.Value);
        }

        if (failure != null)
        {
            SetRuntimeField(runtime, "latestFailure", failure);
        }

        if (policyAction != null)
        {
            SetRuntimeField(runtime, "latestPolicyAction", policyAction);
        }

        if (serverState != null)
        {
            SetRuntimeField(runtime, "latestServerState", serverState);
        }
    }

    private static void SetRuntimeField(PoseToAnchorRuntime runtime, string fieldName, object value)
    {
        typeof(PoseToAnchorRuntime)
            .GetField(fieldName, BindingFlags.Instance | BindingFlags.NonPublic)
            .SetValue(runtime, value);
    }

    private static void InvokeAlignedWorldPose(PoseToAnchorRuntime runtime, long frameId, Pose pose, double sampleTime)
    {
        runtime.AcceptAlignedWorldPoseForReplay(
            frameId,
            pose,
            captureTimeSeconds: sampleTime,
            reliabilityScore: 1.0f,
            reliabilityFlags: Array.Empty<string>(),
            phase: "TRACK",
            poseSource: "TRACK",
            sampleTimeSeconds: sampleTime);
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

    private static void AssertFramePoseDelayBuffer()
    {
        FramePoseDelayBuffer buffer = new FramePoseDelayBuffer();
        FramePoseSample first = MakeFramePoseSample(1f, 1000.0, 10);
        FramePoseSample second = MakeFramePoseSample(2f, 1033.0, 11);
        FramePoseSample third = MakeFramePoseSample(3f, 1066.0, 12);

        FramePoseSample cold = buffer.Select(first, 1);
        Assert(Math.Abs(cold.LeftCameraPose.position.x - 1f) < 1e-5f, "cold delayed frame pose should fall back to current sample");

        FramePoseSample delayedSecond = buffer.Select(second, 1);
        Assert(Math.Abs(delayedSecond.LeftCameraPose.position.x - 1f) < 1e-5f, "one-frame delay should return the previous successful sample");

        FramePoseSample delayedThird = buffer.Select(third, 1);
        Assert(Math.Abs(delayedThird.LeftCameraPose.position.x - 2f) < 1e-5f, "one-frame delay should keep advancing through history");

        FramePoseDelayBuffer twoFrameBuffer = new FramePoseDelayBuffer();
        FramePoseSample twoFrameCold = twoFrameBuffer.Select(first, 2);
        FramePoseSample twoFrameWarmup = twoFrameBuffer.Select(second, 2);
        FramePoseSample delayedByTwo = twoFrameBuffer.Select(third, 2);
        Assert(Math.Abs(twoFrameCold.LeftCameraPose.position.x - 1f) < 1e-5f, "two-frame delay should fall back to current sample while cold");
        Assert(Math.Abs(twoFrameWarmup.LeftCameraPose.position.x - 2f) < 1e-5f, "two-frame delay should keep using current sample until enough history exists");
        Assert(Math.Abs(delayedByTwo.LeftCameraPose.position.x - 1f) < 1e-5f, "two-frame delay should return the sample two successful captures earlier");

        FramePoseSample immediate = buffer.Select(MakeFramePoseSample(4f, 1099.0, 13), 0);
        Assert(Math.Abs(immediate.LeftCameraPose.position.x - 4f) < 1e-5f, "zero delay should return current sample and clear history");
    }

    private static FramePoseSample MakeFramePoseSample(float x, double monoMs, int unityFrame)
    {
        Pose pose = new Pose(new Vector3(x, 0f, 0f), Quaternion.identity);
        return new FramePoseSample(pose, pose, pose, monoMs, unityFrame);
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

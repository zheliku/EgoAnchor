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
    private static int Main()
    {
        var controller = new PolicyController();

        Pose firstPose = new Pose(Vector3.zero, Quaternion.identity);
        AnchorPolicyDecision first = controller.AcceptPose(
            AnchorObservation.FromAlignedPose(1, firstPose, sampleTimeSeconds: 0.0, reliabilityScore: 0.9f)
        );
        Assert(first.Action == AnchorPolicyAction.Accept, "first reliable pose should be accepted");
        Assert(first.State == AnchorState.Tracking, "first reliable pose should enter Tracking");

        ReliabilityScore uppercaseFlag = new ReliabilityGate().Evaluate(
            AnchorObservation.FromAlignedPose(10, firstPose, sampleTimeSeconds: 0.01, reliabilityScore: 0.95f, reliabilityFlags: new[] { "INVALID_POSE" })
        );
        Assert(uppercaseFlag.Level == ReliabilityLevel.Reject, "reliability reject flags should be matched case-insensitively");

        Pose jumpPose = new Pose(new Vector3(2f, 0f, 0f), Quaternion.identity);
        AnchorPolicyDecision jump = controller.AcceptPose(
            AnchorObservation.FromAlignedPose(2, jumpPose, sampleTimeSeconds: 0.05, reliabilityScore: 0.95f)
        );
        Assert(jump.Action == AnchorPolicyAction.Reject, "large pose jump should be rejected");
        Assert(jump.State == AnchorState.FrozenUncertain, "large pose jump should freeze uncertain");
        Assert(jump.HasOutputPose && Vector3.Distance(jump.OutputPose.position, firstPose.position) < 0.001f, "rejected jump should keep stable pose");

        AnchorPolicyDecision low = controller.AcceptPose(
            AnchorObservation.FromAlignedPose(3, firstPose, sampleTimeSeconds: 0.20, reliabilityScore: 0.17f, reliabilityFlags: new[] { "depth_in_mask_low" })
        );
        Assert(low.Action == AnchorPolicyAction.Reject, "short low reliability pose should be rejected");
        Assert(low.State == AnchorState.FrozenUncertain, "short low reliability pose should freeze uncertain");

        AnchorPolicyDecision lowLost = controller.AcceptPose(
            AnchorObservation.FromAlignedPose(4, firstPose, sampleTimeSeconds: 1.10, reliabilityScore: 0.17f, reliabilityFlags: new[] { "depth_in_mask_low" })
        );
        Assert(lowLost.State == AnchorState.FrozenUncertain, "controller-object low reliability should not enter Lost too aggressively");

        AnchorPolicyDecision lowStillHeld = controller.AcceptPose(
            AnchorObservation.FromAlignedPose(5, firstPose, sampleTimeSeconds: 2.30, reliabilityScore: 0.17f, reliabilityFlags: new[] { "depth_in_mask_low" })
        );
        Assert(lowStillHeld.State == AnchorState.Lost, "sustained low reliability should eventually enter Lost");

        Pose relocalizedPose = new Pose(new Vector3(1.2f, -0.25f, 0f), Quaternion.identity);
        AnchorPolicyDecision relocalized = controller.AcceptPose(
            AnchorObservation.FromAlignedPose(
                6,
                relocalizedPose,
                sampleTimeSeconds: 2.32,
                reliabilityScore: 0.17f,
                reliabilityFlags: new[] { "depth_in_mask_low" },
                phase: "RE_REGISTER",
                poseSource: "RE_REGISTER"
            )
        );
        Assert(relocalized.Action == AnchorPolicyAction.Accept, "re-register pose should recover policy even when it jumps from old stable pose");
        Assert(relocalized.State == AnchorState.Tracking, "re-register pose should return policy to Tracking");
        Assert(Vector3.Distance(relocalized.OutputPose.position, relocalizedPose.position) < 0.001f, "re-register pose should update stable pose");

        Pose invalidRelocalizedPose = new Pose(new Vector3(-1.5f, 0.4f, 0f), Quaternion.identity);
        AnchorPolicyDecision invalidRelocalized = controller.AcceptPose(
            AnchorObservation.FromAlignedPose(
                7,
                invalidRelocalizedPose,
                sampleTimeSeconds: 2.34,
                reliabilityScore: 0.95f,
                reliabilityFlags: new[] { "INVALID_POSE" },
                phase: "RE_REGISTER",
                poseSource: "RE_REGISTER"
            )
        );
        Assert(invalidRelocalized.Action == AnchorPolicyAction.Reject, "re-register pose with hard reject flag should not bypass reliability gate");
        Assert(invalidRelocalized.HasOutputPose && Vector3.Distance(invalidRelocalized.OutputPose.position, relocalizedPose.position) < 0.001f, "invalid re-register should keep previous stable pose");

        AnchorPolicyDecision recovered = controller.AcceptPose(
            AnchorObservation.FromAlignedPose(8, relocalizedPose, sampleTimeSeconds: 2.36, reliabilityScore: 0.9f)
        );
        Assert(recovered.Action == AnchorPolicyAction.Accept, "reliable pose should recover from Lost");
        Assert(recovered.State == AnchorState.Tracking, "reliable pose after Lost should return Tracking");

        AnchorPolicyDecision coast = controller.AcceptPose(
            AnchorObservation.MissingPose(9, sampleTimeSeconds: 2.55, "no_pose")
        );
        Assert(coast.Action == AnchorPolicyAction.Coast, "short missing pose after reliable update should coast");
        Assert(coast.State == AnchorState.Coasting, "short missing pose after reliable update should enter Coasting");

        AnchorPolicyDecision lost = controller.AcceptPose(
            AnchorObservation.MissingPose(10, sampleTimeSeconds: 4.6, "no_pose_timeout")
        );
        Assert(lost.Action == AnchorPolicyAction.Hold, "long missing pose should hold last output");
        Assert(lost.State == AnchorState.Lost, "long missing pose should enter Lost");

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

        controller.NotifyReacquire(sampleTimeSeconds: 1.3, "smoke");
        Assert(controller.State == AnchorState.Relocalizing, "reacquire should enter Relocalizing");
        Assert(!controller.HasStablePose, "reacquire should clear stable pose");

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
        AssertAnchorRuntimeHubCountsOnlyActiveTargets();
        AssertAnchorRuntimeHubIsolatesRuntimeExceptions();
        AssertNatsBytesClientSubscriptionOrder();
        AssertNatsBytesClientRequestCancelsOnStop();
        AssertQueuesCanBeCleared();
        AssertNatsControlClientStopClearsPayloadQueues();
        AssertPoseRuntimeIgnoresPoseWhilePaused();
        AssertPoseRuntimeRejectsNonFinitePoseMatrix();
        AssertPolicyHoldAndRejectDoNotAdvanceProcessors();

        Console.WriteLine("Anchor policy smoke passed.");
        return 0;
    }

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

    private static void AssertPolicyHoldAndRejectDoNotAdvanceProcessors()
    {
        MethodInfo method = typeof(PoseToAnchorRuntime).GetMethod("ShouldAdvanceProcessors", BindingFlags.Static | BindingFlags.NonPublic);
        Assert(method != null, "PoseToAnchorRuntime should expose a private processor advancement predicate for policy actions");
        Assert((bool)method.Invoke(null, new object[] { AnchorPolicyAction.Accept }), "Accept policy action should advance processors");
        Assert((bool)method.Invoke(null, new object[] { AnchorPolicyAction.Coast }), "Coast policy action should advance processors");
        Assert(!(bool)method.Invoke(null, new object[] { AnchorPolicyAction.Reject }), "Reject policy action should keep stable pose without advancing processors");
        Assert(!(bool)method.Invoke(null, new object[] { AnchorPolicyAction.Hold }), "Hold policy action should keep stable pose without advancing processors");
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

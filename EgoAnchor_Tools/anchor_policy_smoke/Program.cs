using System;
using EgoAnchor.Policy;
using EgoAnchor.Protocol.Generated;
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

        AnchorPolicyDecision recovered = controller.AcceptPose(
            AnchorObservation.FromAlignedPose(7, relocalizedPose, sampleTimeSeconds: 2.36, reliabilityScore: 0.9f)
        );
        Assert(recovered.Action == AnchorPolicyAction.Accept, "reliable pose should recover from Lost");
        Assert(recovered.State == AnchorState.Tracking, "reliable pose after Lost should return Tracking");

        AnchorPolicyDecision coast = controller.AcceptPose(
            AnchorObservation.MissingPose(8, sampleTimeSeconds: 2.55, "no_pose")
        );
        Assert(coast.Action == AnchorPolicyAction.Coast, "short missing pose after reliable update should coast");
        Assert(coast.State == AnchorState.Coasting, "short missing pose after reliable update should enter Coasting");

        AnchorPolicyDecision lost = controller.AcceptPose(
            AnchorObservation.MissingPose(9, sampleTimeSeconds: 4.6, "no_pose_timeout")
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

        AnchorStatusEvent status = new AnchorStatusEvent
        {
            State = "REACQUIRING",
            Event = "REACQUIRE_STARTED",
            Message = "smoke",
        };
        Assert(status.Event == "REACQUIRE_STARTED", "status smoke should expose event name");

        Console.WriteLine("Anchor policy smoke passed.");
        return 0;
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

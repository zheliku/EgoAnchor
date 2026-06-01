using System;
using System.Collections.Generic;
using System.IO;
using EgoAnchorEval;
using UnityEngine;

static class Program
{
    private static int Main(string[] args)
    {
        string filePath = args.Length > 0
            ? args[0]
            : Path.Combine("EgoAnchor_Python", "data", "eval", "unity_eval_smoke", "test.jsonl");

        if (File.Exists(filePath))
        {
            File.Delete(filePath);
        }

        using (var writer = new JsonlFileWriter(filePath, flushEveryLines: 1))
        {
            writer.WriteLine("{\"test\":1}");
        }

        byte[] bytes = File.ReadAllBytes(filePath);
        byte[] expected = System.Text.Encoding.UTF8.GetBytes("{\"test\":1}\n");
        if (bytes.Length != expected.Length)
        {
            throw new InvalidOperationException("JsonlFileWriter emitted unexpected byte count.");
        }

        for (int i = 0; i < expected.Length; i++)
        {
            if (bytes[i] != expected[i])
            {
                throw new InvalidOperationException("JsonlFileWriter emitted unexpected JSONL bytes.");
            }
        }

        string content = File.ReadAllText(filePath);
        if (content != "{\"test\":1}\n")
        {
            throw new InvalidOperationException("JsonlFileWriter did not write the expected single JSONL row.");
        }

        Pose head = new Pose(new Vector3(1f, 2f, 3f), new Quaternion(0.1f, 0.2f, 0.3f, 0.4f));
        Pose camera = new Pose(new Vector3(4f, 5f, 6f), new Quaternion(0f, 0.5f, 0f, 0.8660254f));
        Pose gt = new Pose(new Vector3(7f, 8f, 9f), Quaternion.identity);
        string capture = AnchorEvalJson.BuildCaptureLine(
            11,
            12.5,
            1000.0,
            head,
            camera,
            gt,
            gtTracked: true,
            gtPoseValid: true,
            gtPoseSource: "live_tracked",
            gtHoldAgeMs: 0.0,
            cameraValid: true);
        AssertContains(capture, "\"event\":\"unity_capture\"");
        AssertContains(capture, "\"frame_id\":11");
        AssertContains(capture, "\"head_pos\":[1,2,3]");
        AssertContains(capture, "\"capture_utc\":\"1970-01-01T00:00:01.000Z\"");
        AssertContains(capture, "\"capture_local\":\"");
        AssertContains(capture, "\"cam_valid\":true");
        AssertContains(capture, "\"gt_tracked\":true");
        AssertContains(capture, "\"gt_pose_valid\":true");
        AssertContains(capture, "\"gt_pose_source\":\"live_tracked\"");
        AssertContains(capture, "\"gt_hold_age_ms\":0");

        var variants = new List<RecordedVariantSnapshot>
        {
            new RecordedVariantSnapshot(
                "kalman",
                sourceFrameId: 11,
                hasStablePose: true,
                stablePose: gt,
                anchorState: "Tracking",
                policyAction: "baseline_accept",
                policyReason: "policy_disabled",
                isPrimary: true,
                hasAlignedRawPose: true,
                alignedRawPose: camera,
                reliabilityScore: 0.75f)
        };
        string output = AnchorEvalJson.BuildOutputLine(
            20.0,
            2000.0,
            11,
            head,
            gt,
            gtTracked: false,
            gtPoseValid: true,
            gtPoseSource: "hold_last",
            gtHoldAgeMs: 123.5,
            variants);
        AssertContains(output, "\"event\":\"unity_output\"");
        AssertContains(output, "\"source_frame_id\":11");
        AssertContains(output, "\"render_utc\":\"1970-01-01T00:00:02.000Z\"");
        AssertContains(output, "\"render_local\":\"");
        AssertContains(output, "\"gt_tracked\":false");
        AssertContains(output, "\"gt_pose_source\":\"hold_last\"");
        AssertContains(output, "\"gt_hold_age_ms\":123.5");
        AssertContains(output, "\"variants\":[");
        AssertContains(output, "\"label\":\"kalman\"");
        AssertContains(output, "\"aligned_raw_pos\":[4,5,6]");
        AssertContains(output, "\"reliability_score\":0.75");

        string manifest = EvalSessionManifestJson.BuildManifest(
            sessionId: "session_a",
            objectId: "controller_right",
            unityRunMode: "editor_link",
            gtSource: "ovr_rtouch",
            gtController: "RTouch",
            monoToUnixOffsetMs: 9000.25,
            sessionStartMonoMs: 10.0,
            sessionStopMonoMs: 40.0,
            conditionSpans: new[]
            {
                new EvalConditionSpan("static", 10.0, 20.0),
                new EvalConditionSpan("slow_head", 20.0, 40.0),
            },
            eventMarkers: new[]
            {
                new EvalEventMarker("occlusion", 25.0),
            },
            variantLabels: new[] { "kalman", "raw" },
            pythonLogFilename: "",
            notes: "smoke \"notes\"",
            gtHoldPolicy: "hold_last_pose_when_untracked",
            holdLastWhenUntracked: true,
            maxHoldAgeMs: 600000.0);
        AssertContains(manifest, "\"session_id\":\"session_a\"");
        AssertContains(manifest, "\"object_id\":\"controller_right\"");
        AssertContains(manifest, "\"gt_source\":\"ovr_rtouch\"");
        AssertContains(manifest, "\"session_start_utc\":");
        AssertContains(manifest, "\"session_start_local\":");
        AssertContains(manifest, "\"session_stop_utc\":");
        AssertContains(manifest, "\"session_stop_local\":");
        AssertContains(manifest, "\"condition_spans\":[");
        AssertContains(manifest, "\"label\":\"static\"");
        AssertContains(manifest, "\"start_utc\":");
        AssertContains(manifest, "\"end_utc\":");
        AssertContains(manifest, "\"event_markers\":[");
        AssertContains(manifest, "\"type\":\"occlusion\"");
        AssertContains(manifest, "\"marker_utc\":");
        AssertContains(manifest, "\"variant_labels\":[\"kalman\",\"raw\"]");
        AssertContains(manifest, "\"gt_hold_policy\":\"hold_last_pose_when_untracked\"");
        AssertContains(manifest, "\"hold_last_when_untracked\":true");
        AssertEquals("20260602_150405_controller_right", EvalSessionController.BuildReadableSessionId(
            new DateTimeOffset(2026, 6, 2, 15, 4, 5, TimeSpan.FromHours(8)),
            "controller_right"));

        AssertHasMethod(typeof(ControllerGroundTruthProvider), nameof(ControllerGroundTruthProvider.TryGetWorldPoseSample));
        AssertHasMethod(typeof(AnchorEvalRecorder), nameof(AnchorEvalRecorder.CollectVariantLabels));
        AssertHasMethod(typeof(EvalSessionController), nameof(EvalSessionController.StartSession));
        AssertHasMethod(typeof(EvalSessionController), nameof(EvalSessionController.StopSession));
        AssertHasMethod(typeof(EvalSessionController), nameof(EvalSessionController.BeginCondition));
        AssertHasMethod(typeof(EvalSessionController), nameof(EvalSessionController.Mark));
        AssertHasMethod(typeof(EvalManualSmokeDriver), nameof(EvalManualSmokeDriver.LogGroundTruthOnce));
        AssertHasMethod(typeof(EvalManualSmokeDriver), nameof(EvalManualSmokeDriver.BeginSmokeRecording));
        AssertHasMethod(typeof(EvalManualSmokeDriver), nameof(EvalManualSmokeDriver.StopSmokeRecording));
        AssertHasMethod(typeof(EvalSessionHotkeyDriver), nameof(EvalSessionHotkeyDriver.BeginStaticCondition));
        AssertEvaluationSceneMounted();

        Console.WriteLine(filePath);
        return 0;
    }

    private static void AssertEvaluationSceneMounted()
    {
        string scenePath = Path.Combine("EgoAnchor_Unity", "Assets", "Scene", "EgoAnchor-Evaluation.unity");
        if (!File.Exists(scenePath))
        {
            throw new InvalidOperationException($"Missing evaluation scene: {scenePath}");
        }

        string scene = File.ReadAllText(scenePath);
        AssertContains(scene, "m_Name: EvalRig");
        AssertContains(scene, "EgoAnchorEval.EvalSessionController");
        AssertContains(scene, "EgoAnchorEval.EvalSessionHotkeyDriver");
        AssertContains(scene, "holdLastPoseWhenUntracked: 1");
        AssertContains(scene, "objectId: controller_right");
    }

    private static void AssertHasMethod(Type type, string methodName)
    {
        if (type.GetMethod(methodName) == null)
        {
            throw new InvalidOperationException($"{type.Name} is missing method {methodName}.");
        }
    }

    private static void AssertContains(string text, string expected)
    {
        if (!text.Contains(expected, StringComparison.Ordinal))
        {
            throw new InvalidOperationException($"Expected JSON to contain: {expected}\nActual: {text}");
        }
    }

    private static void AssertEquals(string expected, string actual)
    {
        if (!string.Equals(expected, actual, StringComparison.Ordinal))
        {
            throw new InvalidOperationException($"Expected '{expected}', got '{actual}'.");
        }
    }
}

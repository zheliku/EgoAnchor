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
            gtPoseValid: true,
            gtPoseSource: "transform",
            cameraValid: true,
            captureUnityFrame: 123,
            cameraReference: "Left");
        AssertContains(capture, "\"event\":\"unity_capture\"");
        AssertContains(capture, "\"frame_id\":11");
        AssertContains(capture, "\"capture_unity_frame\":123");
        AssertContains(capture, "\"head_pos\":[1,2,3]");
        AssertContains(capture, "\"capture_utc\":\"1970-01-01T00:00:01.000Z\"");
        AssertContains(capture, "\"capture_local\":\"");
        AssertContains(capture, "\"cam_valid\":true");
        AssertContains(capture, "\"camera_reference\":\"Left\"");
        AssertContains(capture, "\"head_euler_deg\":[");
        AssertContains(capture, "\"cam_euler_deg\":[");
        AssertContains(capture, "\"gt_euler_deg\":[0,0,0]");
        AssertContains(capture, "\"gt_pose_valid\":true");
        AssertContains(capture, "\"gt_pose_source\":\"transform\"");
        AssertEuler360Output();

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
                latestPhase: "tracking",
                latestFailure: "",
                anchorPoseSource: "transform",
                hasSourceCaptureTiming: true,
                sourceCaptureMonoMs: 12.5,
                sourceCaptureUnityFrame: 123,
                isPrimary: true,
                hasAlignedRawPose: true,
                alignedRawPose: camera,
                hasArrivalTimeRawPose: true,
                arrivalTimeRawPose: new Pose(new Vector3(5f, 6f, 7f), Quaternion.identity),
                arrivalTimeRawMonoMs: 18.5,
                arrivalTimeRawUnityFrame: 321,
                arrivalTimeCameraReference: "Left",
                reliabilityScore: 0.75f,
                motionState: "Static",
                predictAheadMs: 8.5,
                strategyLabel: "kalman_cv",
                gateModule: "null_gate",
                estimatorModule: "kalman_cv",
                outputModule: "pass_through",
                configHash: "abc123",
                latestResidualMeters: 0.01f,
                latestResidualDegrees: 0.2f,
                latestAcceptedScore: 0.75f,
                latestStaticLocked: false)
        };
        string output = AnchorEvalJson.BuildOutputLine(
            20.0,
            2000.0,
            11,
            head,
            gt,
            gtPoseValid: true,
            gtPoseSource: "transform",
            variants,
            renderUnityFrame: 456);
        AssertContains(output, "\"event\":\"unity_output\"");
        AssertContains(output, "\"source_frame_id\":11");
        AssertContains(output, "\"render_unity_frame\":456");
        AssertContains(output, "\"render_utc\":\"1970-01-01T00:00:02.000Z\"");
        AssertContains(output, "\"render_local\":\"");
        AssertContains(output, "\"head_euler_deg\":[");
        AssertContains(output, "\"gt_euler_deg\":[0,0,0]");
        AssertContains(output, "\"gt_pose_source\":\"transform\"");
        AssertContains(output, "\"variants\":[");
        AssertContains(output, "\"label\":\"kalman\"");
        AssertContains(output, "\"stable_euler_deg\":[0,0,0]");
        AssertContains(output, "\"anchor_pose_source\":\"transform\"");
        AssertContains(output, "\"source_capture_mono_ms\":12.5");
        AssertContains(output, "\"source_capture_unity_frame\":123");
        AssertContains(output, "\"latest_phase\":\"tracking\"");
        AssertContains(output, "\"latest_failure\":\"\"");
        AssertContains(output, "\"motion_state\":\"Static\"");
        AssertContains(output, "\"predict_ahead_ms\":8.5");
        AssertContains(output, "\"aligned_raw_pos\":[4,5,6]");
        AssertContains(output, "\"aligned_raw_euler_deg\":[");
        AssertContains(output, "\"has_arrival_time_raw\":true");
        AssertContains(output, "\"arrival_time_raw_pos\":[5,6,7]");
        AssertContains(output, "\"arrival_time_raw_mono_ms\":18.5");
        AssertContains(output, "\"arrival_time_raw_unity_frame\":321");
        AssertContains(output, "\"arrival_time_camera_reference\":\"Left\"");
        AssertContains(output, "\"reliability_score\":0.75");

        string manifest = EvalSessionManifestJson.BuildManifest(
            sessionId: "session_a",
            objectId: "controller_right",
            unityRunMode: "editor_link",
            gtSource: "transform",
            gtTransform: "OVRControllerPrefab",
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
            variantConfigs: Array.Empty<EvalVariantConfig>(),
            pythonLogFilename: "",
            sessionNotes: "smoke \"notes\"");
        AssertContains(manifest, "\"session_id\":\"session_a\"");
        AssertContains(manifest, "\"object_id\":\"controller_right\"");
        AssertContains(manifest, "\"gt_source\":\"transform\"");
        AssertContains(manifest, "\"gt_transform\":\"OVRControllerPrefab\"");
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
        AssertEquals("20260602_150405_controller_right", EvalSessionController.BuildReadableSessionId(
            new DateTimeOffset(2026, 6, 2, 15, 4, 5, TimeSpan.FromHours(8)),
            "controller_right"));
        AssertPythonSessionReuseSelection();

        AssertHasMethod(typeof(AnchorEvalRecorder), nameof(AnchorEvalRecorder.CollectVariantLabels));
        AssertHasMethod(typeof(EvalSessionController), nameof(EvalSessionController.StartSession));
        AssertHasMethod(typeof(EvalSessionController), nameof(EvalSessionController.StopSession));
        AssertHasMethod(typeof(EvalSessionController), nameof(EvalSessionController.BeginCondition));
        AssertHasMethod(typeof(EvalSessionController), nameof(EvalSessionController.Mark));
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
        AssertContains(scene, "groundTruthTransform:");
        AssertContains(scene, "anchorTransform:");
        AssertContains(scene, "objectId: controller_right");
    }

    private static void AssertPythonSessionReuseSelection()
    {
        string root = Path.Combine(Path.GetTempPath(), "egoanchor_eval_reuse_smoke_" + Guid.NewGuid().ToString("N"));
        try
        {
            Directory.CreateDirectory(root);
            WritePythonSession(root, "20260602_155000_controller_left", "controller_left", "left_runtime.jsonl", addUnityLog: false);
            WritePythonSession(root, "20260602_155723_controller_right", "controller_right", "right_runtime.jsonl", addUnityLog: false);
            WritePythonSession(root, "20260602_155900_controller_right", "controller_right", "used_runtime.jsonl", addUnityLog: true);

            bool found = EvalSessionController.TryFindReusablePythonSession(
                root,
                "controller_right",
                maxAgeMinutes: 120.0,
                metadataFilename: "python_session.json",
                out string sessionId,
                out string sessionDir,
                out string pythonLogFilename);

            if (!found)
            {
                throw new InvalidOperationException("Expected reusable Python eval session was not found.");
            }

            AssertEquals("20260602_155723_controller_right", sessionId);
            AssertEquals(Path.Combine(root, "20260602_155723_controller_right"), sessionDir);
            AssertEquals("right_runtime.jsonl", pythonLogFilename);
        }
        finally
        {
            if (Directory.Exists(root))
            {
                Directory.Delete(root, recursive: true);
            }
        }
    }

    private static void AssertEuler360Output()
    {
        float halfRad = -30.0f * (float)Math.PI / 360.0f;
        Pose negativeEulerPose = new Pose(Vector3.zero, new Quaternion(0.0f, (float)Math.Sin(halfRad), 0.0f, (float)Math.Cos(halfRad)));
        string json = AnchorEvalJson.BuildCaptureLine(
            1,
            1.0,
            1.0,
            negativeEulerPose,
            negativeEulerPose,
            negativeEulerPose,
            gtPoseValid: true,
            gtPoseSource: "transform");

        AssertContains(json, "\"gt_euler_deg\":[0,330,0]");
    }

    private static void WritePythonSession(string root, string sessionId, string objectId, string pythonLogFilename, bool addUnityLog)
    {
        string dir = Path.Combine(root, sessionId);
        Directory.CreateDirectory(dir);
        File.WriteAllText(
            Path.Combine(dir, "python_session.json"),
            $"{{\"session_id\":\"{sessionId}\",\"object_id\":\"{objectId}\",\"python_log_filename\":\"{pythonLogFilename}\",\"state\":\"python_started\"}}");
        if (addUnityLog)
        {
            File.WriteAllText(Path.Combine(dir, $"{sessionId}_unity_capture.jsonl"), "{}\n");
        }
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

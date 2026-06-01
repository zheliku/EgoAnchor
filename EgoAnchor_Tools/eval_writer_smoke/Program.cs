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
        string capture = AnchorEvalJson.BuildCaptureLine(11, 12.5, 1000.0, head, camera, gt, gtTracked: true, cameraValid: true);
        AssertContains(capture, "\"event\":\"unity_capture\"");
        AssertContains(capture, "\"frame_id\":11");
        AssertContains(capture, "\"head_pos\":[1,2,3]");
        AssertContains(capture, "\"cam_valid\":true");
        AssertContains(capture, "\"gt_tracked\":true");

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
        string output = AnchorEvalJson.BuildOutputLine(20.0, 2000.0, 11, head, gt, gtTracked: true, variants);
        AssertContains(output, "\"event\":\"unity_output\"");
        AssertContains(output, "\"source_frame_id\":11");
        AssertContains(output, "\"variants\":[");
        AssertContains(output, "\"label\":\"kalman\"");
        AssertContains(output, "\"aligned_raw_pos\":[4,5,6]");
        AssertContains(output, "\"reliability_score\":0.75");

        AssertHasMethod(typeof(EvalManualSmokeDriver), nameof(EvalManualSmokeDriver.LogGroundTruthOnce));
        AssertHasMethod(typeof(EvalManualSmokeDriver), nameof(EvalManualSmokeDriver.BeginSmokeRecording));
        AssertHasMethod(typeof(EvalManualSmokeDriver), nameof(EvalManualSmokeDriver.StopSmokeRecording));

        Console.WriteLine(filePath);
        return 0;
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
}

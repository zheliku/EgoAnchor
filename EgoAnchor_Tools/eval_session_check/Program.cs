using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text.Json;

static class Program
{
    private static int Main(string[] args)
    {
        try
        {
            Options options = Options.Parse(args);
            SessionSummary summary = ValidateSession(options);
            Console.WriteLine($"session_dir={options.SessionDir}");
            Console.WriteLine($"session_id={summary.SessionId}");
            Console.WriteLine($"capture_rows={summary.CaptureRows}");
            Console.WriteLine($"output_rows={summary.OutputRows}");
            Console.WriteLine($"variant_labels={string.Join(",", summary.OutputVariantLabels.OrderBy(v => v, StringComparer.Ordinal))}");
            Console.WriteLine($"condition_spans={summary.ConditionSpanCount}");
            Console.WriteLine($"event_markers={summary.EventMarkerCount}");
            Console.WriteLine($"python_pose_frame_matches={summary.PythonPoseFrameMatches}");
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[EgoAnchorEval][SessionCheck] {ex.Message}");
            return 1;
        }
    }

    private static SessionSummary ValidateSession(Options options)
    {
        if (!Directory.Exists(options.SessionDir))
        {
            throw new InvalidOperationException($"Session directory does not exist: {options.SessionDir}");
        }

        string manifestPath = Path.Combine(options.SessionDir, "session_manifest.json");
        if (!File.Exists(manifestPath))
        {
            throw new InvalidOperationException($"Missing session_manifest.json in {options.SessionDir}");
        }

        using JsonDocument manifestDoc = JsonDocument.Parse(File.ReadAllText(manifestPath));
        JsonElement manifest = manifestDoc.RootElement;
        string sessionId = RequireString(manifest, "session_id");
        RequireString(manifest, "object_id");
        RequireString(manifest, "unity_run_mode");
        RequireString(manifest, "gt_source");
        RequireNumber(manifest, "mono_to_unix_offset_ms");
        RequireNumber(manifest, "session_start_unix_ms");
        RequireString(manifest, "session_start_utc");
        RequireString(manifest, "session_start_local");
        RequireNumber(manifest, "session_stop_unix_ms");
        RequireString(manifest, "session_stop_utc");
        RequireString(manifest, "session_stop_local");
        RequireString(manifest, "gt_hold_policy");
        RequireBool(manifest, "hold_last_when_untracked");
        ValidateConditionSpans(manifest, out int conditionSpanCount);
        ValidateEventMarkers(manifest, out int eventMarkerCount);
        HashSet<string> manifestVariantLabels = ReadStringSet(manifest, "variant_labels");

        string capturePath = ResolveLogPath(options.SessionDir, sessionId, "_unity_capture.jsonl");
        string outputPath = ResolveLogPath(options.SessionDir, sessionId, "_unity_output.jsonl");
        List<long> captureFrameIds = ValidateCaptureLog(capturePath, out int captureRows);
        HashSet<string> outputVariantLabels = ValidateOutputLog(outputPath, out int outputRows);

        foreach (string label in manifestVariantLabels)
        {
            if (!outputVariantLabels.Contains(label))
            {
                throw new InvalidOperationException($"Manifest variant label '{label}' was not found in output variants.");
            }
        }

        if (!outputVariantLabels.Contains("raw"))
        {
            throw new InvalidOperationException("Output variants must include label 'raw'.");
        }

        string pythonLog = ResolvePythonLog(options, manifest);
        int pythonMatches = 0;
        if (!string.IsNullOrEmpty(pythonLog))
        {
            pythonMatches = CountPythonPoseFrameMatches(pythonLog, captureFrameIds);
            if (pythonMatches <= 0)
            {
                throw new InvalidOperationException($"No capture frame_id was found in Python pose_result log: {pythonLog}");
            }
        }
        else if (options.RequirePythonJoin)
        {
            throw new InvalidOperationException("Python join was required, but no --python-log was provided and manifest python_log_filename is empty or missing.");
        }

        return new SessionSummary(
            sessionId,
            captureRows,
            outputRows,
            outputVariantLabels,
            conditionSpanCount,
            eventMarkerCount,
            pythonMatches);
    }

    private static List<long> ValidateCaptureLog(string path, out int rowCount)
    {
        var frameIds = new List<long>();
        long previousFrameId = long.MinValue;
        rowCount = 0;

        foreach (string line in File.ReadLines(path))
        {
            if (string.IsNullOrWhiteSpace(line))
            {
                continue;
            }

            using JsonDocument doc = JsonDocument.Parse(line);
            JsonElement row = doc.RootElement;
            RequireStringEquals(row, "event", "unity_capture");
            long frameId = RequireLong(row, "frame_id");
            if (frameId <= previousFrameId)
            {
                throw new InvalidOperationException($"Capture frame_id must be strictly increasing. Previous={previousFrameId}, current={frameId}");
            }

            previousFrameId = frameId;
            frameIds.Add(frameId);
            RequireNumber(row, "capture_mono_ms");
            RequireNumber(row, "capture_unix_ms");
            RequireString(row, "capture_utc");
            RequireString(row, "capture_local");
            RequirePoseArray(row, "head_pos", 3, allowNull: false);
            RequirePoseArray(row, "head_rot", 4, allowNull: false);
            RequireBool(row, "cam_valid");
            RequirePoseArray(row, "cam_pos", 3, allowNull: true);
            RequirePoseArray(row, "cam_rot", 4, allowNull: true);
            RequireBool(row, "gt_tracked");
            RequireBool(row, "gt_pose_valid");
            RequireString(row, "gt_pose_source");
            RequireNumberOrNull(row, "gt_hold_age_ms");
            rowCount++;
        }

        if (rowCount == 0)
        {
            throw new InvalidOperationException($"Capture log has no rows: {path}");
        }

        return frameIds;
    }

    private static HashSet<string> ValidateOutputLog(string path, out int rowCount)
    {
        var labels = new HashSet<string>(StringComparer.Ordinal);
        bool sawPrimary = false;
        rowCount = 0;

        foreach (string line in File.ReadLines(path))
        {
            if (string.IsNullOrWhiteSpace(line))
            {
                continue;
            }

            using JsonDocument doc = JsonDocument.Parse(line);
            JsonElement row = doc.RootElement;
            RequireStringEquals(row, "event", "unity_output");
            RequireNumber(row, "render_mono_ms");
            RequireNumber(row, "render_unix_ms");
            RequireString(row, "render_utc");
            RequireString(row, "render_local");
            RequireLong(row, "source_frame_id");
            RequirePoseArray(row, "head_pos", 3, allowNull: false);
            RequirePoseArray(row, "head_rot", 4, allowNull: false);
            RequireBool(row, "gt_tracked");
            RequireBool(row, "gt_pose_valid");
            RequireString(row, "gt_pose_source");
            RequireNumberOrNull(row, "gt_hold_age_ms");

            JsonElement variants = RequireProperty(row, "variants");
            if (variants.ValueKind != JsonValueKind.Array || variants.GetArrayLength() == 0)
            {
                throw new InvalidOperationException("Output row variants must be a non-empty array.");
            }

            foreach (JsonElement variant in variants.EnumerateArray())
            {
                string label = RequireString(variant, "label");
                labels.Add(label);
                bool isPrimary = RequireBool(variant, "is_primary");
                RequireLong(variant, "source_frame_id");
                RequireBool(variant, "has_stable");
                RequireString(variant, "anchor_state");
                RequireString(variant, "policy_action");
                RequireString(variant, "policy_reason");

                if (isPrimary)
                {
                    sawPrimary = true;
                    RequireBool(variant, "has_aligned_raw");
                    RequirePoseArray(variant, "aligned_raw_pos", 3, allowNull: true);
                    RequirePoseArray(variant, "aligned_raw_rot", 4, allowNull: true);
                    RequireNumberOrNull(variant, "reliability_score");
                }
            }

            rowCount++;
        }

        if (rowCount == 0)
        {
            throw new InvalidOperationException($"Output log has no rows: {path}");
        }

        if (!sawPrimary)
        {
            throw new InvalidOperationException("Output variants never contained is_primary=true.");
        }

        return labels;
    }

    private static void ValidateConditionSpans(JsonElement manifest, out int spanCount)
    {
        JsonElement spans = RequireProperty(manifest, "condition_spans");
        if (spans.ValueKind != JsonValueKind.Array)
        {
            throw new InvalidOperationException("manifest.condition_spans must be an array.");
        }

        spanCount = spans.GetArrayLength();
        double previousEnd = double.NegativeInfinity;
        foreach (JsonElement span in spans.EnumerateArray())
        {
            RequireString(span, "label");
            double start = RequireNumber(span, "start_mono_ms");
            RequireNumber(span, "start_unix_ms");
            RequireString(span, "start_utc");
            RequireString(span, "start_local");
            double end = RequireNumber(span, "end_mono_ms");
            RequireNumber(span, "end_unix_ms");
            RequireString(span, "end_utc");
            RequireString(span, "end_local");
            if (end < start)
            {
                throw new InvalidOperationException($"Condition span end before start: {start} -> {end}");
            }

            if (start < previousEnd - 1e-6)
            {
                throw new InvalidOperationException("Condition spans overlap or are out of order.");
            }

            previousEnd = end;
        }
    }

    private static void ValidateEventMarkers(JsonElement manifest, out int markerCount)
    {
        JsonElement markers = RequireProperty(manifest, "event_markers");
        if (markers.ValueKind != JsonValueKind.Array)
        {
            throw new InvalidOperationException("manifest.event_markers must be an array.");
        }

        markerCount = markers.GetArrayLength();
        foreach (JsonElement marker in markers.EnumerateArray())
        {
            RequireString(marker, "type");
            RequireNumber(marker, "mono_ms");
            RequireNumber(marker, "marker_unix_ms");
            RequireString(marker, "marker_utc");
            RequireString(marker, "marker_local");
        }
    }

    private static int CountPythonPoseFrameMatches(string pythonLog, IReadOnlyCollection<long> captureFrameIds)
    {
        if (!File.Exists(pythonLog))
        {
            throw new InvalidOperationException($"Python log does not exist: {pythonLog}");
        }

        var wanted = new HashSet<long>(captureFrameIds);
        var matched = new HashSet<long>();
        foreach (string line in File.ReadLines(pythonLog))
        {
            if (string.IsNullOrWhiteSpace(line))
            {
                continue;
            }

            using JsonDocument doc = JsonDocument.Parse(line);
            JsonElement row = doc.RootElement;
            if (!row.TryGetProperty("event", out JsonElement eventElement)
                || eventElement.ValueKind != JsonValueKind.String
                || !string.Equals(eventElement.GetString(), "pose_result", StringComparison.Ordinal))
            {
                continue;
            }

            if (row.TryGetProperty("frame_id", out JsonElement frameElement)
                && frameElement.TryGetInt64(out long frameId)
                && wanted.Contains(frameId))
            {
                matched.Add(frameId);
            }
        }

        return matched.Count;
    }

    private static string ResolveLogPath(string sessionDir, string sessionId, string suffix)
    {
        string named = Path.Combine(sessionDir, $"{sessionId}{suffix}");
        if (File.Exists(named))
        {
            return named;
        }

        string[] matches = Directory.GetFiles(sessionDir, $"*{suffix}");
        if (matches.Length != 1)
        {
            throw new InvalidOperationException($"Expected exactly one *{suffix} in {sessionDir}, found {matches.Length}.");
        }

        return matches[0];
    }

    private static string ResolvePythonLog(Options options, JsonElement manifest)
    {
        if (!string.IsNullOrWhiteSpace(options.PythonLog))
        {
            return Path.GetFullPath(options.PythonLog);
        }

        string fromManifest = manifest.TryGetProperty("python_log_filename", out JsonElement element)
            && element.ValueKind == JsonValueKind.String
            ? element.GetString()
            : string.Empty;
        if (string.IsNullOrWhiteSpace(fromManifest))
        {
            return string.Empty;
        }

        string candidate = Path.IsPathRooted(fromManifest)
            ? fromManifest
            : Path.Combine(options.SessionDir, fromManifest);
        return File.Exists(candidate) ? Path.GetFullPath(candidate) : string.Empty;
    }

    private static HashSet<string> ReadStringSet(JsonElement obj, string name)
    {
        JsonElement array = RequireProperty(obj, name);
        if (array.ValueKind != JsonValueKind.Array)
        {
            throw new InvalidOperationException($"{name} must be an array.");
        }

        var values = new HashSet<string>(StringComparer.Ordinal);
        foreach (JsonElement element in array.EnumerateArray())
        {
            if (element.ValueKind != JsonValueKind.String)
            {
                throw new InvalidOperationException($"{name} must contain only strings.");
            }

            values.Add(element.GetString() ?? string.Empty);
        }

        return values;
    }

    private static JsonElement RequireProperty(JsonElement obj, string name)
    {
        if (!obj.TryGetProperty(name, out JsonElement value))
        {
            throw new InvalidOperationException($"Missing JSON property: {name}");
        }

        return value;
    }

    private static string RequireString(JsonElement obj, string name)
    {
        JsonElement value = RequireProperty(obj, name);
        if (value.ValueKind != JsonValueKind.String)
        {
            throw new InvalidOperationException($"{name} must be a string.");
        }

        return value.GetString() ?? string.Empty;
    }

    private static void RequireStringEquals(JsonElement obj, string name, string expected)
    {
        string actual = RequireString(obj, name);
        if (!string.Equals(actual, expected, StringComparison.Ordinal))
        {
            throw new InvalidOperationException($"{name} expected '{expected}', got '{actual}'.");
        }
    }

    private static bool RequireBool(JsonElement obj, string name)
    {
        JsonElement value = RequireProperty(obj, name);
        if (value.ValueKind != JsonValueKind.True && value.ValueKind != JsonValueKind.False)
        {
            throw new InvalidOperationException($"{name} must be a boolean.");
        }

        return value.GetBoolean();
    }

    private static long RequireLong(JsonElement obj, string name)
    {
        JsonElement value = RequireProperty(obj, name);
        if (!value.TryGetInt64(out long result))
        {
            throw new InvalidOperationException($"{name} must be an integer.");
        }

        return result;
    }

    private static double RequireNumber(JsonElement obj, string name)
    {
        JsonElement value = RequireProperty(obj, name);
        if (!TryReadNumber(value, out double result))
        {
            throw new InvalidOperationException($"{name} must be a number.");
        }

        return result;
    }

    private static void RequireNumberOrNull(JsonElement obj, string name)
    {
        JsonElement value = RequireProperty(obj, name);
        if (value.ValueKind == JsonValueKind.Null)
        {
            return;
        }

        if (!TryReadNumber(value, out _))
        {
            throw new InvalidOperationException($"{name} must be a number or null.");
        }
    }

    private static void RequirePoseArray(JsonElement obj, string name, int length, bool allowNull)
    {
        JsonElement value = RequireProperty(obj, name);
        if (allowNull && value.ValueKind == JsonValueKind.Null)
        {
            return;
        }

        if (value.ValueKind != JsonValueKind.Array || value.GetArrayLength() != length)
        {
            throw new InvalidOperationException($"{name} must be an array of length {length}.");
        }

        foreach (JsonElement element in value.EnumerateArray())
        {
            if (!TryReadNumber(element, out _))
            {
                throw new InvalidOperationException($"{name} must contain only numbers.");
            }
        }
    }

    private static bool TryReadNumber(JsonElement value, out double result)
    {
        if (value.ValueKind == JsonValueKind.Number && value.TryGetDouble(out result))
        {
            return true;
        }

        result = 0.0;
        return false;
    }

    private sealed class Options
    {
        public string SessionDir { get; private set; }

        public string PythonLog { get; private set; }

        public bool RequirePythonJoin { get; private set; }

        public static Options Parse(string[] args)
        {
            var options = new Options
            {
                SessionDir = Path.Combine("EgoAnchor_Tools", "eval_session_check", "sample_session"),
                PythonLog = string.Empty,
                RequirePythonJoin = false,
            };

            for (int i = 0; i < args.Length; i++)
            {
                string arg = args[i];
                if (arg == "--session-dir" && i + 1 < args.Length)
                {
                    options.SessionDir = args[++i];
                }
                else if (arg == "--python-log" && i + 1 < args.Length)
                {
                    options.PythonLog = args[++i];
                }
                else if (arg == "--require-python-join")
                {
                    options.RequirePythonJoin = true;
                }
                else
                {
                    throw new InvalidOperationException($"Unknown or incomplete argument: {arg}");
                }
            }

            options.SessionDir = Path.GetFullPath(options.SessionDir);
            return options;
        }
    }

    private sealed class SessionSummary
    {
        public SessionSummary(
            string sessionId,
            int captureRows,
            int outputRows,
            HashSet<string> outputVariantLabels,
            int conditionSpanCount,
            int eventMarkerCount,
            int pythonPoseFrameMatches)
        {
            SessionId = sessionId;
            CaptureRows = captureRows;
            OutputRows = outputRows;
            OutputVariantLabels = outputVariantLabels;
            ConditionSpanCount = conditionSpanCount;
            EventMarkerCount = eventMarkerCount;
            PythonPoseFrameMatches = pythonPoseFrameMatches;
        }

        public string SessionId { get; }

        public int CaptureRows { get; }

        public int OutputRows { get; }

        public HashSet<string> OutputVariantLabels { get; }

        public int ConditionSpanCount { get; }

        public int EventMarkerCount { get; }

        public int PythonPoseFrameMatches { get; }
    }
}

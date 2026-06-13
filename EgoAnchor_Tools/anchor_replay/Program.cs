using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Text.Json;
using EgoAnchor.Policy;
using EgoAnchorEval;
using UnityEngine;

static class Program
{
    private const string OutputFilename = "anchor_replay_output.jsonl";
    private const string SummaryFilename = "anchor_replay_summary.csv";
    private const string ConfigFilename = "anchor_replay_config.json";

    private static int Main(string[] args)
    {
        try
        {
            Options options = Options.Parse(args);
            Directory.CreateDirectory(options.OutputDir);
            List<ReplayRow> rows = LoadReplayRows(options.SessionDir);
            if (rows.Count == 0)
            {
                throw new InvalidOperationException("session 中没有可回放的 unity_output 行。");
            }

            List<StrategyRunner> strategies = CreateDefaultStrategies();
            string outputPath = Path.Combine(options.OutputDir, OutputFilename);
            string summaryPath = Path.Combine(options.OutputDir, SummaryFilename);
            string configPath = Path.Combine(options.OutputDir, ConfigFilename);
            RunReplay(rows, strategies, outputPath);
            WriteSummary(strategies, summaryPath);
            WriteConfig(strategies, configPath);
            Console.WriteLine($"anchor replay rows={rows.Count}, strategies={strategies.Count}");
            Console.WriteLine(outputPath);
            Console.WriteLine(summaryPath);
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(ex.Message);
            return 1;
        }
    }

    private static void RunReplay(List<ReplayRow> rows, List<StrategyRunner> strategies, string outputPath)
    {
        using StreamWriter writer = new StreamWriter(outputPath, append: false);
        HashSet<long> submittedFrames = new HashSet<long>();
        foreach (ReplayRow row in rows)
        {
            if (row.HasRawPose && row.SourceFrameId >= 0 && submittedFrames.Add(row.SourceFrameId))
            {
                double sampleSeconds = row.RenderMonoMs / 1000.0;
                double captureSeconds = row.SourceCaptureMonoMs.HasValue ? row.SourceCaptureMonoMs.Value / 1000.0 : sampleSeconds;
                AnchorObservation observation = AnchorObservation.FromAlignedPose(
                    row.SourceFrameId,
                    row.RawPose,
                    sampleSeconds,
                    row.ReliabilityScore,
                    null,
                    row.Phase,
                    row.PoseSource,
                    captureSeconds);
                foreach (StrategyRunner strategy in strategies)
                {
                    strategy.Accept(observation);
                }
            }

            double renderSeconds = row.RenderMonoMs / 1000.0;
            List<RecordedVariantSnapshot> snapshots = new List<RecordedVariantSnapshot>(strategies.Count);
            foreach (StrategyRunner strategy in strategies)
            {
                snapshots.Add(strategy.Advance(row, renderSeconds));
            }

            string line = AnchorEvalJson.BuildOutputLine(
                row.RenderMonoMs,
                row.RenderUnixMs,
                row.SourceFrameId,
                row.HeadPose,
                row.GroundTruthPose,
                row.GroundTruthValid,
                row.GroundTruthSource,
                snapshots,
                row.RenderUnityFrame);
            writer.WriteLine(line);
        }
    }

    private static List<ReplayRow> LoadReplayRows(string sessionDir)
    {
        string outputPath = ResolveUniqueLog(sessionDir, "*_unity_output.jsonl");
        List<ReplayRow> rows = new List<ReplayRow>();
        foreach (string line in File.ReadLines(outputPath))
        {
            if (string.IsNullOrWhiteSpace(line))
            {
                continue;
            }

            using JsonDocument doc = JsonDocument.Parse(line);
            JsonElement root = doc.RootElement;
            long sourceFrameId = ReadLong(root, "source_frame_id", -1);
            double renderMonoMs = ReadDouble(root, "render_mono_ms", 0.0);
            ReplayMeasurement measurement = ExtractMeasurement(root, sourceFrameId, renderMonoMs);
            rows.Add(new ReplayRow(
                renderMonoMs,
                ReadDouble(root, "render_unix_ms", 0.0),
                ReadInt(root, "render_unity_frame", -1),
                sourceFrameId,
                ReadPose(root, "head_pos", "head_rot", true),
                ReadPose(root, "gt_pos", "gt_rot", ReadBool(root, "gt_pose_valid", false)),
                ReadBool(root, "gt_pose_valid", false),
                ReadString(root, "gt_pose_source", ""),
                measurement.HasPose,
                measurement.Pose,
                measurement.SourceCaptureMonoMs,
                measurement.ReliabilityScore,
                measurement.Phase,
                measurement.PoseSource));
        }

        return rows;
    }

    private static ReplayMeasurement ExtractMeasurement(JsonElement root, long sourceFrameId, double renderMonoMs)
    {
        if (!root.TryGetProperty("variants", out JsonElement variants) || variants.ValueKind != JsonValueKind.Array)
        {
            return ReplayMeasurement.None;
        }

        ReplayMeasurement rawFallback = ReplayMeasurement.None;
        foreach (JsonElement variant in variants.EnumerateArray())
        {
            bool isPrimary = ReadBool(variant, "is_primary", false);
            bool hasAlignedRaw = ReadBool(variant, "has_aligned_raw", false);
            if (hasAlignedRaw && TryReadPose(variant, "aligned_raw_pos", "aligned_raw_rot", out Pose alignedRaw))
            {
                return new ReplayMeasurement(
                    true,
                    alignedRaw,
                    ReadNullableDouble(variant, "source_capture_mono_ms"),
                    ReadFloat(variant, "reliability_score", 1.0f),
                    ReadString(variant, "latest_phase", "TRACK"),
                    "TRACK");
            }

            string label = ReadString(variant, "label", "");
            bool hasStable = ReadBool(variant, "has_stable", false);
            if (label == "raw" && hasStable && TryReadPose(variant, "stable_pos", "stable_rot", out Pose rawStable))
            {
                rawFallback = new ReplayMeasurement(
                    true,
                    rawStable,
                    ReadNullableDouble(variant, "source_capture_mono_ms") ?? renderMonoMs,
                    ReadFloat(variant, "reliability_score", 1.0f),
                    ReadString(variant, "latest_phase", "TRACK"),
                    "TRACK");
            }

            if (isPrimary && rawFallback.HasPose)
            {
                rawFallback = new ReplayMeasurement(
                    rawFallback.HasPose,
                    rawFallback.Pose,
                    rawFallback.SourceCaptureMonoMs ?? renderMonoMs,
                    ReadFloat(variant, "reliability_score", rawFallback.ReliabilityScore),
                    ReadString(variant, "latest_phase", rawFallback.Phase),
                    rawFallback.PoseSource);
            }
        }

        return rawFallback.HasPose
            ? rawFallback
            : new ReplayMeasurement(false, Pose.identity, renderMonoMs, 0.0f, "NONE", "NONE");
    }

    private static List<StrategyRunner> CreateDefaultStrategies()
    {
        return new List<StrategyRunner>
        {
            new StrategyRunner("raw_zoh", CreateModule<NullGateModule>(), CreateModule<RawEstimatorModule>(), CreateModule<PassThroughOutputModule>()),
            new StrategyRunner("lowpass_predict", CreateModule<NullGateModule>(), CreateModule<LowPassEstimatorModule>(), CreateModule<PassThroughOutputModule>()),
            new StrategyRunner("kalman_cv", CreateModule<NullGateModule>(), CreateModule<KalmanEstimatorModule>(), CreateModule<PassThroughOutputModule>()),
            new StrategyRunner("oneeuro_vanilla", CreateModule<NullGateModule>(), CreateModule<OneEuroEstimatorModule>(), CreateModule<PassThroughOutputModule>()),
            new StrategyRunner("egoanchor_no_static", CreateModule<ScoreJumpGateModule>(), CreateModule<EgoAnchorEstimatorModule>(), CreateModule<PassThroughOutputModule>()),
            new StrategyRunner("egoanchor_full", CreateModule<ScoreJumpGateModule>(), CreateModule<EgoAnchorEstimatorModule>(), CreateModule<StaticLockRateLimitOutputModule>()),
        };
    }

    private static T CreateModule<T>() where T : UnityEngine.Object
    {
        T module = (T)RuntimeHelpers.GetUninitializedObject(typeof(T));
        MakeUnityObjectNonNull(module);
        if (module is AnchorGateModule gate)
        {
            gate.ResetModule();
        }
        else if (module is AnchorEstimatorModule estimator)
        {
            estimator.ResetModule();
        }
        else if (module is AnchorOutputStageModule output)
        {
            output.ResetModule();
        }

        return module;
    }

    private static void WriteSummary(List<StrategyRunner> strategies, string path)
    {
        using StreamWriter writer = new StreamWriter(path, append: false);
        writer.WriteLine("label,render_rows,measurement_rows,valid_gt_rows,static_jitter_pos_mm,static_jitter_rot_deg,moving_rmse_pos_mm,moving_rmse_rot_deg,lag_ms,max_zero_run,jump_reject_count,hold_count,lost_count");
        foreach (StrategyRunner strategy in strategies)
        {
            StrategyMetrics m = strategy.Metrics;
            writer.WriteLine(string.Join(",", new[]
            {
                strategy.Label,
                m.RenderRows.ToString(CultureInfo.InvariantCulture),
                m.MeasurementRows.ToString(CultureInfo.InvariantCulture),
                m.ValidGtRows.ToString(CultureInfo.InvariantCulture),
                Rms(m.StepPositionMeters).ToString("R", CultureInfo.InvariantCulture),
                Rms(m.StepRotationDegrees).ToString("R", CultureInfo.InvariantCulture),
                (Rms(m.PositionErrorsMeters) * 1000.0).ToString("R", CultureInfo.InvariantCulture),
                Rms(m.RotationErrorsDegrees).ToString("R", CultureInfo.InvariantCulture),
                Mean(m.PredictAheadMs).ToString("R", CultureInfo.InvariantCulture),
                m.MaxZeroRun.ToString(CultureInfo.InvariantCulture),
                m.JumpRejectCount.ToString(CultureInfo.InvariantCulture),
                m.HoldCount.ToString(CultureInfo.InvariantCulture),
                m.LostCount.ToString(CultureInfo.InvariantCulture),
            }));
        }
    }

    private static void WriteConfig(List<StrategyRunner> strategies, string path)
    {
        using StreamWriter writer = new StreamWriter(path, append: false);
        writer.WriteLine("{");
        writer.WriteLine("  \"strategies\": [");
        for (int i = 0; i < strategies.Count; i++)
        {
            StrategyRunner s = strategies[i];
            writer.Write($"    {{\"label\":\"{s.Label}\",\"gate_module\":\"{s.Gate.ModuleName}\",\"estimator_module\":\"{s.Estimator.ModuleName}\",\"output_module\":\"{s.Output.ModuleName}\"}}");
            writer.WriteLine(i + 1 < strategies.Count ? "," : "");
        }
        writer.WriteLine("  ]");
        writer.WriteLine("}");
    }

    private static string ResolveUniqueLog(string sessionDir, string pattern)
    {
        string[] matches = Directory.GetFiles(sessionDir, pattern, SearchOption.TopDirectoryOnly);
        if (matches.Length != 1)
        {
            throw new InvalidOperationException($"{sessionDir}: expected one {pattern}, got {matches.Length}");
        }

        return matches[0];
    }

    private static bool TryReadPose(JsonElement row, string posName, string rotName, out Pose pose)
    {
        pose = Pose.identity;
        if (!row.TryGetProperty(posName, out JsonElement pos) || pos.ValueKind == JsonValueKind.Null)
        {
            return false;
        }

        if (!row.TryGetProperty(rotName, out JsonElement rot) || rot.ValueKind == JsonValueKind.Null)
        {
            return false;
        }

        pose = new Pose(ReadVector3(pos), ReadQuaternion(rot));
        return true;
    }

    private static Pose ReadPose(JsonElement row, string posName, string rotName, bool valid)
    {
        return valid && TryReadPose(row, posName, rotName, out Pose pose) ? pose : Pose.identity;
    }

    private static Vector3 ReadVector3(JsonElement value)
    {
        return new Vector3(
            (float)value[0].GetDouble(),
            (float)value[1].GetDouble(),
            (float)value[2].GetDouble());
    }

    private static Quaternion ReadQuaternion(JsonElement value)
    {
        return new Quaternion(
            (float)value[0].GetDouble(),
            (float)value[1].GetDouble(),
            (float)value[2].GetDouble(),
            (float)value[3].GetDouble());
    }

    private static double? ReadNullableDouble(JsonElement row, string name)
    {
        if (!row.TryGetProperty(name, out JsonElement value) || value.ValueKind == JsonValueKind.Null)
        {
            return null;
        }

        return value.GetDouble();
    }

    private static double ReadDouble(JsonElement row, string name, double defaultValue)
    {
        return row.TryGetProperty(name, out JsonElement value) && value.ValueKind != JsonValueKind.Null ? value.GetDouble() : defaultValue;
    }

    private static float ReadFloat(JsonElement row, string name, float defaultValue)
    {
        return row.TryGetProperty(name, out JsonElement value) && value.ValueKind != JsonValueKind.Null ? value.GetSingle() : defaultValue;
    }

    private static int ReadInt(JsonElement row, string name, int defaultValue)
    {
        return row.TryGetProperty(name, out JsonElement value) && value.ValueKind != JsonValueKind.Null ? value.GetInt32() : defaultValue;
    }

    private static long ReadLong(JsonElement row, string name, long defaultValue)
    {
        return row.TryGetProperty(name, out JsonElement value) && value.ValueKind != JsonValueKind.Null ? value.GetInt64() : defaultValue;
    }

    private static bool ReadBool(JsonElement row, string name, bool defaultValue)
    {
        return row.TryGetProperty(name, out JsonElement value) && value.ValueKind != JsonValueKind.Null ? value.GetBoolean() : defaultValue;
    }

    private static string ReadString(JsonElement row, string name, string defaultValue)
    {
        return row.TryGetProperty(name, out JsonElement value) && value.ValueKind != JsonValueKind.Null ? value.GetString() ?? defaultValue : defaultValue;
    }

    private static double Rms(List<double> values)
    {
        if (values.Count == 0)
        {
            return double.NaN;
        }

        double sum = 0.0;
        foreach (double value in values)
        {
            sum += value * value;
        }

        return Math.Sqrt(sum / values.Count);
    }

    private static double Mean(List<double> values)
    {
        if (values.Count == 0)
        {
            return double.NaN;
        }

        double sum = 0.0;
        foreach (double value in values)
        {
            sum += value;
        }

        return sum / values.Count;
    }

    private static float QuaternionAngleDegrees(Quaternion a, Quaternion b)
    {
        float dot = Math.Abs(a.x * b.x + a.y * b.y + a.z * b.z + a.w * b.w);
        dot = Math.Min(1f, Math.Max(-1f, dot));
        return (float)(2.0 * Math.Acos(dot) * 180.0 / Math.PI);
    }

    private static void MakeUnityObjectNonNull(UnityEngine.Object unityObject)
    {
        const BindingFlags flags = BindingFlags.Instance | BindingFlags.NonPublic;
        typeof(UnityEngine.Object).GetField("m_CachedPtr", flags)?.SetValue(unityObject, new IntPtr(1));
        typeof(UnityEngine.Object).GetField("m_InstanceID", flags)?.SetValue(unityObject, 1);
    }

    private sealed class StrategyRunner
    {
        private readonly AnchorStateMachine stateMachine = new AnchorStateMachine();
        private GateDecision latestGate = GateDecision.Hold("initialized");
        private double lastAcceptedTime = -1.0;
        private float latestScore = 1.0f;
        private AnchorMotionState motionState = AnchorMotionState.Unknown;
        private Pose lastPose = Pose.identity;
        private bool hasLastPose;
        private int zeroRun;

        public StrategyRunner(string label, AnchorGateModule gate, AnchorEstimatorModule estimator, AnchorOutputStageModule output)
        {
            Label = label;
            Gate = gate;
            Estimator = estimator;
            Output = output;
        }

        public string Label { get; }
        public AnchorGateModule Gate { get; }
        public AnchorEstimatorModule Estimator { get; }
        public AnchorOutputStageModule Output { get; }
        public StrategyMetrics Metrics { get; } = new StrategyMetrics();

        public void Accept(AnchorObservation observation)
        {
            double time = observation.HasCaptureTime ? observation.CaptureTimeSeconds : observation.SampleTimeSeconds;
            AnchorEstimate predicted = Estimator.HasEstimate ? Estimator.PredictAt(time) : AnchorEstimate.Stationary(Pose.identity, time);
            latestGate = Gate.Evaluate(observation, predicted, Estimator.HasEstimate);
            if ((latestGate.Action == GateAction.Accept || latestGate.Action == GateAction.Snap) && observation.HasAlignedPose)
            {
                if (latestGate.Action == GateAction.Snap)
                {
                    Estimator.Snap(observation);
                }
                else
                {
                    Estimator.UpdateEstimate(observation);
                }

                lastAcceptedTime = time;
                latestScore = observation.ReliabilityScore;
                stateMachine.OnReliablePose(time, latestGate.Reason);
                Metrics.MeasurementRows++;
            }
            else if (latestGate.Action == GateAction.Reject)
            {
                stateMachine.OnUncertainPose(time, latestGate.Reason);
                Metrics.HoldCount++;
                if (latestGate.Reason.Contains("jump", StringComparison.OrdinalIgnoreCase))
                {
                    Metrics.JumpRejectCount++;
                }
            }
            else
            {
                stateMachine.OnMissingPose(time, lastAcceptedTime >= 0.0 ? time - lastAcceptedTime : double.PositiveInfinity, Estimator.HasEstimate, latestGate.Reason);
                Metrics.HoldCount++;
            }
        }

        public RecordedVariantSnapshot Advance(ReplayRow row, double renderSeconds)
        {
            Metrics.RenderRows++;
            if (!Estimator.HasEstimate)
            {
                return MakeSnapshot(row, false, Pose.identity, AnchorState.Searching, 0.0f);
            }

            double gap = lastAcceptedTime >= 0.0 ? Math.Max(0.0, renderSeconds - lastAcceptedTime) : double.PositiveInfinity;
            stateMachine.OnMissingPose(renderSeconds, gap, true, "stale_measurement");
            if (stateMachine.State == AnchorState.Lost)
            {
                Metrics.LostCount++;
                return MakeSnapshot(row, false, Pose.identity, stateMachine.State, (float)gap);
            }

            AnchorEstimate estimate = Estimator.PredictAt(renderSeconds);
            motionState = Estimator.LinearVelocity.magnitude < 0.015f && Estimator.AngularVelocityRad.magnitude * Mathf.Rad2Deg < 1.5f
                ? AnchorMotionState.Static
                : AnchorMotionState.Moving;
            OutputContext context = new OutputContext(lastAcceptedTime, gap, latestScore, stateMachine.State, motionState);
            Pose pose = Output.Condition(estimate, renderSeconds, context);
            UpdateMetrics(row, pose, gap);
            return MakeSnapshot(row, true, pose, stateMachine.State, (float)gap);
        }

        private RecordedVariantSnapshot MakeSnapshot(ReplayRow row, bool hasPose, Pose pose, AnchorState state, float predictAhead)
        {
            return new RecordedVariantSnapshot(
                Label,
                row.SourceFrameId,
                hasPose,
                pose,
                state.ToString(),
                latestGate.ToPolicyAction().ToString(),
                latestGate.Reason,
                row.Phase,
                "",
                hasPose ? "replay" : "none",
                row.SourceCaptureMonoMs.HasValue,
                row.SourceCaptureMonoMs ?? double.NaN,
                row.RenderUnityFrame,
                Label == "raw_zoh",
                row.HasRawPose,
                row.RawPose,
                false,
                Pose.identity,
                double.NaN,
                -1,
                "",
                row.ReliabilityScore,
                motionState.ToString(),
                predictAhead * 1000.0,
                Label,
                Gate.ModuleName,
                Estimator.ModuleName,
                Output.ModuleName,
                "",
                Output.LastResidualMeters,
                Output.LastResidualDegrees,
                latestScore,
                Output.IsStaticLocked);
        }

        private void UpdateMetrics(ReplayRow row, Pose pose, double gap)
        {
            Metrics.PredictAheadMs.Add(gap * 1000.0);
            if (row.GroundTruthValid)
            {
                Metrics.ValidGtRows++;
                Metrics.PositionErrorsMeters.Add(Vector3.Distance(pose.position, row.GroundTruthPose.position));
                Metrics.RotationErrorsDegrees.Add(QuaternionAngleDegrees(pose.rotation, row.GroundTruthPose.rotation));
            }

            if (hasLastPose)
            {
                double step = Vector3.Distance(pose.position, lastPose.position);
                double rotStep = QuaternionAngleDegrees(pose.rotation, lastPose.rotation);
                Metrics.StepPositionMeters.Add(step * 1000.0);
                Metrics.StepRotationDegrees.Add(rotStep);
                if (step < 1e-5 && rotStep < 1e-3)
                {
                    zeroRun++;
                }
                else
                {
                    zeroRun = 0;
                }

                Metrics.MaxZeroRun = Math.Max(Metrics.MaxZeroRun, zeroRun);
            }

            lastPose = pose;
            hasLastPose = true;
        }
    }

    private sealed class StrategyMetrics
    {
        public int RenderRows;
        public int MeasurementRows;
        public int ValidGtRows;
        public int MaxZeroRun;
        public int JumpRejectCount;
        public int HoldCount;
        public int LostCount;
        public readonly List<double> StepPositionMeters = new List<double>();
        public readonly List<double> StepRotationDegrees = new List<double>();
        public readonly List<double> PositionErrorsMeters = new List<double>();
        public readonly List<double> RotationErrorsDegrees = new List<double>();
        public readonly List<double> PredictAheadMs = new List<double>();
    }

    private readonly struct ReplayMeasurement
    {
        public static readonly ReplayMeasurement None = new ReplayMeasurement(false, Pose.identity, null, 0.0f, "", "");

        public ReplayMeasurement(bool hasPose, Pose pose, double? sourceCaptureMonoMs, float reliabilityScore, string phase, string poseSource)
        {
            HasPose = hasPose;
            Pose = pose;
            SourceCaptureMonoMs = sourceCaptureMonoMs;
            ReliabilityScore = reliabilityScore;
            Phase = phase ?? string.Empty;
            PoseSource = poseSource ?? string.Empty;
        }

        public bool HasPose { get; }
        public Pose Pose { get; }
        public double? SourceCaptureMonoMs { get; }
        public float ReliabilityScore { get; }
        public string Phase { get; }
        public string PoseSource { get; }
    }

    private readonly struct ReplayRow
    {
        public ReplayRow(
            double renderMonoMs,
            double renderUnixMs,
            int renderUnityFrame,
            long sourceFrameId,
            Pose headPose,
            Pose groundTruthPose,
            bool groundTruthValid,
            string groundTruthSource,
            bool hasRawPose,
            Pose rawPose,
            double? sourceCaptureMonoMs,
            float reliabilityScore,
            string phase,
            string poseSource)
        {
            RenderMonoMs = renderMonoMs;
            RenderUnixMs = renderUnixMs;
            RenderUnityFrame = renderUnityFrame;
            SourceFrameId = sourceFrameId;
            HeadPose = headPose;
            GroundTruthPose = groundTruthPose;
            GroundTruthValid = groundTruthValid;
            GroundTruthSource = groundTruthSource ?? string.Empty;
            HasRawPose = hasRawPose;
            RawPose = rawPose;
            SourceCaptureMonoMs = sourceCaptureMonoMs;
            ReliabilityScore = reliabilityScore;
            Phase = phase ?? string.Empty;
            PoseSource = poseSource ?? string.Empty;
        }

        public double RenderMonoMs { get; }
        public double RenderUnixMs { get; }
        public int RenderUnityFrame { get; }
        public long SourceFrameId { get; }
        public Pose HeadPose { get; }
        public Pose GroundTruthPose { get; }
        public bool GroundTruthValid { get; }
        public string GroundTruthSource { get; }
        public bool HasRawPose { get; }
        public Pose RawPose { get; }
        public double? SourceCaptureMonoMs { get; }
        public float ReliabilityScore { get; }
        public string Phase { get; }
        public string PoseSource { get; }
    }

    private sealed class Options
    {
        public string SessionDir { get; private set; }
        public string OutputDir { get; private set; }

        public static Options Parse(string[] args)
        {
            string session = "";
            string output = "";
            for (int i = 0; i < args.Length; i++)
            {
                if (args[i] == "--session" && i + 1 < args.Length)
                {
                    session = args[++i];
                }
                else if (args[i] == "--out" && i + 1 < args.Length)
                {
                    output = args[++i];
                }
            }

            if (string.IsNullOrWhiteSpace(session))
            {
                throw new ArgumentException("Usage: anchor_replay --session <session_dir> --out <output_dir>");
            }

            if (string.IsNullOrWhiteSpace(output))
            {
                output = Path.Combine(session, "anchor_replay");
            }

            return new Options { SessionDir = session, OutputDir = output };
        }
    }
}

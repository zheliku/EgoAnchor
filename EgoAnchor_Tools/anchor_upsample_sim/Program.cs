using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;
using EgoAnchor.Policy;
using UnityEngine;

/// <summary>
/// EgoAnchor baseline 离线实时升采样模拟入口。
/// </summary>
static class Program
{
    /// <summary>没有录制 render 时间时的回退渲染帧率，单位 Hz。</summary>
    private const double DefaultRenderHz = 60.0;

    /// <summary>输出 JSONL 文件名。</summary>
    private const string OutputJsonl = "upsample_sim_output.jsonl";

    /// <summary>输出摘要 CSV 文件名。</summary>
    private const string SummaryCsv = "upsample_sim_summary.csv";

    /// <summary>算法说明文件名。</summary>
    private const string NotesMarkdown = "algorithm_notes.md";

    /// <summary>
    /// 命令行入口。
    /// </summary>
    private static int Main(string[] args)
    {
        try
        {
            Options options = Options.Parse(args);
            if (options.SelfTest)
            {
                SelfTest.Run();
                Console.WriteLine("Anchor upsample simulator self-test passed.");
                return 0;
            }

            Directory.CreateDirectory(options.OutputDir);
            Directory.CreateDirectory(Path.Combine(options.OutputDir, "charts"));
            SessionData session = SessionLoader.Load(options.SessionDir);
            SimulationResult result = Simulator.Run(session, options.RenderHz);
            OutputWriter.WriteAll(result, options.OutputDir);
            Console.WriteLine($"anchor upsample sim observations={session.Observations.Count}, render_rows={result.Rows.Count}, algorithms={result.Algorithms.Count}");
            Console.WriteLine(Path.Combine(options.OutputDir, OutputJsonl));
            Console.WriteLine(Path.Combine(options.OutputDir, SummaryCsv));
            Console.WriteLine(Path.Combine(options.OutputDir, "charts"));
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[AnchorUpsampleSim] {ex.Message}");
            return 1;
        }
    }

    /// <summary>
    /// 创建默认 baseline 列表。
    /// </summary>
    private static List<IPosePredictor> CreateBaselinePredictors()
    {
        return new List<IPosePredictor>
        {
            new ModulePredictor("raw_none", "什么都不处理：最近一次观测 pose 的 zero-order hold。", CreateModule<RawEstimatorModule>()),
            new ModulePredictor("kalman_prediction", "卡尔曼滤波 + 预测：常速度 Kalman 状态在 render tick 前推。", CreateModule<KalmanEstimatorModule>()),
            new DeadReckoningSplinePredictor(),
            new ResidualBlendPredictor(),
            new ModulePredictor("oneeuro_prediction", "One Euro Filter + 预测：自适应低通后用滤波速度短窗口前推。", CreateModule<OneEuroEstimatorModule>()),
        };
    }

    /// <summary>
    /// 创建不依赖 Unity 场景生命周期的 policy module。
    /// </summary>
    private static T CreateModule<T>() where T : UnityEngine.Object
    {
        T module = (T)RuntimeHelpers.GetUninitializedObject(typeof(T));
        MakeUnityObjectNonNull(module);
        if (module is AnchorEstimatorModule estimator)
        {
            estimator.ResetModule();
        }

        return module;
    }

    /// <summary>
    /// 为 headless dotnet 运行补齐 UnityEngine.Object 的非空判定字段。
    /// </summary>
    private static void MakeUnityObjectNonNull(UnityEngine.Object unityObject)
    {
        const BindingFlags flags = BindingFlags.Instance | BindingFlags.NonPublic;
        typeof(UnityEngine.Object).GetField("m_CachedPtr", flags)?.SetValue(unityObject, new IntPtr(1));
        typeof(UnityEngine.Object).GetField("m_InstanceID", flags)?.SetValue(unityObject, 1);
    }

    /// <summary>
    /// 命令行参数。
    /// </summary>
    private sealed class Options
    {
        /// <summary>是否运行内置自测。</summary>
        public bool SelfTest { get; private set; }

        /// <summary>输入 session 目录。</summary>
        public string SessionDir { get; private set; }

        /// <summary>输出目录。</summary>
        public string OutputDir { get; private set; }

        /// <summary>没有录制 render 时间时的回退渲染帧率，单位 Hz。</summary>
        public double RenderHz { get; private set; } = DefaultRenderHz;

        /// <summary>
        /// 解析命令行参数。
        /// </summary>
        public static Options Parse(string[] args)
        {
            Options options = new Options();
            for (int i = 0; i < args.Length; i++)
            {
                string arg = args[i];
                if (arg == "--self-test")
                {
                    options.SelfTest = true;
                }
                else if (arg == "--session" && i + 1 < args.Length)
                {
                    options.SessionDir = args[++i];
                }
                else if (arg == "--out" && i + 1 < args.Length)
                {
                    options.OutputDir = args[++i];
                }
                else if (arg == "--render-hz" && i + 1 < args.Length)
                {
                    options.RenderHz = double.Parse(args[++i], CultureInfo.InvariantCulture);
                }
                else
                {
                    throw new ArgumentException($"Unknown or incomplete argument: {arg}");
                }
            }

            if (options.SelfTest)
            {
                return options;
            }

            if (string.IsNullOrWhiteSpace(options.SessionDir))
            {
                throw new ArgumentException("Usage: anchor_upsample_sim --session <session_dir> [--out <output_dir>] [--render-hz 60]");
            }

            if (string.IsNullOrWhiteSpace(options.OutputDir))
            {
                options.OutputDir = Path.Combine(options.SessionDir, "anchor_upsample_sim");
            }

            if (options.RenderHz <= 0.0)
            {
                throw new ArgumentException("--render-hz must be positive.");
            }

            options.SessionDir = Path.GetFullPath(options.SessionDir);
            options.OutputDir = Path.GetFullPath(options.OutputDir);
            return options;
        }
    }

    /// <summary>
    /// 会话数据加载器。
    /// </summary>
    private static class SessionLoader
    {
        /// <summary>
        /// 从 session 目录读取唯一的 unity_output 日志。
        /// </summary>
        public static SessionData Load(string sessionDir)
        {
            string outputPath = ResolveUniqueLog(sessionDir, "*_unity_output.jsonl");
            List<ObservationSample> observations = new List<ObservationSample>();
            List<double> renderMonoTimesMs = new List<double>();
            HashSet<long> seenFrames = new HashSet<long>();
            double firstRenderMs = double.NaN;
            double lastRenderMs = double.NaN;
            double unixOffsetMs = double.NaN;
            int sourceRows = 0;

            foreach (string line in File.ReadLines(outputPath))
            {
                if (string.IsNullOrWhiteSpace(line))
                {
                    continue;
                }

                using JsonDocument doc = JsonDocument.Parse(line);
                JsonElement root = doc.RootElement;
                if (!string.Equals(ReadString(root, "event", ""), "unity_output", StringComparison.Ordinal))
                {
                    continue;
                }

                double renderMs = ReadDouble(root, "render_mono_ms", double.NaN);
                double renderUnixMs = ReadDouble(root, "render_unix_ms", double.NaN);
                if (double.IsNaN(renderMs))
                {
                    continue;
                }

                renderMonoTimesMs.Add(renderMs);
                if (double.IsNaN(firstRenderMs))
                {
                    firstRenderMs = renderMs;
                }

                lastRenderMs = renderMs;
                if (double.IsNaN(unixOffsetMs) && !double.IsNaN(renderMs) && !double.IsNaN(renderUnixMs))
                {
                    unixOffsetMs = renderUnixMs - renderMs;
                }

                sourceRows++;
                if (!TryExtractPrimaryObservation(root, renderMs, seenFrames, out ObservationSample observation))
                {
                    continue;
                }

                observations.Add(observation);
            }

            if (sourceRows == 0)
            {
                throw new InvalidOperationException($"{outputPath}: no unity_output rows found.");
            }

            if (observations.Count == 0)
            {
                throw new InvalidOperationException($"{outputPath}: no primary aligned_raw observations found.");
            }

            observations.Sort((a, b) => a.AvailableMonoMs.CompareTo(b.AvailableMonoMs));
            return new SessionData(sessionDir, outputPath, firstRenderMs, lastRenderMs, unixOffsetMs, observations, renderMonoTimesMs);
        }

        /// <summary>
        /// 提取 primary aligned raw 观测，并按 source_frame_id 去重。
        /// </summary>
        private static bool TryExtractPrimaryObservation(JsonElement root, double availableMonoMs, HashSet<long> seenFrames, out ObservationSample observation)
        {
            observation = default;
            if (!root.TryGetProperty("variants", out JsonElement variants) || variants.ValueKind != JsonValueKind.Array)
            {
                return false;
            }

            foreach (JsonElement variant in variants.EnumerateArray())
            {
                if (!ReadBool(variant, "is_primary", false) || !ReadBool(variant, "has_aligned_raw", false))
                {
                    continue;
                }

                long frameId = ReadLong(variant, "source_frame_id", -1);
                if (frameId < 0 || !seenFrames.Add(frameId))
                {
                    return false;
                }

                if (!TryReadPose(variant, "aligned_raw_pos", "aligned_raw_rot", out Pose pose))
                {
                    return false;
                }

                double captureMs = ReadDouble(variant, "source_capture_mono_ms", availableMonoMs);
                observation = new ObservationSample(
                    frameId,
                    captureMs,
                    availableMonoMs,
                    pose,
                    ReadFloat(variant, "reliability_score", 1.0f),
                    ReadString(variant, "latest_phase", "TRACK"));
                return true;
            }

            return false;
        }

        /// <summary>
        /// 解析唯一日志路径。
        /// </summary>
        private static string ResolveUniqueLog(string sessionDir, string pattern)
        {
            string[] matches = Directory.GetFiles(sessionDir, pattern, SearchOption.TopDirectoryOnly);
            if (matches.Length != 1)
            {
                throw new InvalidOperationException($"{sessionDir}: expected one {pattern}, got {matches.Length}");
            }

            return matches[0];
        }
    }

    /// <summary>
    /// 离线模拟器。
    /// </summary>
    private static class Simulator
    {
        /// <summary>
        /// 按录制的 render clock 运行实时预测；没有录制时间时才回退到固定频率。
        /// </summary>
        public static SimulationResult Run(SessionData session, double renderHz)
        {
            List<IPosePredictor> predictors = CreateBaselinePredictors();
            List<RenderRow> rows = new List<RenderRow>();
            List<double> renderTimesMs = ResolveRenderTimes(session, renderHz);
            int nextObservation = 0;
            ObservationSample latestObservation = default;
            bool hasLatestObservation = false;
            int renderIndex = 0;

            foreach (double renderMs in renderTimesMs)
            {
                while (nextObservation < session.Observations.Count
                    && session.Observations[nextObservation].AvailableMonoMs <= renderMs + 1e-6)
                {
                    latestObservation = session.Observations[nextObservation++];
                    hasLatestObservation = true;
                    foreach (IPosePredictor predictor in predictors)
                    {
                        predictor.Accept(latestObservation);
                    }
                }

                List<VariantSample> variants = new List<VariantSample>(predictors.Count);
                double renderSeconds = renderMs / 1000.0;
                foreach (IPosePredictor predictor in predictors)
                {
                    variants.Add(predictor.Predict(renderSeconds));
                }

                rows.Add(new RenderRow(
                    renderMs,
                    double.IsNaN(session.UnixOffsetMs) ? double.NaN : renderMs + session.UnixOffsetMs,
                    renderIndex++,
                    hasLatestObservation,
                    latestObservation,
                    variants));
            }

            return new SimulationResult(session, predictors, rows);
        }

        /// <summary>
        /// 获取 render 时间轴，优先使用 Unity 日志真实 render_mono_ms。
        /// </summary>
        private static List<double> ResolveRenderTimes(SessionData session, double renderHz)
        {
            if (session.RenderMonoTimesMs.Count > 0)
            {
                return new List<double>(session.RenderMonoTimesMs);
            }

            List<double> renderTimesMs = new List<double>();
            double dtMs = 1000.0 / renderHz;
            double startMs = Math.Min(session.FirstRenderMonoMs, session.Observations[0].AvailableMonoMs);
            double endMs = Math.Max(session.LastRenderMonoMs, session.Observations[session.Observations.Count - 1].AvailableMonoMs);
            for (double renderMs = startMs; renderMs <= endMs + 1e-6; renderMs += dtMs)
            {
                renderTimesMs.Add(renderMs);
            }

            return renderTimesMs;
        }
    }

    /// <summary>
    /// 预测器接口。
    /// </summary>
    private interface IPosePredictor
    {
        /// <summary>算法标签。</summary>
        string Label { get; }

        /// <summary>中文算法说明。</summary>
        string Description { get; }

        /// <summary>接收一帧低频观测。</summary>
        void Accept(ObservationSample observation);

        /// <summary>预测当前渲染时刻的 pose。</summary>
        VariantSample Predict(double renderSeconds);
    }

    /// <summary>
    /// 复用现有 Unity estimator module 的 baseline 包装。
    /// </summary>
    private sealed class ModulePredictor : IPosePredictor
    {
        /// <summary>算法标签。</summary>
        private readonly string label;

        /// <summary>中文算法说明。</summary>
        private readonly string description;

        /// <summary>现有 Unity estimator module。</summary>
        private readonly AnchorEstimatorModule estimator;

        /// <summary>最近一次观测。</summary>
        private ObservationSample latestObservation;

        /// <summary>是否已有观测。</summary>
        private bool hasObservation;

        /// <summary>
        /// 构造 estimator 包装器。
        /// </summary>
        public ModulePredictor(string label, string description, AnchorEstimatorModule estimator)
        {
            this.label = label;
            this.description = description;
            this.estimator = estimator;
        }

        /// <summary>算法标签。</summary>
        public string Label => label;

        /// <summary>中文算法说明。</summary>
        public string Description => description;

        /// <summary>
        /// 把低频观测提交给现有 estimator。
        /// </summary>
        public void Accept(ObservationSample observation)
        {
            AnchorObservation anchorObservation = AnchorObservation.FromAlignedPose(
                observation.FrameId,
                observation.Pose,
                observation.AvailableSeconds,
                observation.ReliabilityScore,
                Array.Empty<string>(),
                observation.Phase,
                "TRACK",
                observation.CaptureSeconds);

            if (!estimator.HasEstimate)
            {
                estimator.Snap(anchorObservation);
            }
            else
            {
                estimator.UpdateEstimate(anchorObservation);
            }

            latestObservation = observation;
            hasObservation = true;
        }

        /// <summary>
        /// 预测当前渲染时刻。
        /// </summary>
        public VariantSample Predict(double renderSeconds)
        {
            if (!estimator.HasEstimate || !hasObservation)
            {
                return VariantSample.None(label, "no_estimate");
            }

            AnchorEstimate estimate = estimator.PredictAt(renderSeconds);
            return new VariantSample(
                label,
                true,
                latestObservation.FrameId,
                estimate.Pose,
                estimate.PredictAheadSeconds * 1000.0,
                latestObservation.ReliabilityScore,
                "predict");
        }
    }

    /// <summary>
    /// 航位推测 + 样条修正 baseline。
    /// </summary>
    private sealed class DeadReckoningSplinePredictor : IPosePredictor
    {
        /// <summary>修正窗口时长，单位秒。</summary>
        private const double CorrectionSeconds = 0.12;

        /// <summary>最大前推时长，单位秒。</summary>
        private const float MaxPredictAheadSeconds = 0.25f;

        /// <summary>最近一次观测。</summary>
        private ObservationSample latestObservation;

        /// <summary>上一次观测。</summary>
        private ObservationSample previousObservation;

        /// <summary>是否已有最近观测。</summary>
        private bool hasLatestObservation;

        /// <summary>是否已有上一次观测。</summary>
        private bool hasPreviousObservation;

        /// <summary>当前线速度，单位 m/s。</summary>
        private Vector3 linearVelocity;

        /// <summary>当前角速度，单位 rad/s。</summary>
        private Vector3 angularVelocityRad;

        /// <summary>修正开始时的旧预测 pose。</summary>
        private Pose correctionStartPose = Pose.identity;

        /// <summary>修正开始时旧预测使用的线速度。</summary>
        private Vector3 correctionStartVelocity;

        /// <summary>修正开始时旧预测使用的角速度。</summary>
        private Vector3 correctionStartAngularVelocityRad;

        /// <summary>修正开始时间，单位秒。</summary>
        private double correctionStartSeconds;

        /// <summary>修正结束时间，单位秒。</summary>
        private double correctionEndSeconds;

        /// <summary>是否正在进行样条修正。</summary>
        private bool hasCorrection;

        /// <summary>算法标签。</summary>
        public string Label => "dead_reckoning_spline";

        /// <summary>中文算法说明。</summary>
        public string Description => "航位推测 + 样条修正：render tick 按观测速度外推，新观测到达后用 smoothstep 三次曲线吸收预测误差。";

        /// <summary>
        /// 接收新观测并启动平滑修正。
        /// </summary>
        public void Accept(ObservationSample observation)
        {
            Pose oldPrediction = hasLatestObservation
                ? Predict(observation.AvailableSeconds).Pose
                : observation.Pose;
            Vector3 oldVelocity = linearVelocity;
            Vector3 oldAngularVelocity = angularVelocityRad;

            if (hasLatestObservation)
            {
                previousObservation = latestObservation;
                hasPreviousObservation = true;
            }

            latestObservation = observation;
            hasLatestObservation = true;

            if (hasPreviousObservation)
            {
                float dt = Mathf.Max((float)(latestObservation.CaptureSeconds - previousObservation.CaptureSeconds), 1e-5f);
                Vector3 observedLinear = (latestObservation.Pose.position - previousObservation.Pose.position) / dt;
                Vector3 observedAngular = AnchorMath.AngularVelocity(previousObservation.Pose.rotation, latestObservation.Pose.rotation, dt);
                linearVelocity = Vector3.Lerp(linearVelocity, observedLinear, 0.85f);
                angularVelocityRad = Vector3.Lerp(angularVelocityRad, observedAngular, 0.85f);
            }
            else
            {
                linearVelocity = Vector3.zero;
                angularVelocityRad = Vector3.zero;
            }

            correctionStartPose = oldPrediction;
            correctionStartVelocity = oldVelocity;
            correctionStartAngularVelocityRad = oldAngularVelocity;
            correctionStartSeconds = observation.AvailableSeconds;
            correctionEndSeconds = correctionStartSeconds + CorrectionSeconds;
            hasCorrection = true;
        }

        /// <summary>
        /// 预测当前渲染时刻。
        /// </summary>
        public VariantSample Predict(double renderSeconds)
        {
            if (!hasLatestObservation)
            {
                return VariantSample.None(Label, "no_estimate");
            }

            Pose deadReckoned = PredictFromLatestObservation(renderSeconds);
            Pose pose = deadReckoned;
            string reason = "dead_reckon";
            if (hasCorrection && renderSeconds >= correctionStartSeconds && renderSeconds <= correctionEndSeconds)
            {
                float t = Mathf.Clamp01((float)((renderSeconds - correctionStartSeconds) / CorrectionSeconds));
                float smooth = t * t * (3.0f - 2.0f * t);
                Pose oldPath = AnchorMath.Integrate(
                    correctionStartPose,
                    correctionStartVelocity,
                    correctionStartAngularVelocityRad,
                    Mathf.Max((float)(renderSeconds - correctionStartSeconds), 0.0f));
                pose = BlendPose(oldPath, deadReckoned, smooth);
                reason = "spline_correction";
            }

            double ahead = Math.Max(0.0, renderSeconds - latestObservation.CaptureSeconds);
            return new VariantSample(
                Label,
                true,
                latestObservation.FrameId,
                pose,
                Math.Min(ahead, MaxPredictAheadSeconds) * 1000.0,
                latestObservation.ReliabilityScore,
                reason);
        }

        /// <summary>
        /// 从最近一次观测按当前速度做航位推测。
        /// </summary>
        private Pose PredictFromLatestObservation(double renderSeconds)
        {
            float ahead = Mathf.Clamp((float)(renderSeconds - latestObservation.CaptureSeconds), 0.0f, MaxPredictAheadSeconds);
            return AnchorMath.Integrate(latestObservation.Pose, linearVelocity, angularVelocityRad, ahead);
        }

        /// <summary>
        /// 平滑混合两个 pose。
        /// </summary>
        private static Pose BlendPose(in Pose from, in Pose to, float alpha)
        {
            float t = Mathf.Clamp01(alpha);
            Quaternion aligned = AnchorMath.AlignHemisphere(from.rotation, to.rotation);
            Vector3 delta = AnchorMath.Log(AnchorMath.Multiply(AnchorMath.Inverse(from.rotation), aligned));
            return new Pose(
                Vector3.Lerp(from.position, to.position, t),
                AnchorMath.Multiply(from.rotation, AnchorMath.Exp(delta * t)));
        }
    }

    /// <summary>
    /// 历史残差淡化预测 baseline。
    /// 该算法模拟 VR runtime 常见的“高频预测 + 历史残差纠偏 + 分帧误差偿还”流程。
    /// </summary>
    private sealed class ResidualBlendPredictor : IPosePredictor
    {
        /// <summary>每个 60Hz render 帧偿还的残差比例。</summary>
        private const float ErrorPaybackPer60HzFrame = 0.10f;

        /// <summary>历史预测缓存时长，单位秒。</summary>
        private const double HistorySeconds = 2.0;

        /// <summary>最大线速度，单位 m/s，避免低频观测异常造成预测飞出。</summary>
        private const float MaxLinearVelocity = 1.5f;

        /// <summary>最大角速度，单位 rad/s。</summary>
        private const float MaxAngularVelocityRad = 3.5f;

        /// <summary>最近一次观测。</summary>
        private ObservationSample latestObservation;

        /// <summary>上一次观测。</summary>
        private ObservationSample previousObservation;

        /// <summary>是否已有最近观测。</summary>
        private bool hasLatestObservation;

        /// <summary>是否已有上一次观测。</summary>
        private bool hasPreviousObservation;

        /// <summary>当前连续输出 pose。</summary>
        private Pose currentPose = Pose.identity;

        /// <summary>当前输出时间，单位秒。</summary>
        private double currentTimeSeconds;

        /// <summary>是否已有可连续输出的 pose。</summary>
        private bool hasPose;

        /// <summary>当前线速度，单位 m/s。</summary>
        private Vector3 linearVelocity;

        /// <summary>当前角速度，单位 rad/s。</summary>
        private Vector3 angularVelocityRad;

        /// <summary>待偿还的世界平移残差。</summary>
        private Vector3 remainingPositionResidual;

        /// <summary>待偿还的旋转残差，旋转向量单位 rad。</summary>
        private Vector3 remainingRotationResidualRad;

        /// <summary>历史 render 输出记录。</summary>
        private readonly List<HistorySample> history = new List<HistorySample>();

        /// <summary>算法标签。</summary>
        public string Label => "residual_blend_prediction";

        /// <summary>中文算法说明。</summary>
        public string Description => "历史残差淡化预测：render 帧持续按运动状态外推；低频观测到达时查历史预测误差，只把残差加入待偿还队列，后续每帧约偿还 10%，避免一次性跳变。";

        /// <summary>
        /// 接收低频观测，计算历史预测残差但不直接覆盖当前输出。
        /// </summary>
        public void Accept(ObservationSample observation)
        {
            if (!hasPose)
            {
                currentPose = observation.Pose;
                currentTimeSeconds = observation.AvailableSeconds;
                latestObservation = observation;
                hasLatestObservation = true;
                hasPose = true;
                StoreHistory(currentTimeSeconds, currentPose);
                return;
            }

            Pose historicalPrediction = FindHistoricalPrediction(observation.CaptureSeconds);
            remainingPositionResidual += observation.Pose.position - historicalPrediction.position;

            Quaternion alignedObservation = AnchorMath.AlignHemisphere(historicalPrediction.rotation, observation.Pose.rotation);
            Quaternion residualRotation = AnchorMath.Multiply(AnchorMath.Inverse(historicalPrediction.rotation), alignedObservation);
            remainingRotationResidualRad += AnchorMath.Log(residualRotation);

            if (hasLatestObservation)
            {
                previousObservation = latestObservation;
                hasPreviousObservation = true;
            }

            latestObservation = observation;
            hasLatestObservation = true;
            UpdateVelocity();
        }

        /// <summary>
        /// 高频 render 时刻输出当前连续预测 pose，并分帧偿还历史残差。
        /// </summary>
        public VariantSample Predict(double renderSeconds)
        {
            if (!hasPose || !hasLatestObservation)
            {
                return VariantSample.None(Label, "no_estimate");
            }

            float dt = Mathf.Max((float)(renderSeconds - currentTimeSeconds), 0.0f);
            if (dt > 0.0f)
            {
                currentPose = AnchorMath.Integrate(currentPose, linearVelocity, angularVelocityRad, dt);
                float payback = PaybackAlpha(dt);
                Vector3 positionStep = remainingPositionResidual * payback;
                Vector3 rotationStep = remainingRotationResidualRad * payback;
                currentPose = new Pose(
                    currentPose.position + positionStep,
                    AnchorMath.Multiply(currentPose.rotation, AnchorMath.Exp(rotationStep)));
                remainingPositionResidual -= positionStep;
                remainingRotationResidualRad -= rotationStep;
                currentTimeSeconds = renderSeconds;
            }

            StoreHistory(renderSeconds, currentPose);
            return new VariantSample(
                Label,
                true,
                latestObservation.FrameId,
                currentPose,
                Math.Max(0.0, renderSeconds - latestObservation.CaptureSeconds) * 1000.0,
                latestObservation.ReliabilityScore,
                remainingPositionResidual.sqrMagnitude > 1e-10f || remainingRotationResidualRad.sqrMagnitude > 1e-10f
                    ? "residual_payback"
                    : "predict");
        }

        /// <summary>
        /// 根据最近两帧观测更新运动速度。
        /// </summary>
        private void UpdateVelocity()
        {
            if (!hasPreviousObservation)
            {
                return;
            }

            float dt = Mathf.Max((float)(latestObservation.CaptureSeconds - previousObservation.CaptureSeconds), 1e-5f);
            Vector3 observedLinear = (latestObservation.Pose.position - previousObservation.Pose.position) / dt;
            Vector3 observedAngular = AnchorMath.AngularVelocity(previousObservation.Pose.rotation, latestObservation.Pose.rotation, dt);
            linearVelocity = Vector3.Lerp(linearVelocity, ClampMagnitude(observedLinear, MaxLinearVelocity), 0.50f);
            angularVelocityRad = Vector3.Lerp(angularVelocityRad, ClampMagnitude(observedAngular, MaxAngularVelocityRad), 0.50f);
        }

        /// <summary>
        /// 查询指定历史时刻附近的已输出预测 pose。
        /// </summary>
        private Pose FindHistoricalPrediction(double timeSeconds)
        {
            if (history.Count == 0)
            {
                return currentPose;
            }

            HistorySample before = history[0];
            HistorySample after = history[history.Count - 1];
            bool hasBefore = false;
            bool hasAfter = false;
            foreach (HistorySample sample in history)
            {
                if (sample.TimeSeconds <= timeSeconds)
                {
                    before = sample;
                    hasBefore = true;
                }

                if (sample.TimeSeconds >= timeSeconds)
                {
                    after = sample;
                    hasAfter = true;
                    break;
                }
            }

            if (!hasBefore)
            {
                return history[0].Pose;
            }

            if (!hasAfter)
            {
                return history[history.Count - 1].Pose;
            }

            double span = after.TimeSeconds - before.TimeSeconds;
            if (span <= 1e-6)
            {
                return before.Pose;
            }

            float alpha = Mathf.Clamp01((float)((timeSeconds - before.TimeSeconds) / span));
            return BlendPose(before.Pose, after.Pose, alpha);
        }

        /// <summary>
        /// 保存历史输出，并删除过旧记录。
        /// </summary>
        private void StoreHistory(double timeSeconds, Pose pose)
        {
            if (history.Count > 0 && timeSeconds < history[history.Count - 1].TimeSeconds - 1e-6)
            {
                history.Clear();
            }

            if (history.Count == 0 || Math.Abs(history[history.Count - 1].TimeSeconds - timeSeconds) > 1e-6)
            {
                history.Add(new HistorySample(timeSeconds, pose));
            }
            else
            {
                history[history.Count - 1] = new HistorySample(timeSeconds, pose);
            }

            double oldest = timeSeconds - HistorySeconds;
            while (history.Count > 1 && history[0].TimeSeconds < oldest)
            {
                history.RemoveAt(0);
            }
        }

        /// <summary>
        /// 将每 60Hz 帧 10% 的偿还率换算到真实非均匀 render dt。
        /// </summary>
        private static float PaybackAlpha(float dt)
        {
            double frameCount = Math.Max(dt, 0.0f) * 60.0;
            return Mathf.Clamp01((float)(1.0 - Math.Pow(1.0 - ErrorPaybackPer60HzFrame, frameCount)));
        }

        /// <summary>
        /// 平滑混合两个 pose。
        /// </summary>
        private static Pose BlendPose(in Pose from, in Pose to, float alpha)
        {
            float t = Mathf.Clamp01(alpha);
            Quaternion aligned = AnchorMath.AlignHemisphere(from.rotation, to.rotation);
            Vector3 delta = AnchorMath.Log(AnchorMath.Multiply(AnchorMath.Inverse(from.rotation), aligned));
            return new Pose(
                Vector3.Lerp(from.position, to.position, t),
                AnchorMath.Multiply(from.rotation, AnchorMath.Exp(delta * t)));
        }

        /// <summary>
        /// 限幅向量长度。
        /// </summary>
        private static Vector3 ClampMagnitude(Vector3 value, float maxMagnitude)
        {
            float max = Mathf.Max(maxMagnitude, 0.0f);
            return value.magnitude > max && max > 0.0f ? value.normalized * max : value;
        }

        /// <summary>
        /// 单条历史输出记录。
        /// </summary>
        private readonly struct HistorySample
        {
            /// <summary>输出时间，单位秒。</summary>
            public readonly double TimeSeconds;

            /// <summary>当时已经输出给 render 的 pose。</summary>
            public readonly Pose Pose;

            /// <summary>
            /// 构造历史输出记录。
            /// </summary>
            public HistorySample(double timeSeconds, Pose pose)
            {
                TimeSeconds = timeSeconds;
                Pose = pose;
            }
        }
    }

    /// <summary>
    /// 输出写入器。
    /// </summary>
    private static class OutputWriter
    {
        /// <summary>
        /// 写出全部结果文件。
        /// </summary>
        public static void WriteAll(SimulationResult result, string outputDir)
        {
            WriteJsonl(result, Path.Combine(outputDir, OutputJsonl));
            WriteSummary(result, Path.Combine(outputDir, SummaryCsv));
            WriteNotes(result, Path.Combine(outputDir, NotesMarkdown));
            string chartsDir = Path.Combine(outputDir, "charts");
            Directory.CreateDirectory(chartsDir);
            foreach (IPosePredictor algorithm in result.Algorithms)
            {
                SvgChartWriter.WriteAlgorithmChart(result, algorithm.Label, Path.Combine(chartsDir, $"{algorithm.Label}.svg"));
            }
        }

        /// <summary>
        /// 写出逐 render tick JSONL。
        /// </summary>
        private static void WriteJsonl(SimulationResult result, string path)
        {
            using StreamWriter writer = new StreamWriter(path, append: false, Encoding.UTF8);
            foreach (RenderRow row in result.Rows)
            {
                writer.WriteLine(JsonLine(row));
            }
        }

        /// <summary>
        /// 构造一行 JSON。
        /// </summary>
        private static string JsonLine(RenderRow row)
        {
            StringBuilder builder = new StringBuilder(2048);
            bool first = true;
            builder.Append('{');
            AppendString(builder, ref first, "event", "upsample_sim_render");
            AppendDouble(builder, ref first, "render_mono_ms", row.RenderMonoMs);
            AppendDouble(builder, ref first, "render_unix_ms", row.RenderUnixMs);
            AppendLong(builder, ref first, "render_index", row.RenderIndex);
            AppendBool(builder, ref first, "obs_has_pose", row.HasObservation);
            AppendLong(builder, ref first, "obs_source_frame_id", row.HasObservation ? row.Observation.FrameId : -1);
            AppendDouble(builder, ref first, "obs_source_capture_mono_ms", row.HasObservation ? row.Observation.CaptureMonoMs : double.NaN);
            AppendDouble(builder, ref first, "obs_available_mono_ms", row.HasObservation ? row.Observation.AvailableMonoMs : double.NaN);
            AppendDouble(builder, ref first, "obs_age_ms", row.HasObservation ? row.RenderMonoMs - row.Observation.CaptureMonoMs : double.NaN);
            AppendFloat(builder, ref first, "obs_reliability_score", row.HasObservation ? row.Observation.ReliabilityScore : float.NaN);
            AppendName(builder, ref first, "variants");
            builder.Append('[');
            for (int i = 0; i < row.Variants.Count; i++)
            {
                if (i > 0)
                {
                    builder.Append(',');
                }

                AppendVariant(builder, row.Variants[i]);
            }

            builder.Append(']');
            builder.Append('}');
            return builder.ToString();
        }

        /// <summary>
        /// 写出单个算法变体。
        /// </summary>
        private static void AppendVariant(StringBuilder builder, VariantSample variant)
        {
            bool first = true;
            builder.Append('{');
            AppendString(builder, ref first, "label", variant.Label);
            AppendBool(builder, ref first, "has_pose", variant.HasPose);
            AppendLong(builder, ref first, "source_frame_id", variant.SourceFrameId);
            AppendPose(builder, ref first, "pos", "rot", variant.Pose, variant.HasPose);
            AppendDouble(builder, ref first, "predict_ahead_ms", variant.PredictAheadMs);
            AppendFloat(builder, ref first, "latest_score", variant.LatestScore);
            AppendString(builder, ref first, "reason", variant.Reason);
            builder.Append('}');
        }

        /// <summary>
        /// 写出摘要 CSV。
        /// </summary>
        private static void WriteSummary(SimulationResult result, string path)
        {
            Dictionary<string, Metrics> metrics = Metrics.Compute(result);
            using StreamWriter writer = new StreamWriter(path, append: false, Encoding.UTF8);
            writer.WriteLine("label,render_rows,observation_rows,mean_obs_age_ms,step_pos_rms_mm,step_rot_rms_deg,max_step_pos_mm,max_step_rot_deg,obs_instant_error_rms_mm,obs_instant_rot_error_rms_deg");
            foreach (IPosePredictor algorithm in result.Algorithms)
            {
                Metrics m = metrics[algorithm.Label];
                writer.WriteLine(string.Join(",", new[]
                {
                    algorithm.Label,
                    m.RenderRows.ToString(CultureInfo.InvariantCulture),
                    result.Session.Observations.Count.ToString(CultureInfo.InvariantCulture),
                    Mean(m.ObservationAgeMs).ToString("R", CultureInfo.InvariantCulture),
                    Rms(m.StepPositionMm).ToString("R", CultureInfo.InvariantCulture),
                    Rms(m.StepRotationDeg).ToString("R", CultureInfo.InvariantCulture),
                    Max(m.StepPositionMm).ToString("R", CultureInfo.InvariantCulture),
                    Max(m.StepRotationDeg).ToString("R", CultureInfo.InvariantCulture),
                    Rms(m.ObservationInstantErrorMm).ToString("R", CultureInfo.InvariantCulture),
                    Rms(m.ObservationInstantRotationErrorDeg).ToString("R", CultureInfo.InvariantCulture),
                }));
            }
        }

        /// <summary>
        /// 写出中文算法说明。
        /// </summary>
        private static void WriteNotes(SimulationResult result, string path)
        {
            using StreamWriter writer = new StreamWriter(path, append: false, Encoding.UTF8);
            writer.WriteLine("# Anchor Upsample Baseline Notes");
            writer.WriteLine();
            writer.WriteLine("输入观测只来自 primary variant 的 `aligned_raw_pos/aligned_raw_rot`，并按 `source_frame_id` 去重。`stable_pos/stable_rot`、`arrival_time_raw_*`、GT 和 head pose 都不作为算法输入。");
            writer.WriteLine();
            writer.WriteLine("模拟时钟优先使用 Unity 日志中逐帧记录的 `render_mono_ms`，因此 render 间隔保留真实的非均匀时间轴；只有合成数据或缺少录制时间时才使用 `--render-hz` 作为回退。每个 render 时刻只使用已经到达的低频观测，调用各 baseline 的 `Predict(renderTime)` 输出最新 pose。");
            writer.WriteLine();
            foreach (IPosePredictor algorithm in result.Algorithms)
            {
                writer.WriteLine($"## {algorithm.Label}");
                writer.WriteLine();
                writer.WriteLine(algorithm.Description);
                writer.WriteLine();
            }
        }
    }

    /// <summary>
    /// SVG 曲线写入器。
    /// </summary>
    private static class SvgChartWriter
    {
        /// <summary>
        /// 写出单个算法的四面板曲线。
        /// </summary>
        public static void WriteAlgorithmChart(SimulationResult result, string label, string path)
        {
            const int width = 3200;
            const int panelHeight = 320;
            const int left = 120;
            const int right = 70;
            const int top = 132;
            const int gap = 48;
            const int bottom = 84;
            int height = top + 4 * panelHeight + 3 * gap + bottom;
            double t0 = result.Rows.Count > 0 ? result.Rows[0].RenderMonoMs : 0.0;
            double t1 = result.Rows.Count > 0 ? result.Rows[result.Rows.Count - 1].RenderMonoMs : 1.0;
            Quaternion reference = result.Session.Observations.Count > 0 ? result.Session.Observations[0].Pose.rotation : Quaternion.identity;
            string[] names = { "x (m)", "y (m)", "z (m)", "rot angle (deg)" };
            int plotRight = width - right;

            using StreamWriter writer = new StreamWriter(path, append: false, Encoding.UTF8);
            writer.WriteLine($"<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{width}\" height=\"{height}\" viewBox=\"0 0 {width} {height}\">");
            writer.WriteLine("<rect width=\"100%\" height=\"100%\" fill=\"white\"/>");
            writer.WriteLine($"<text x=\"{left}\" y=\"42\" font-family=\"Segoe UI, Arial\" font-size=\"32\" font-weight=\"600\" fill=\"#111\">{Escape(label)} baseline render pose vs observations</text>");
            writer.WriteLine($"<text x=\"{left}\" y=\"78\" font-family=\"Segoe UI, Arial\" font-size=\"20\" fill=\"#555\">x-axis uses recorded render_mono_ms timeline, not fixed 60Hz. Red circles are discrete low-frequency observations; blue line is upsampled/render output.</text>");
            writer.WriteLine($"<line x1=\"{left}\" y1=\"106\" x2=\"{left + 72}\" y2=\"106\" stroke=\"#1565c0\" stroke-width=\"5\"/>");
            writer.WriteLine($"<text x=\"{left + 88}\" y=\"112\" font-family=\"Segoe UI, Arial\" font-size=\"22\" fill=\"#222\">render / upsampled pose</text>");
            writer.WriteLine($"<circle cx=\"{left + 430}\" cy=\"106\" r=\"8\" fill=\"#d32f2f\" opacity=\"0.95\"/>");
            writer.WriteLine($"<text x=\"{left + 452}\" y=\"112\" font-family=\"Segoe UI, Arial\" font-size=\"22\" fill=\"#222\">observed pose (low-frequency input)</text>");

            for (int panel = 0; panel < 4; panel++)
            {
                int yTop = top + panel * (panelHeight + gap);
                List<Point2> render = CollectRenderPoints(result, label, panel, reference, t0, t1, left, plotRight, yTop, panelHeight, out double min, out double max);
                List<Point2> obs = CollectObservationPoints(result.Session.Observations, panel, reference, t0, t1, left, plotRight, yTop, panelHeight, min, max);
                DrawGrid(writer, left, plotRight, yTop, panelHeight, t0, t1, panel == 3);
                writer.WriteLine($"<text x=\"20\" y=\"{yTop + 30}\" font-family=\"Segoe UI, Arial\" font-size=\"22\" font-weight=\"600\" fill=\"#333\">{Escape(names[panel])}</text>");
                writer.WriteLine($"<text x=\"{left + 10}\" y=\"{yTop + 24}\" font-family=\"Segoe UI, Arial\" font-size=\"17\" fill=\"#666\">{max.ToString("0.####", CultureInfo.InvariantCulture)}</text>");
                writer.WriteLine($"<text x=\"{left + 10}\" y=\"{yTop + panelHeight - 10}\" font-family=\"Segoe UI, Arial\" font-size=\"17\" fill=\"#666\">{min.ToString("0.####", CultureInfo.InvariantCulture)}</text>");
                writer.WriteLine($"<polyline fill=\"none\" stroke=\"#1565c0\" stroke-width=\"3.2\" stroke-linejoin=\"round\" stroke-linecap=\"round\" points=\"{Polyline(render)}\"/>");
                foreach (Point2 p in obs)
                {
                    writer.WriteLine($"<circle cx=\"{p.X.ToString("0.###", CultureInfo.InvariantCulture)}\" cy=\"{p.Y.ToString("0.###", CultureInfo.InvariantCulture)}\" r=\"6\" fill=\"#d32f2f\" stroke=\"white\" stroke-width=\"1.5\" opacity=\"0.95\"/>");
                }
            }

            writer.WriteLine($"<text x=\"{left}\" y=\"{height - 28}\" font-family=\"Segoe UI, Arial\" font-size=\"18\" fill=\"#555\">render rows: {result.Rows.Count.ToString(CultureInfo.InvariantCulture)}, observation frames: {result.Session.Observations.Count.ToString(CultureInfo.InvariantCulture)}. Observation dots are placed at first available render_mono_ms for each source_frame_id.</text>");
            writer.WriteLine("</svg>");
        }

        /// <summary>
        /// 绘制时间网格和横轴秒标。
        /// </summary>
        private static void DrawGrid(StreamWriter writer, int left, int right, int yTop, int panelHeight, double t0, double t1, bool drawLabels)
        {
            writer.WriteLine($"<rect x=\"{left}\" y=\"{yTop}\" width=\"{right - left}\" height=\"{panelHeight}\" fill=\"#fafafa\" stroke=\"#bdbdbd\" stroke-width=\"1.2\"/>");
            int tickCount = 12;
            for (int i = 0; i <= tickCount; i++)
            {
                double alpha = i / (double)tickCount;
                double x = left + alpha * (right - left);
                double tSeconds = ((t0 + alpha * (t1 - t0)) - t0) / 1000.0;
                string stroke = i == 0 || i == tickCount ? "#bdbdbd" : "#e0e0e0";
                writer.WriteLine($"<line x1=\"{x.ToString("0.###", CultureInfo.InvariantCulture)}\" y1=\"{yTop}\" x2=\"{x.ToString("0.###", CultureInfo.InvariantCulture)}\" y2=\"{yTop + panelHeight}\" stroke=\"{stroke}\" stroke-width=\"1\"/>");
                if (drawLabels)
                {
                    writer.WriteLine($"<text x=\"{(x - 20).ToString("0.###", CultureInfo.InvariantCulture)}\" y=\"{yTop + panelHeight + 30}\" font-family=\"Segoe UI, Arial\" font-size=\"18\" fill=\"#555\">{tSeconds.ToString("0.0", CultureInfo.InvariantCulture)}s</text>");
                }
            }

            for (int i = 1; i < 4; i++)
            {
                double y = yTop + i * panelHeight / 4.0;
                writer.WriteLine($"<line x1=\"{left}\" y1=\"{y.ToString("0.###", CultureInfo.InvariantCulture)}\" x2=\"{right}\" y2=\"{y.ToString("0.###", CultureInfo.InvariantCulture)}\" stroke=\"#eeeeee\" stroke-width=\"1\"/>");
            }
        }

        /// <summary>
        /// 收集 render 曲线点。
        /// </summary>
        private static List<Point2> CollectRenderPoints(SimulationResult result, string label, int component, Quaternion reference, double t0, double t1, int x0, int x1, int y0, int height, out double min, out double max)
        {
            List<double> values = new List<double>();
            foreach (RenderRow row in result.Rows)
            {
                VariantSample variant = FindVariant(row, label);
                if (variant.HasPose)
                {
                    values.Add(Component(variant.Pose, component, reference));
                }
            }

            Range(values, out min, out max);
            List<Point2> points = new List<Point2>();
            foreach (RenderRow row in result.Rows)
            {
                VariantSample variant = FindVariant(row, label);
                if (!variant.HasPose)
                {
                    continue;
                }

                double x = Scale(row.RenderMonoMs, t0, t1, x0, x1);
                double y = Scale(Component(variant.Pose, component, reference), min, max, y0 + height, y0);
                points.Add(new Point2(x, y));
            }

            return points;
        }

        /// <summary>
        /// 收集观测离散点。
        /// </summary>
        private static List<Point2> CollectObservationPoints(IReadOnlyList<ObservationSample> observations, int component, Quaternion reference, double t0, double t1, int x0, int x1, int y0, int height, double min, double max)
        {
            List<Point2> points = new List<Point2>();
            foreach (ObservationSample observation in observations)
            {
                double x = Scale(observation.AvailableMonoMs, t0, t1, x0, x1);
                double y = Scale(Component(observation.Pose, component, reference), min, max, y0 + height, y0);
                points.Add(new Point2(x, y));
            }

            return points;
        }

        /// <summary>
        /// 查找一行中的算法变体。
        /// </summary>
        private static VariantSample FindVariant(RenderRow row, string label)
        {
            foreach (VariantSample variant in row.Variants)
            {
                if (variant.Label == label)
                {
                    return variant;
                }
            }

            return VariantSample.None(label, "missing");
        }

        /// <summary>
        /// 读取曲线分量。
        /// </summary>
        private static double Component(in Pose pose, int component, Quaternion reference)
        {
            switch (component)
            {
                case 0:
                    return pose.position.x;
                case 1:
                    return pose.position.y;
                case 2:
                    return pose.position.z;
                default:
                    return AnchorMath.AngleDegrees(reference, pose.rotation);
            }
        }
    }

    /// <summary>
    /// 内置自测。
    /// </summary>
    private static class SelfTest
    {
        /// <summary>
        /// 运行合成数据行为测试。
        /// </summary>
        public static void Run()
        {
            List<ObservationSample> observations = new List<ObservationSample>
            {
                new ObservationSample(1, 0.0, 0.0, new Pose(new Vector3(0.0f, 0.0f, 0.0f), Quaternion.identity), 1.0f, "TRACK"),
                new ObservationSample(2, 200.0, 200.0, new Pose(new Vector3(0.20f, 0.02f, 0.0f), YawDegrees(4.0f)), 1.0f, "TRACK"),
                new ObservationSample(3, 400.0, 400.0, new Pose(new Vector3(0.42f, 0.03f, 0.0f), YawDegrees(8.0f)), 1.0f, "TRACK"),
            };
            List<double> renderTimesMs = new List<double>
            {
                0.0, 17.0, 33.0, 51.0, 68.0, 86.0, 104.0, 123.0, 145.0, 166.0,
                188.0, 209.0, 230.0, 251.0, 274.0, 297.0, 320.0, 344.0, 369.0, 395.0,
                422.0, 448.0, 475.0, 503.0, 532.0, 562.0, 593.0, 625.0, 650.0,
            };
            SessionData session = new SessionData("self_test", "synthetic", 0.0, 650.0, 0.0, observations, renderTimesMs);
            SimulationResult result = Simulator.Run(session, 60.0);
            Assert(result.Rows.Count == renderTimesMs.Count, "self-test should use the provided recorded render timeline.");
            for (int i = 0; i < renderTimesMs.Count; i++)
            {
                Assert(Math.Abs(result.Rows[i].RenderMonoMs - renderTimesMs[i]) < 1e-6, "render timeline should be preserved exactly.");
            }
            Assert(result.Algorithms.Count == 5, "self-test should include five baseline algorithms.");
            AssertRawHolds(result);
            AssertPredictorMoves(result, "kalman_prediction");
            AssertPredictorMoves(result, "dead_reckoning_spline");
            AssertPredictorMoves(result, "oneeuro_prediction");
            AssertResidualBlendPaysDownErrorGradually();
            foreach (RenderRow row in result.Rows)
            {
                foreach (VariantSample variant in row.Variants)
                {
                    if (variant.HasPose)
                    {
                        float norm = Mathf.Sqrt(
                            variant.Pose.rotation.x * variant.Pose.rotation.x
                            + variant.Pose.rotation.y * variant.Pose.rotation.y
                            + variant.Pose.rotation.z * variant.Pose.rotation.z
                            + variant.Pose.rotation.w * variant.Pose.rotation.w);
                        Assert(Math.Abs(norm - 1.0f) < 1e-3f, $"{variant.Label} quaternion should be normalized.");
                    }
                }
            }
        }

        /// <summary>
        /// 验证 raw_none 在观测之间保持不变。
        /// </summary>
        private static void AssertRawHolds(SimulationResult result)
        {
            VariantSample at220 = FindAt(result, "raw_none", 220.0);
            VariantSample at350 = FindAt(result, "raw_none", 350.0);
            Assert(Vector3.Distance(at220.Pose.position, at350.Pose.position) < 1e-6f, "raw_none should hold latest observation between samples.");
        }

        /// <summary>
        /// 验证预测算法在观测之间产生连续变化。
        /// </summary>
        private static void AssertPredictorMoves(SimulationResult result, string label)
        {
            VariantSample first = FindAt(result, label, 420.0);
            VariantSample second = FindAt(result, label, 520.0);
            Assert(first.HasPose && second.HasPose, $"{label} should output pose.");
            float motion = Vector3.Distance(first.Pose.position, second.Pose.position);
            Assert(motion > 1e-5f, $"{label} should move between observations.");
        }

        /// <summary>
        /// 验证历史残差淡化算法不会在新观测到达时一次性跳到测量点。
        /// </summary>
        private static void AssertResidualBlendPaysDownErrorGradually()
        {
            List<ObservationSample> observations = new List<ObservationSample>
            {
                new ObservationSample(1, 0.0, 0.0, new Pose(Vector3.zero, Quaternion.identity), 1.0f, "TRACK"),
                new ObservationSample(2, 200.0, 200.0, new Pose(new Vector3(1.0f, 0.0f, 0.0f), Quaternion.identity), 1.0f, "TRACK"),
            };
            List<double> renderTimesMs = new List<double>
            {
                0.0, 16.667, 33.333, 50.0, 66.667, 83.333, 100.0, 116.667, 133.333, 150.0,
                166.667, 183.333, 200.0, 216.667, 233.333, 250.0,
            };
            SessionData session = new SessionData("self_test", "synthetic_residual", 0.0, 250.0, 0.0, observations, renderTimesMs);
            SimulationResult result = Simulator.Run(session, 60.0);
            VariantSample before = FindAt(result, "residual_blend_prediction", 183.333);
            VariantSample atArrival = FindAt(result, "residual_blend_prediction", 200.0);
            VariantSample after = FindAt(result, "residual_blend_prediction", 216.667);
            Assert(before.HasPose && atArrival.HasPose && after.HasPose, "residual_blend_prediction should output pose.");
            float arrivalStep = Mathf.Abs(atArrival.Pose.position.x - before.Pose.position.x);
            Assert(arrivalStep > 0.02f && arrivalStep < 0.20f, "residual_blend_prediction should pay only a small part of the historical residual at arrival.");
            Assert(after.Pose.position.x > atArrival.Pose.position.x, "residual_blend_prediction should keep paying down residual over later render frames.");
        }

        /// <summary>
        /// 查找指定时间附近的变体。
        /// </summary>
        private static VariantSample FindAt(SimulationResult result, string label, double renderMs)
        {
            RenderRow best = result.Rows[0];
            double bestDelta = Math.Abs(best.RenderMonoMs - renderMs);
            foreach (RenderRow row in result.Rows)
            {
                double delta = Math.Abs(row.RenderMonoMs - renderMs);
                if (delta < bestDelta)
                {
                    best = row;
                    bestDelta = delta;
                }
            }

            foreach (VariantSample variant in best.Variants)
            {
                if (variant.Label == label)
                {
                    return variant;
                }
            }

            throw new InvalidOperationException($"Missing variant {label}");
        }

        /// <summary>
        /// 构造绕 Y 轴旋转。
        /// </summary>
        private static Quaternion YawDegrees(float degrees)
        {
            float radians = degrees * Mathf.Deg2Rad;
            return new Quaternion(0.0f, Mathf.Sin(radians * 0.5f), 0.0f, Mathf.Cos(radians * 0.5f));
        }

        /// <summary>
        /// 自测断言。
        /// </summary>
        private static void Assert(bool condition, string message)
        {
            if (!condition)
            {
                throw new InvalidOperationException(message);
            }
        }
    }

    /// <summary>
    /// 会话数据。
    /// </summary>
    private sealed class SessionData
    {
        /// <summary>输入 session 目录。</summary>
        public readonly string SessionDir;

        /// <summary>输入 unity_output 路径。</summary>
        public readonly string OutputLogPath;

        /// <summary>第一行 render 单调时间，单位毫秒。</summary>
        public readonly double FirstRenderMonoMs;

        /// <summary>最后一行 render 单调时间，单位毫秒。</summary>
        public readonly double LastRenderMonoMs;

        /// <summary>Unix 毫秒与单调毫秒的偏移。</summary>
        public readonly double UnixOffsetMs;

        /// <summary>低频观测列表。</summary>
        public readonly List<ObservationSample> Observations;

        /// <summary>录制的 render 单调时间列表，单位毫秒。</summary>
        public readonly List<double> RenderMonoTimesMs;

        /// <summary>
        /// 构造会话数据。
        /// </summary>
        public SessionData(string sessionDir, string outputLogPath, double firstRenderMonoMs, double lastRenderMonoMs, double unixOffsetMs, List<ObservationSample> observations, List<double> renderMonoTimesMs)
        {
            SessionDir = sessionDir;
            OutputLogPath = outputLogPath;
            FirstRenderMonoMs = firstRenderMonoMs;
            LastRenderMonoMs = lastRenderMonoMs;
            UnixOffsetMs = unixOffsetMs;
            Observations = observations;
            RenderMonoTimesMs = renderMonoTimesMs;
        }
    }

    /// <summary>
    /// 一帧低频观测。
    /// </summary>
    private readonly struct ObservationSample
    {
        /// <summary>源 frame_id。</summary>
        public readonly long FrameId;

        /// <summary>采集单调时间，单位毫秒。</summary>
        public readonly double CaptureMonoMs;

        /// <summary>观测在 Unity 输出日志中首次可见的单调时间，单位毫秒。</summary>
        public readonly double AvailableMonoMs;

        /// <summary>frame-aligned raw world pose。</summary>
        public readonly Pose Pose;

        /// <summary>Python 可靠性分数。</summary>
        public readonly float ReliabilityScore;

        /// <summary>Python phase。</summary>
        public readonly string Phase;

        /// <summary>采集单调时间，单位秒。</summary>
        public double CaptureSeconds => CaptureMonoMs / 1000.0;

        /// <summary>可见单调时间，单位秒。</summary>
        public double AvailableSeconds => AvailableMonoMs / 1000.0;

        /// <summary>
        /// 构造低频观测。
        /// </summary>
        public ObservationSample(long frameId, double captureMonoMs, double availableMonoMs, Pose pose, float reliabilityScore, string phase)
        {
            FrameId = frameId;
            CaptureMonoMs = captureMonoMs;
            AvailableMonoMs = availableMonoMs;
            Pose = new Pose(pose.position, AnchorMath.Normalize(pose.rotation));
            ReliabilityScore = Mathf.Clamp01(reliabilityScore);
            Phase = phase ?? string.Empty;
        }
    }

    /// <summary>
    /// 单个算法的 render 输出。
    /// </summary>
    private readonly struct VariantSample
    {
        /// <summary>算法标签。</summary>
        public readonly string Label;

        /// <summary>是否有可输出 pose。</summary>
        public readonly bool HasPose;

        /// <summary>当前输出对应的最近 source frame。</summary>
        public readonly long SourceFrameId;

        /// <summary>预测 pose。</summary>
        public readonly Pose Pose;

        /// <summary>预测前推时长，单位毫秒。</summary>
        public readonly double PredictAheadMs;

        /// <summary>最近观测可靠性分数。</summary>
        public readonly float LatestScore;

        /// <summary>输出原因。</summary>
        public readonly string Reason;

        /// <summary>
        /// 构造 render 输出。
        /// </summary>
        public VariantSample(string label, bool hasPose, long sourceFrameId, Pose pose, double predictAheadMs, float latestScore, string reason)
        {
            Label = label ?? string.Empty;
            HasPose = hasPose;
            SourceFrameId = sourceFrameId;
            Pose = new Pose(pose.position, AnchorMath.Normalize(pose.rotation));
            PredictAheadMs = predictAheadMs;
            LatestScore = latestScore;
            Reason = reason ?? string.Empty;
        }

        /// <summary>
        /// 构造无 pose 输出。
        /// </summary>
        public static VariantSample None(string label, string reason)
        {
            return new VariantSample(label, false, -1, Pose.identity, double.NaN, float.NaN, reason);
        }
    }

    /// <summary>
    /// 单个 render tick 输出。
    /// </summary>
    private readonly struct RenderRow
    {
        /// <summary>渲染单调时间，单位毫秒。</summary>
        public readonly double RenderMonoMs;

        /// <summary>渲染 Unix 时间，单位毫秒。</summary>
        public readonly double RenderUnixMs;

        /// <summary>模拟 render 序号。</summary>
        public readonly int RenderIndex;

        /// <summary>是否已有低频观测。</summary>
        public readonly bool HasObservation;

        /// <summary>最近低频观测。</summary>
        public readonly ObservationSample Observation;

        /// <summary>各算法输出。</summary>
        public readonly List<VariantSample> Variants;

        /// <summary>
        /// 构造 render 行。
        /// </summary>
        public RenderRow(double renderMonoMs, double renderUnixMs, int renderIndex, bool hasObservation, ObservationSample observation, List<VariantSample> variants)
        {
            RenderMonoMs = renderMonoMs;
            RenderUnixMs = renderUnixMs;
            RenderIndex = renderIndex;
            HasObservation = hasObservation;
            Observation = observation;
            Variants = variants;
        }
    }

    /// <summary>
    /// 完整模拟结果。
    /// </summary>
    private sealed class SimulationResult
    {
        /// <summary>输入会话。</summary>
        public readonly SessionData Session;

        /// <summary>算法列表。</summary>
        public readonly List<IPosePredictor> Algorithms;

        /// <summary>逐 render tick 输出。</summary>
        public readonly List<RenderRow> Rows;

        /// <summary>
        /// 构造完整模拟结果。
        /// </summary>
        public SimulationResult(SessionData session, List<IPosePredictor> algorithms, List<RenderRow> rows)
        {
            Session = session;
            Algorithms = algorithms;
            Rows = rows;
        }
    }

    /// <summary>
    /// 指标统计。
    /// </summary>
    private sealed class Metrics
    {
        /// <summary>render 输出行数。</summary>
        public int RenderRows;

        /// <summary>观测年龄，单位毫秒。</summary>
        public readonly List<double> ObservationAgeMs = new List<double>();

        /// <summary>相邻 render 平移步长，单位毫米。</summary>
        public readonly List<double> StepPositionMm = new List<double>();

        /// <summary>相邻 render 旋转步长，单位度。</summary>
        public readonly List<double> StepRotationDeg = new List<double>();

        /// <summary>观测到达瞬间输出与观测的平移误差，单位毫米。</summary>
        public readonly List<double> ObservationInstantErrorMm = new List<double>();

        /// <summary>观测到达瞬间输出与观测的旋转误差，单位度。</summary>
        public readonly List<double> ObservationInstantRotationErrorDeg = new List<double>();

        /// <summary>
        /// 计算所有算法指标。
        /// </summary>
        public static Dictionary<string, Metrics> Compute(SimulationResult result)
        {
            Dictionary<string, Metrics> metrics = new Dictionary<string, Metrics>(StringComparer.Ordinal);
            Dictionary<string, VariantSample> previous = new Dictionary<string, VariantSample>(StringComparer.Ordinal);
            foreach (IPosePredictor algorithm in result.Algorithms)
            {
                metrics[algorithm.Label] = new Metrics();
            }

            HashSet<long> countedObservationFrames = new HashSet<long>();
            foreach (RenderRow row in result.Rows)
            {
                foreach (VariantSample variant in row.Variants)
                {
                    Metrics m = metrics[variant.Label];
                    m.RenderRows++;
                    if (row.HasObservation)
                    {
                        m.ObservationAgeMs.Add(row.RenderMonoMs - row.Observation.CaptureMonoMs);
                    }

                    if (variant.HasPose && previous.TryGetValue(variant.Label, out VariantSample prev) && prev.HasPose)
                    {
                        m.StepPositionMm.Add(Vector3.Distance(prev.Pose.position, variant.Pose.position) * 1000.0);
                        m.StepRotationDeg.Add(AnchorMath.AngleDegrees(prev.Pose.rotation, variant.Pose.rotation));
                    }

                    if (variant.HasPose)
                    {
                        previous[variant.Label] = variant;
                    }

                    if (row.HasObservation
                        && row.Observation.FrameId == variant.SourceFrameId
                        && countedObservationFrames.Add(row.Observation.FrameId * 17 + variant.Label.GetHashCode()))
                    {
                        m.ObservationInstantErrorMm.Add(Vector3.Distance(row.Observation.Pose.position, variant.Pose.position) * 1000.0);
                        m.ObservationInstantRotationErrorDeg.Add(AnchorMath.AngleDegrees(row.Observation.Pose.rotation, variant.Pose.rotation));
                    }
                }
            }

            return metrics;
        }
    }

    /// <summary>
    /// 二维绘图点。
    /// </summary>
    private readonly struct Point2
    {
        /// <summary>X 坐标。</summary>
        public readonly double X;

        /// <summary>Y 坐标。</summary>
        public readonly double Y;

        /// <summary>
        /// 构造二维点。
        /// </summary>
        public Point2(double x, double y)
        {
            X = x;
            Y = y;
        }
    }

    /// <summary>
    /// 读取 pose。
    /// </summary>
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

    /// <summary>
    /// 读取 Vector3 数组。
    /// </summary>
    private static Vector3 ReadVector3(JsonElement value)
    {
        return new Vector3((float)value[0].GetDouble(), (float)value[1].GetDouble(), (float)value[2].GetDouble());
    }

    /// <summary>
    /// 读取 Quaternion 数组。
    /// </summary>
    private static Quaternion ReadQuaternion(JsonElement value)
    {
        return AnchorMath.Normalize(new Quaternion((float)value[0].GetDouble(), (float)value[1].GetDouble(), (float)value[2].GetDouble(), (float)value[3].GetDouble()));
    }

    /// <summary>
    /// 读取 double 字段。
    /// </summary>
    private static double ReadDouble(JsonElement row, string name, double defaultValue)
    {
        return row.TryGetProperty(name, out JsonElement value) && value.ValueKind == JsonValueKind.Number ? value.GetDouble() : defaultValue;
    }

    /// <summary>
    /// 读取 float 字段。
    /// </summary>
    private static float ReadFloat(JsonElement row, string name, float defaultValue)
    {
        return row.TryGetProperty(name, out JsonElement value) && value.ValueKind == JsonValueKind.Number ? value.GetSingle() : defaultValue;
    }

    /// <summary>
    /// 读取 long 字段。
    /// </summary>
    private static long ReadLong(JsonElement row, string name, long defaultValue)
    {
        return row.TryGetProperty(name, out JsonElement value) && value.ValueKind == JsonValueKind.Number ? value.GetInt64() : defaultValue;
    }

    /// <summary>
    /// 读取 bool 字段。
    /// </summary>
    private static bool ReadBool(JsonElement row, string name, bool defaultValue)
    {
        return row.TryGetProperty(name, out JsonElement value) && (value.ValueKind == JsonValueKind.True || value.ValueKind == JsonValueKind.False) ? value.GetBoolean() : defaultValue;
    }

    /// <summary>
    /// 读取 string 字段。
    /// </summary>
    private static string ReadString(JsonElement row, string name, string defaultValue)
    {
        return row.TryGetProperty(name, out JsonElement value) && value.ValueKind == JsonValueKind.String ? value.GetString() ?? defaultValue : defaultValue;
    }

    /// <summary>
    /// 写入 JSON 字段名。
    /// </summary>
    private static void AppendName(StringBuilder builder, ref bool first, string name)
    {
        if (!first)
        {
            builder.Append(',');
        }

        first = false;
        AppendEscaped(builder, name);
        builder.Append(':');
    }

    /// <summary>
    /// 写入 JSON 字符串属性。
    /// </summary>
    private static void AppendString(StringBuilder builder, ref bool first, string name, string value)
    {
        AppendName(builder, ref first, name);
        AppendEscaped(builder, value ?? string.Empty);
    }

    /// <summary>
    /// 写入 JSON bool 属性。
    /// </summary>
    private static void AppendBool(StringBuilder builder, ref bool first, string name, bool value)
    {
        AppendName(builder, ref first, name);
        builder.Append(value ? "true" : "false");
    }

    /// <summary>
    /// 写入 JSON long 属性。
    /// </summary>
    private static void AppendLong(StringBuilder builder, ref bool first, string name, long value)
    {
        AppendName(builder, ref first, name);
        builder.Append(value.ToString(CultureInfo.InvariantCulture));
    }

    /// <summary>
    /// 写入 JSON double 属性。
    /// </summary>
    private static void AppendDouble(StringBuilder builder, ref bool first, string name, double value)
    {
        AppendName(builder, ref first, name);
        AppendNumber(builder, value);
    }

    /// <summary>
    /// 写入 JSON float 属性。
    /// </summary>
    private static void AppendFloat(StringBuilder builder, ref bool first, string name, float value)
    {
        AppendName(builder, ref first, name);
        AppendNumber(builder, value);
    }

    /// <summary>
    /// 写入 pose 属性。
    /// </summary>
    private static void AppendPose(StringBuilder builder, ref bool first, string posName, string rotName, Pose pose, bool hasPose)
    {
        AppendName(builder, ref first, posName);
        if (hasPose)
        {
            AppendVector3(builder, pose.position);
        }
        else
        {
            builder.Append("null");
        }

        AppendName(builder, ref first, rotName);
        if (hasPose)
        {
            AppendQuaternion(builder, pose.rotation);
        }
        else
        {
            builder.Append("null");
        }

        AppendName(builder, ref first, "euler_deg");
        if (hasPose)
        {
            AppendVector3(builder, ToEuler360(pose.rotation));
        }
        else
        {
            builder.Append("null");
        }
    }

    /// <summary>
    /// 写入 Vector3 数组。
    /// </summary>
    private static void AppendVector3(StringBuilder builder, Vector3 value)
    {
        builder.Append('[');
        AppendNumber(builder, value.x);
        builder.Append(',');
        AppendNumber(builder, value.y);
        builder.Append(',');
        AppendNumber(builder, value.z);
        builder.Append(']');
    }

    /// <summary>
    /// 写入 Quaternion 数组。
    /// </summary>
    private static void AppendQuaternion(StringBuilder builder, Quaternion value)
    {
        builder.Append('[');
        AppendNumber(builder, value.x);
        builder.Append(',');
        AppendNumber(builder, value.y);
        builder.Append(',');
        AppendNumber(builder, value.z);
        builder.Append(',');
        AppendNumber(builder, value.w);
        builder.Append(']');
    }

    /// <summary>
    /// 写入 JSON 数值。
    /// </summary>
    private static void AppendNumber(StringBuilder builder, double value)
    {
        if (double.IsNaN(value) || double.IsInfinity(value))
        {
            builder.Append("null");
            return;
        }

        builder.Append(value.ToString("R", CultureInfo.InvariantCulture));
    }

    /// <summary>
    /// 写入 JSON 数值。
    /// </summary>
    private static void AppendNumber(StringBuilder builder, float value)
    {
        if (float.IsNaN(value) || float.IsInfinity(value))
        {
            builder.Append("null");
            return;
        }

        builder.Append(value.ToString("R", CultureInfo.InvariantCulture));
    }

    /// <summary>
    /// 写入转义字符串。
    /// </summary>
    private static void AppendEscaped(StringBuilder builder, string value)
    {
        builder.Append('"');
        if (!string.IsNullOrEmpty(value))
        {
            foreach (char c in value)
            {
                switch (c)
                {
                    case '\\':
                        builder.Append("\\\\");
                        break;
                    case '"':
                        builder.Append("\\\"");
                        break;
                    case '\n':
                        builder.Append("\\n");
                        break;
                    case '\r':
                        builder.Append("\\r");
                        break;
                    case '\t':
                        builder.Append("\\t");
                        break;
                    default:
                        builder.Append(c);
                        break;
                }
            }
        }

        builder.Append('"');
    }

    /// <summary>
    /// 把四元数转换为 0..360 欧拉角。
    /// </summary>
    private static Vector3 ToEuler360(Quaternion value)
    {
        Quaternion q = AnchorMath.Normalize(value);
        double x = q.x;
        double y = q.y;
        double z = q.z;
        double w = q.w;
        double sinX = 2.0 * (w * x + y * z);
        double cosX = 1.0 - 2.0 * (x * x + y * y);
        double eulerX = Math.Atan2(sinX, cosX) * Mathf.Rad2Deg;
        double sinY = 2.0 * (w * y - z * x);
        sinY = Math.Max(-1.0, Math.Min(1.0, sinY));
        double eulerY = Math.Asin(sinY) * Mathf.Rad2Deg;
        double sinZ = 2.0 * (w * z + x * y);
        double cosZ = 1.0 - 2.0 * (y * y + z * z);
        double eulerZ = Math.Atan2(sinZ, cosZ) * Mathf.Rad2Deg;
        return new Vector3(NormalizeAngle((float)eulerX), NormalizeAngle((float)eulerY), NormalizeAngle((float)eulerZ));
    }

    /// <summary>
    /// 规范角度到 0..360。
    /// </summary>
    private static float NormalizeAngle(float value)
    {
        float normalized = value % 360.0f;
        return normalized < 0.0f ? normalized + 360.0f : normalized;
    }

    /// <summary>
    /// 均值。
    /// </summary>
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

    /// <summary>
    /// 均方根。
    /// </summary>
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

    /// <summary>
    /// 最大值。
    /// </summary>
    private static double Max(List<double> values)
    {
        if (values.Count == 0)
        {
            return double.NaN;
        }

        double result = values[0];
        foreach (double value in values)
        {
            result = Math.Max(result, value);
        }

        return result;
    }

    /// <summary>
    /// 计算范围。
    /// </summary>
    private static void Range(List<double> values, out double min, out double max)
    {
        if (values.Count == 0)
        {
            min = 0.0;
            max = 1.0;
            return;
        }

        min = values[0];
        max = values[0];
        foreach (double value in values)
        {
            min = Math.Min(min, value);
            max = Math.Max(max, value);
        }

        if (Math.Abs(max - min) < 1e-9)
        {
            min -= 0.5;
            max += 0.5;
        }
        else
        {
            double pad = (max - min) * 0.08;
            min -= pad;
            max += pad;
        }
    }

    /// <summary>
    /// 数值线性映射。
    /// </summary>
    private static double Scale(double value, double srcMin, double srcMax, double dstMin, double dstMax)
    {
        if (Math.Abs(srcMax - srcMin) < 1e-12)
        {
            return (dstMin + dstMax) * 0.5;
        }

        return dstMin + (value - srcMin) / (srcMax - srcMin) * (dstMax - dstMin);
    }

    /// <summary>
    /// SVG polyline 点串。
    /// </summary>
    private static string Polyline(List<Point2> points)
    {
        StringBuilder builder = new StringBuilder(points.Count * 16);
        for (int i = 0; i < points.Count; i++)
        {
            if (i > 0)
            {
                builder.Append(' ');
            }

            builder.Append(points[i].X.ToString("0.###", CultureInfo.InvariantCulture));
            builder.Append(',');
            builder.Append(points[i].Y.ToString("0.###", CultureInfo.InvariantCulture));
        }

        return builder.ToString();
    }

    /// <summary>
    /// XML 转义。
    /// </summary>
    private static string Escape(string value)
    {
        return (value ?? string.Empty)
            .Replace("&", "&amp;", StringComparison.Ordinal)
            .Replace("<", "&lt;", StringComparison.Ordinal)
            .Replace(">", "&gt;", StringComparison.Ordinal)
            .Replace("\"", "&quot;", StringComparison.Ordinal);
    }
}

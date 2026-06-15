using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using EgoAnchor.Tools3.Core;
using EgoAnchor.Tools3.Data;
using EgoAnchor.Tools3.Eval;
using EgoAnchor.Tools3.Predictors;
using EgoAnchor.Tools3.Predictors.Interp;
using EgoAnchor.Tools3.Predictors.Motion;
using EgoAnchor.Tools3.Sim;
using EgoAnchor.Tools3.Viz;

namespace EgoAnchor.Tools3
{
    /// <summary>
    /// EgoAnchor_Tools3 离线实时升采样仿真入口。
    ///
    /// 流程:
    ///   1. 从 session 的 *_unity_output.jsonl 提取真实 ~5fps 观测 pose 序列;
    ///   2. 对每个算法, 用 RealtimeSimulator 模拟实时运行 (观测按真实时间喂入,
    ///      渲染时钟 60fps, 每帧实时外推) -> 得到 ~60fps render 轨迹;
    ///   3. 导出每个算法的 JSONL (观测点 + render 点) 和对比 PNG 曲线图;
    ///   4. 打印平滑度小结 (相邻 render 帧的位置/旋转步长 RMS, 越小越平滑)。
    ///
    /// 用法:
    ///   dotnet run -- --session &lt;session_dir&gt; [--out &lt;output_dir&gt;] [--render-hz 60]
    /// </summary>
    internal static class Program
    {
        private static int Main(string[] args)
        {
            try
            {
                Options opt = Options.Parse(args);
                Directory.CreateDirectory(opt.OutputDir);

                List<Observation> observations = ObservationLoader.Load(opt.SessionDir);
                if (observations.Count == 0)
                {
                    throw new InvalidOperationException("没有提取到观测 pose (aligned_raw)。");
                }

                double timeZero = observations[0].TimeSeconds;
                double durationSec = observations[^1].TimeSeconds - timeZero;
                double obsHz = observations.Count / Math.Max(durationSec, 1e-6);
                Console.WriteLine($"session: {opt.SessionDir}");
                Console.WriteLine($"观测帧数: {observations.Count}, 时长: {durationSec:F1}s, 实际观测频率: {obsHz:F2}fps");
                Console.WriteLine($"渲染频率: {opt.RenderHz:F0}fps, 输出目录: {opt.OutputDir}");
                Console.WriteLine();

                // 参照基线
                var references = new List<IPredictor>
                {
                    new RawZohPredictor(),                  // 闪现/阶梯反例 (相当于 A 行)
                    new DeadReckoningSplinePredictor(),     // 零延迟样条参照
                };

                // B 行: 高频外推 + 误差融合 (零延迟)。decayPerFrame 见 --decay。
                var rowB = new List<IPredictor>
                {
                    new ResidualBlendingPredictor(new ConstVelocityMotionModel(), opt.DecayPerFrame), // cv_blend
                    new ResidualBlendingPredictor(new OneEuroMotionModel(), opt.DecayPerFrame),       // oneeuro_blend
                    new ResidualBlendingPredictor(new KalmanMotionModel(), opt.DecayPerFrame),        // kalman_blend
                };

                // C 行: 延迟一周期 + 插值。逐列与 B 行配对 (DR↔raw, 1€↔oneeuro, Kalman↔kalman)。
                var rowC = new List<IPredictor>
                {
                    new DelayedInterpolationPredictor(new RawControlPoints(), SplineKind.Hermite),               // raw_hermite
                    new DelayedInterpolationPredictor(new OneEuroControlPoints(), SplineKind.CentripetalCatmullRom), // oneeuro_interp
                    new DelayedInterpolationPredictor(new KalmanControlPoints(), SplineKind.Hermite),            // kalman_hermite
                };

                var predictors = new List<IPredictor>();
                predictors.AddRange(references);
                predictors.AddRange(rowB);
                predictors.AddRange(rowC);

                var simulator = new RealtimeSimulator(opt.RenderHz);
                var results = new List<SimResult>();
                var resultByLabel = new Dictionary<string, SimResult>();
                var allMetrics = new List<AlgorithmMetrics>();

                Console.WriteLine($"{"algorithm",-22} {"render",7} {"stepRMS(mm)",12} {"lag(ms)",9} {"alignRMS(mm)",13} {"throughRMS(mm)",15}");
                Console.WriteLine(new string('-', 82));

                foreach (IPredictor predictor in predictors)
                {
                    SimResult result = simulator.Run(predictor, observations);
                    results.Add(result);
                    resultByLabel[result.Label] = result;

                    AlgorithmMetrics m = MetricsCalculator.Compute(result, observations);
                    allMetrics.Add(m);
                    Console.WriteLine($"{m.Label,-22} {result.RenderSamples.Count,7} {m.StepPosRmsMm,12:F3} {m.LagMs,9:F0} {m.AlignedPosRmsMm,13:F2} {m.ThroughPosRmsMm,15:F2}");

                    WriteRenderJsonl(Path.Combine(opt.OutputDir, $"render_{result.Label}.jsonl"), result, observations, timeZero);

                    string singlePng = Path.Combine(opt.OutputDir, $"plot_{result.Label}.png");
                    TrajectoryPlotter.PlotSingle(result, observations, timeZero, singlePng);
                    if (opt.Zoom is { } zw)
                    {
                        TrajectoryPlotter.PlotSingle(result, observations, timeZero, Path.Combine(opt.OutputDir, $"plot_{result.Label}_zoom.png"), zw);
                    }
                }

                Console.WriteLine();
                Console.WriteLine("提示: stepRMS=平滑度(越小越平滑,但奖励滞后); lag=互相关估计的实际滞后;");
                Console.WriteLine("      alignRMS=按滞后对齐后准确度; throughRMS=不对齐的过点误差(C行插值应≈0)。");
                Console.WriteLine();

                // 全部算法对比图 (总览)
                string comparisonPng = Path.Combine(opt.OutputDir, "plot_comparison.png");
                TrajectoryPlotter.PlotComparison(results, observations, timeZero, comparisonPng);
                if (opt.Zoom is { } zoomAll)
                {
                    TrajectoryPlotter.PlotComparison(results, observations, timeZero, Path.Combine(opt.OutputDir, "plot_comparison_zoom.png"), zoomAll);
                }

                // 逐列 B↔C 配对对比图 (核心: 同一运动状态来源下, 补偿 vs 延迟插值)
                var pairs = new (string name, string b, string c)[]
                {
                    ("pair_dr", "cv_blend", "raw_hermite"),
                    ("pair_oneeuro", "oneeuro_blend", "oneeuro_interp"),
                    ("pair_kalman", "kalman_blend", "kalman_hermite"),
                };

                foreach (var (name, bLabel, cLabel) in pairs)
                {
                    if (!resultByLabel.TryGetValue(bLabel, out SimResult? bRes) || !resultByLabel.TryGetValue(cLabel, out SimResult? cRes))
                    {
                        continue;
                    }

                    var pairResults = new List<SimResult> { resultByLabel["raw_zoh"], bRes, cRes };
                    TrajectoryPlotter.PlotComparison(pairResults, observations, timeZero, Path.Combine(opt.OutputDir, $"plot_{name}.png"));
                    if (opt.Zoom is { } zoomPair)
                    {
                        TrajectoryPlotter.PlotComparison(pairResults, observations, timeZero, Path.Combine(opt.OutputDir, $"plot_{name}_zoom.png"), zoomPair);
                    }
                }

                // 平滑度 vs 滞后 散点 (拍板总图)
                TrajectoryPlotter.PlotSmoothnessVsLag(allMetrics, Path.Combine(opt.OutputDir, "plot_smoothness_vs_lag.png"));

                // 观测点单独导出
                WriteObservationsJsonl(Path.Combine(opt.OutputDir, "observations.jsonl"), observations, timeZero);

                Console.WriteLine("已输出:");
                Console.WriteLine($"  总对比图: {comparisonPng}");
                Console.WriteLine($"  配对图: plot_pair_dr / plot_pair_oneeuro / plot_pair_kalman (.png + _zoom.png)");
                Console.WriteLine($"  拍板散点: plot_smoothness_vs_lag.png");
                if (opt.Zoom is { } z)
                {
                    Console.WriteLine($"  zoom 窗口: [{z.start:F1}, {z.end:F1}]s");
                }

                Console.WriteLine($"  单算法图 + render_*.jsonl + observations.jsonl 见 {opt.OutputDir}");
                Console.WriteLine($"  单算法图 + 各算法 render_*.jsonl + observations.jsonl 见 {opt.OutputDir}");
                return 0;
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine("错误: " + ex.Message);
                Console.Error.WriteLine(ex.StackTrace);
                return 1;
            }
        }

        private static void WriteRenderJsonl(string path, SimResult result, IReadOnlyList<Observation> observations, double timeZero)
        {
            using var w = new StreamWriter(path, append: false);
            // 头行: 元信息
            w.WriteLine(JsonSerializer.Serialize(new
            {
                kind = "meta",
                label = result.Label,
                render_count = result.RenderSamples.Count,
                obs_count = observations.Count,
                time_zero_mono_s = timeZero,
            }));

            foreach (RenderSample s in result.RenderSamples)
            {
                var (rvx, rvy, rvz) = Rotation.ToRotationVectorDegrees(s.Pose.Rotation);
                w.WriteLine(JsonSerializer.Serialize(new
                {
                    kind = "render",
                    t = Round(s.TimeSeconds - timeZero),
                    pos = new[] { Round(s.Pose.Position.X), Round(s.Pose.Position.Y), Round(s.Pose.Position.Z) },
                    rot = new[] { Round(s.Pose.Rotation.X), Round(s.Pose.Rotation.Y), Round(s.Pose.Rotation.Z), Round(s.Pose.Rotation.W) },
                    rotvec_deg = new[] { Round(rvx), Round(rvy), Round(rvz) },
                    last_obs_dt = Round(s.TimeSeconds - s.LastObservationTimeSeconds),
                }));
            }
        }

        private static void WriteObservationsJsonl(string path, IReadOnlyList<Observation> observations, double timeZero)
        {
            using var w = new StreamWriter(path, append: false);
            foreach (Observation o in observations)
            {
                var (rvx, rvy, rvz) = Rotation.ToRotationVectorDegrees(o.Pose.Rotation);
                w.WriteLine(JsonSerializer.Serialize(new
                {
                    kind = "observation",
                    source_frame_id = o.SourceFrameId,
                    t = Round(o.TimeSeconds - timeZero),
                    pos = new[] { Round(o.Pose.Position.X), Round(o.Pose.Position.Y), Round(o.Pose.Position.Z) },
                    rot = new[] { Round(o.Pose.Rotation.X), Round(o.Pose.Rotation.Y), Round(o.Pose.Rotation.Z), Round(o.Pose.Rotation.W) },
                    rotvec_deg = new[] { Round(rvx), Round(rvy), Round(rvz) },
                    score = Round(o.Score),
                }));
            }
        }

        private static double Round(double v) => Math.Round(v, 6);

        private sealed class Options
        {
            public string SessionDir { get; private set; } = "";
            public string OutputDir { get; private set; } = "";
            public double RenderHz { get; private set; } = 60.0;
            public double DecayPerFrame { get; private set; } = 0.9;
            public (double start, double end)? Zoom { get; private set; }

            public static Options Parse(string[] args)
            {
                string session = "", output = "";
                double hz = 60.0;
                double decay = 0.9;
                double? zoomStart = null, zoomEnd = null;
                for (int i = 0; i < args.Length; i++)
                {
                    switch (args[i])
                    {
                        case "--session" when i + 1 < args.Length:
                            session = args[++i];
                            break;
                        case "--out" when i + 1 < args.Length:
                            output = args[++i];
                            break;
                        case "--render-hz" when i + 1 < args.Length:
                            hz = double.Parse(args[++i], CultureInfo.InvariantCulture);
                            break;
                        case "--decay" when i + 1 < args.Length:
                            decay = double.Parse(args[++i], CultureInfo.InvariantCulture);
                            break;
                        case "--zoom-start" when i + 1 < args.Length:
                            zoomStart = double.Parse(args[++i], CultureInfo.InvariantCulture);
                            break;
                        case "--zoom-end" when i + 1 < args.Length:
                            zoomEnd = double.Parse(args[++i], CultureInfo.InvariantCulture);
                            break;
                    }
                }

                if (string.IsNullOrWhiteSpace(session))
                {
                    throw new ArgumentException("用法: --session <session_dir> [--out <output_dir>] [--render-hz 60] [--decay 0.9] [--zoom-start <s> --zoom-end <s>]");
                }

                if (string.IsNullOrWhiteSpace(output))
                {
                    output = Path.Combine(session, "tools3_upsample_sim");
                }

                (double, double)? zoom = null;
                if (zoomStart.HasValue && zoomEnd.HasValue)
                {
                    zoom = (zoomStart.Value, zoomEnd.Value);
                }

                return new Options { SessionDir = session, OutputDir = output, RenderHz = hz, DecayPerFrame = decay, Zoom = zoom };
            }
        }
    }
}

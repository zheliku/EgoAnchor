using System;
using System.Collections.Generic;
using System.IO;
using EgoAnchor.Tools2.Data;
using EgoAnchor.Tools2.Plot;
using EgoAnchor.Tools2.Predictors;
using EgoAnchor.Tools2.Sim;

namespace EgoAnchor.Tools2
{
    /// <summary>
    /// 离线 anchor policy 仿真程序入口。
    ///
    /// 用法:
    ///   dotnet run --project EgoAnchor_Tools2\AnchorPolicySim.csproj -- --session EgoAnchor_Python\data\eval\20260614_130324_controller_right
    ///   dotnet run -- --diag --session <session>   # 仅输出统计诊断,不画图
    ///
    /// 流程:
    /// 1. 加载 session 的 unity_output.jsonl,提取 5fps 观测序列和 60fps render 时间轴。
    /// 2. 对每个算法用同一份输入流式仿真 (5fps 观测提交 -> 60fps 预测输出)。
    /// 3. 输出每个算法单独曲线图 + 总对比图到 session 目录下 EgoAnchor_Tools2_output/。
    /// </summary>
    public static class Program
    {
        /// <summary>程序入口。</summary>
        public static int Main(string[] args)
        {
            bool diag = false;
            var filtered = new List<string>();
            foreach (var a in args)
            {
                if (a == "--diag") diag = true;
                else filtered.Add(a);
            }
            if (diag) return Diag.Diagnose.Run(filtered.ToArray());
            foreach (var a in filtered) { if (a == "--probe-gap") return Diag.ProbeGap.Run(filtered.ToArray()); }
            foreach (var a in filtered) { if (a == "--probe-jump") return Diag.ProbeJump.Run(filtered.ToArray()); }
            string session = ParseSessionArg(filtered.ToArray());
            if (string.IsNullOrEmpty(session))
            {
                Console.Error.WriteLine("用法:dotnet run -- --session <path-or-id>");
                Console.Error.WriteLine("示例:dotnet run -- --session EgoAnchor_Python\\data\\eval\\20260614_130324_controller_right");
                return 1;
            }

            // 解析 session 路径:支持完整路径或相对仓库根的 id
            string sessionDir = ResolveSessionDir(session);
            string unityOutputPath = Path.Combine(sessionDir, FindUnityOutput(sessionDir));
            if (!File.Exists(unityOutputPath))
            {
                Console.Error.WriteLine($"找不到 unity_output.jsonl:{unityOutputPath}");
                return 2;
            }

            Console.WriteLine($"[AnchorPolicySim] 加载 session:{sessionDir}");
            SessionLoader.Load(unityOutputPath, out List<PoseObservation> observations, out List<RenderTick> renderTicks, out double firstRenderSeconds);
            Console.WriteLine($"  观测数:{observations.Count}  render 帧数:{renderTicks.Count}  首帧时间:{firstRenderSeconds:F3}s");
            if (observations.Count == 0 || renderTicks.Count == 0)
            {
                Console.Error.WriteLine("观测或 render 序列为空,无法仿真。");
                return 3;
            }

            // 加载 condition 分段;缺失时退化为整段 (用首末 render 时间)
            string manifestPath = Path.Combine(sessionDir, "session_manifest.json");
            List<ConditionSpan> conditions = SessionLoader.LoadConditions(manifestPath);
            if (conditions.Count == 0)
            {
                double t0 = renderTicks[0].RenderTimeSeconds;
                double t1 = renderTicks[renderTicks.Count - 1].RenderTimeSeconds;
                conditions = new List<ConditionSpan> { new ConditionSpan("full", t0, t1) };
                Console.WriteLine("  未找到 condition_spans,退化为整段画图。");
            }
            else
            {
                Console.WriteLine($"  条件分段:{conditions.Count} 段 -> {string.Join(", ", conditions.ConvertAll(c => $"{c.Label}({c.DurationSeconds:F1}s)"))}");
            }

            // 构造全部算法 (精简,去掉无效的 SG 平滑变体)。
            // - 实时预测:raw / kalman_ca / oneeuro / egoanchor
            // - snapshot_interp:1 周期延迟纯插值 (平滑但末端冻结)
            // - snap_interp_extrap:1 周期延迟插值 + 末端短窗口预测补偿 (平滑且无冻结)
            // - ideal_interp:零延迟上限参考
            // (predictor, lookaheadSeconds)
            List<(IAnchorPredictor predictor, double lookahead)> predictors = new List<(IAnchorPredictor, double)>
            {
                (new RawZohPredictor(), 0.0),
                (new KalmanCaPredictor(), 0.0),
                (new OneEuroPredictor(), 0.0),
                (new EgoAnchorScoreRPredictor(), 0.0),
                // 快照插值:1 周期延迟,纯 Catmull-Rom 插值,末端够不着时冻结 (ZOH)
                (new SnapshotInterpPredictor(0.2), 0.0),
                // 快照插值 + 末端预测补偿:插值段平滑过点,末端用差分速度短窗口外推,无冻结
                (new SnapshotInterpExtrapolatePredictor(0.2), 0.0),
                // 理想插值参考
                (new IdealInterpPredictor(), 0.3),
            };

            // 输出目录
            string outDir = Path.Combine(sessionDir, "EgoAnchor_Tools2_output");
            Directory.CreateDirectory(outDir);

            // 逐算法仿真
            Dictionary<string, IReadOnlyList<PredictSample>> allResults = new Dictionary<string, IReadOnlyList<PredictSample>>();
            foreach ((IAnchorPredictor predictor, double lookahead) in predictors)
            {
                Console.WriteLine($"[AnchorPolicySim] 仿真算法:{predictor.Label} (lookahead={lookahead:F2}s)");
                List<PredictSample> result = Simulator.Run(predictor, observations, renderTicks, lookahead);
                TrajectoryPlotter.PlotSingle(predictor.Label, result, observations, conditions, outDir, "traj");
                Console.WriteLine($"  按条件分段输出位置/旋转图 ({result.Count} 帧)");
                allResults[predictor.Label] = result;
            }

            // 总对比图 (位置 + 旋转,按条件分段)
            TrajectoryPlotter.PlotComparison(allResults, observations, conditions, outDir, "traj_cmp");
            Console.WriteLine("[AnchorPolicySim] 对比图按条件分段输出完成。");
            Console.WriteLine($"[AnchorPolicySim] 完成。输出目录:{outDir}");
            return 0;
        }

        /// <summary>解析 --session 参数。</summary>
        private static string ParseSessionArg(string[] args)
        {
            for (int i = 0; i < args.Length - 1; i++)
            {
                if (args[i] == "--session" || args[i] == "-s")
                {
                    return args[i + 1];
                }
            }
            return null;
        }

        /// <summary>把 session 参数解析为绝对目录路径。</summary>
        private static string ResolveSessionDir(string session)
        {
            if (Path.IsPathRooted(session) && Directory.Exists(session))
            {
                return session;
            }

            // 相对仓库根
            string repoRoot = FindRepoRoot();
            string candidate = Path.IsPathRooted(session) ? session : Path.Combine(repoRoot, session);
            if (Directory.Exists(candidate))
            {
                return candidate;
            }

            // 仅给 id 时,拼到 eval 目录
            candidate = Path.Combine(repoRoot, "EgoAnchor_Python", "data", "eval", session);
            return candidate;
        }

        /// <summary>从当前目录向上找仓库根 (含 EgoAnchor_Tools2 或 .git)。</summary>
        private static string FindRepoRoot()
        {
            string dir = AppContext.BaseDirectory;
            for (int i = 0; i < 8; i++)
            {
                if (Directory.Exists(Path.Combine(dir, "EgoAnchor_Tools2")) || Directory.Exists(Path.Combine(dir, ".git")))
                {
                    return dir;
                }
                string parent = Path.GetDirectoryName(dir);
                if (string.IsNullOrEmpty(parent) || parent == dir) break;
                dir = parent;
            }
            return AppContext.BaseDirectory;
        }

        /// <summary>在 session 目录中找到 unity_output jsonl 文件名。</summary>
        private static string FindUnityOutput(string sessionDir)
        {
            foreach (string f in Directory.GetFiles(sessionDir, "*_unity_output.jsonl"))
            {
                return Path.GetFileName(f);
            }
            return "*_unity_output.jsonl";
        }
    }
}

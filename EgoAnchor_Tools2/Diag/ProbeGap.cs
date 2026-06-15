using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using EgoAnchor.Tools2.Data;
using EgoAnchor.Tools2.Math;
using EgoAnchor.Tools2.Predictors;
using EgoAnchor.Tools2.Sim;

namespace EgoAnchor.Tools2.Diag
{
    /// <summary>
    /// 抽查两个相邻观测之间的逐 render 帧预测,确认各算法是否真的在观测之间产生平滑过渡。
    /// </summary>
    public static class ProbeGap
    {
        public static int Run(string[] args)
        {
            string dir = null;
            string condLabel = null;
            for (int i = 0; i < args.Length - 1; i++)
            {
                if (args[i] == "--session") dir = Path.IsPathRooted(args[i + 1]) ? args[i + 1]
                    : Path.Combine(FindRepo(), "EgoAnchor_Python", "data", "eval", args[i + 1]);
                if (args[i] == "--cond") condLabel = args[i + 1];
            }
            if (dir == null) { Console.Error.WriteLine("need --session"); return 1; }

            string file = Directory.GetFiles(dir, "*_unity_output.jsonl")[0];
            SessionLoader.Load(file, out var obs, out var ticks, out double t0);
            string manifest = Path.Combine(dir, "session_manifest.json");
            var conds = SessionLoader.LoadConditions(manifest);
            ConditionSpan cond = conds.Count == 0 ? new ConditionSpan("full", ticks[0].RenderTimeSeconds, ticks[ticks.Count - 1].RenderTimeSeconds)
                : (condLabel != null ? conds.First(c => c.Label == condLabel) : conds[0]);

            Console.WriteLine($"=== condition: {cond.Label}  [{cond.StartSeconds:F3}, {cond.EndSeconds:F3}]s  dur={cond.DurationSeconds:F2}s ===");

            // 找该段内第 3-4 个观测之间的一段
            var segObs = obs.Where(o => o.CaptureTimeSeconds >= cond.StartSeconds && o.CaptureTimeSeconds <= cond.EndSeconds).ToList();
            if (segObs.Count < 5) { Console.WriteLine("观测太少"); return 0; }
            int idxA = 3;
            PoseObservation oA = segObs[idxA];
            PoseObservation oB = segObs[idxA + 1];
            Console.WriteLine($"观测 gap: idxA={idxA} tA={oA.CaptureTimeSeconds:F4} posA=({oA.Position.X:F5},{oA.Position.Y:F5},{oA.Position.Z:F5})");
            Console.WriteLine($"         idxB={idxA+1} tB={oB.CaptureTimeSeconds:F4} posB=({oB.Position.X:F5},{oB.Position.Y:F5},{oB.Position.Z:F5})  dt={(oB.CaptureTimeSeconds-oA.CaptureTimeSeconds)*1000:F1}ms");

            // 跑各算法,打印该 gap 内的逐帧预测
            var raw = new RawZohPredictor();
            var kal = new KalmanCaPredictor();
            var one = new OneEuroPredictor();
            var dead = new DeadReckoningCatmullPredictor();
            var snap = new SnapshotInterpPredictor(0.4);
            var ideal = new IdealInterpPredictor();
            var resRaw = Simulator.Run(raw, obs, ticks, 0.0);
            var resKal = Simulator.Run(kal, obs, ticks, 0.0);
            var resOne = Simulator.Run(one, obs, ticks, 0.0);
            var resDead = Simulator.Run(dead, obs, ticks, 0.0);
            var resSnap = Simulator.Run(snap, obs, ticks, 0.0);
            var resIdeal = Simulator.Run(ideal, obs, ticks, 0.3);

            Console.WriteLine($"=== render ticks in gap [{oA.CaptureTimeSeconds:F4}, {oB.CaptureTimeSeconds:F4}] ===");
            Console.WriteLine(string.Format("{0,10} {1,9} {2,10} {3,10} {4,10} {5,10} {6,10} {7,10}", "renderT", "ahead_ms", "rawX", "kalX", "snapX", "oneX", "deadX", "idealX"));
            int cnt = 0;
            for (int i = 0; i < ticks.Count; i++)
            {
                double rt = ticks[i].RenderTimeSeconds;
                if (rt < oA.CaptureTimeSeconds || rt > oB.CaptureTimeSeconds) continue;
                double ahead = (rt - oA.CaptureTimeSeconds) * 1000;
                Console.WriteLine(string.Format("{0,10:F4} {1,9:F1} {2,10:F5} {3,10:F5} {4,10:F5} {5,10:F5} {6,10:F5} {7,10:F5}",
                    rt, ahead, resRaw[i].Position.X, resKal[i].Position.X, resSnap[i].Position.X, resOne[i].Position.X, resDead[i].Position.X, resIdeal[i].Position.X));
                cnt++;
            }
            Console.WriteLine($"共 {cnt} 个 render 帧。snapX(snapshot_interp, 滞后0.4s)在更早的两观测间插值 (注意它的 ahead 是负的滞后)。");
            Console.WriteLine($"posA.X={oA.Position.X:F5} posB.X={oB.Position.X:F5}");
            return 0;
        }

        private static string FindRepo()
        {
            string d = AppContext.BaseDirectory;
            for (int i = 0; i < 8; i++)
            {
                if (Directory.Exists(Path.Combine(d, "EgoAnchor_Tools2"))) return d;
                var p = Path.GetDirectoryName(d); if (p == null || p == d) break; d = p;
            }
            return AppContext.BaseDirectory;
        }
    }
}

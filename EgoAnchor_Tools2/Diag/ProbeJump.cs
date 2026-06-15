using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using EgoAnchor.Tools2.Data;
using EgoAnchor.Tools2.Predictors;
using EgoAnchor.Tools2.Sim;

namespace EgoAnchor.Tools2.Diag
{
    /// <summary>
    /// 检查观测点边界处的跳变:对比 kalman(无纠偏)和 kalman+errblend(有纠偏)在新观测到达瞬间的连续性。
    /// 关键指标:观测点前后相邻两 render 帧的位置差 (跳变量)。
    /// </summary>
    public static class ProbeJump
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

            Console.WriteLine($"=== condition: {cond.Label} ===");
            var kal = new KalmanCaPredictor();
            var snap = new SnapshotInterpPredictor(0.2);
            var snapE = new SnapshotInterpExtrapolatePredictor(0.2);
            var resKal = Simulator.Run(kal, obs, ticks, 0.0);
            var resSnap = Simulator.Run(snap, obs, ticks, 0.0);
            var resSnapE = Simulator.Run(snapE, obs, ticks, 0.0);

            // 跳变统计
            var segObs = obs.Where(o => o.CaptureTimeSeconds >= cond.StartSeconds && o.CaptureTimeSeconds <= cond.EndSeconds).Select(o => o.CaptureTimeSeconds).ToList();

            double[] maxJ = new double[3];
            double[] sumObs = new double[3];
            double[] sumFar = new double[3];
            int nearCount = 0, farCount = 0;
            var allRes = new[] { resKal, resSnap, resSnapE };
            string[] names = { "kalman          ", "snapshot_interp ", "snap_interp_extrap" };
            for (int i = 1; i < resKal.Count; i++)
            {
                double rt = resKal[i].RenderTimeSeconds;
                if (rt < cond.StartSeconds || rt > cond.EndSeconds) continue;
                bool nearObs = false;
                double prevRt = resKal[i - 1].RenderTimeSeconds;
                foreach (double ot in segObs)
                {
                    if ((ot >= prevRt && ot <= rt) || System.Math.Abs(rt - ot) < 0.02) { nearObs = true; break; }
                }
                for (int a = 0; a < 3; a++)
                {
                    double dx = (allRes[a][i].Position.X - allRes[a][i - 1].Position.X) * 1000;
                    double dy = (allRes[a][i].Position.Y - allRes[a][i - 1].Position.Y) * 1000;
                    double dz = (allRes[a][i].Position.Z - allRes[a][i - 1].Position.Z) * 1000;
                    double j = System.Math.Sqrt(dx * dx + dy * dy + dz * dz);
                    if (j > maxJ[a]) maxJ[a] = j;
                    if (nearObs) sumObs[a] += j; else sumFar[a] += j;
                }
                if (nearObs) nearCount++; else farCount++;
            }

            Console.WriteLine($"总 render 帧跳变统计 (mm):  观测点附近帧={nearCount}  非观测点帧={farCount}");
            for (int a = 0; a < 3; a++)
            {
                Console.WriteLine($"  {names[a]}: maxJump={maxJ[a]:F2}  观测点附近均值={(nearCount>0?sumObs[a]/nearCount:0):F3}  非观测点均值={(farCount>0?sumFar[a]/farCount:0):F3}");
            }
            Console.WriteLine($"解读:snap_interp_extrap 应与 snapshot_interp 跳变接近 (都很小),且末端无冻结。");
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

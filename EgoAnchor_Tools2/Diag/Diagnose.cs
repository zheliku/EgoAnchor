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
    /// 算法诊断:输出各算法预测范围、与观测的偏差统计,客观验证曲线合理性。
    /// </summary>
    public static class Diagnose
    {
        public static int Run(string[] args)
        {
            string session = null;
            for (int i = 0; i < args.Length - 1; i++)
                if (args[i] == "--session") session = args[i + 1];
            if (session == null) { Console.Error.WriteLine("need --session"); return 1; }

            string dir = Path.IsPathRooted(session) ? session :
                Path.Combine(FindRepo(), "EgoAnchor_Python", "data", "eval", session);
            string file = Directory.GetFiles(dir, "*_unity_output.jsonl")[0];
            SessionLoader.Load(file, out var obs, out var ticks, out double t0);
            Console.WriteLine($"obs={obs.Count} render={ticks.Count} t0={t0:F3}");

            // 观测范围
            double oMinX = obs.Min(o => o.Position.X), oMaxX = obs.Max(o => o.Position.X);
            double oMinY = obs.Min(o => o.Position.Y), oMaxY = obs.Max(o => o.Position.Y);
            double oMinZ = obs.Min(o => o.Position.Z), oMaxZ = obs.Max(o => o.Position.Z);
            Console.WriteLine($"obs X:[{oMinX:F4},{oMaxX:F4}] Y:[{oMinY:F4},{oMaxY:F4}] Z:[{oMinZ:F4},{oMaxZ:F4}]");

            var predictors = new IAnchorPredictor[]
            {
                new RawZohPredictor(),
                new KalmanCaPredictor(),
                new DeadReckoningCatmullPredictor(),
                new OneEuroPredictor(),
                new EgoAnchorScoreRPredictor(),
            };

            foreach (var p in predictors)
            {
                var res = Simulator.Run(p, obs, ticks);
                // 检查发散/NaN
                int nanCount = res.Count(r => float.IsNaN(r.Position.X) || float.IsNaN(r.Position.Y) || float.IsNaN(r.Position.Z));
                double minX = res.Min(r => r.Position.X), maxX = res.Max(r => r.Position.X);
                double minY = res.Min(r => r.Position.Y), maxY = res.Max(r => r.Position.Y);
                double minZ = res.Min(r => r.Position.Z), maxZ = res.Max(r => r.Position.Z);
                // 平均预测前推时长
                double avgAhead = res.Average(r => r.PredictAheadSeconds);
                // 与最近观测的最大位置偏差 (在观测时刻附近)
                double maxDevX = 0, maxDevY = 0, maxDevZ = 0;
                foreach (var r in res)
                {
                    // 找时间最近的观测
                    double bestDt = double.MaxValue; Vec3 nearest = Vec3.Zero;
                    foreach (var o in obs)
                    {
                        double dt = System.Math.Abs(o.CaptureTimeSeconds - r.RenderTimeSeconds);
                        if (dt < bestDt) { bestDt = dt; nearest = o.Position; }
                    }
                    double dx = System.Math.Abs(r.Position.X - nearest.X);
                    double dy = System.Math.Abs(r.Position.Y - nearest.Y);
                    double dz = System.Math.Abs(r.Position.Z - nearest.Z);
                    if (dx > maxDevX) maxDevX = dx;
                    if (dy > maxDevY) maxDevY = dy;
                    if (dz > maxDevZ) maxDevZ = dz;
                }
                Console.WriteLine($"{p.Label,-26} X:[{minX:F4},{maxX:F4}] Y:[{minY:F4},{maxY:F4}] Z:[{minZ:F4},{maxZ:F4}] NaN={nanCount} avgAhead={avgAhead*1000:F1}ms maxDevNearestObs(m)=({maxDevX:F3},{maxDevY:F3},{maxDevZ:F3})");
            }
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

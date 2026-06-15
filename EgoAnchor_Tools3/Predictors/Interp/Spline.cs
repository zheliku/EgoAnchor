using System;
using EgoAnchor.Tools3.Core;

namespace EgoAnchor.Tools3.Predictors.Interp
{
    /// <summary>
    /// 样条插值数学 (位置用 Vec3, 旋转在调用方用切空间向量复用同一套)。
    ///
    /// 提供两类:
    ///   - Hermite: 已知两端点 P1 P2 + 两端切线速度 v1 v2, 在其间做三次 Hermite。严格过 P1 P2。
    ///   - Catmull-Rom (向心, centripetal α=0.5): 已知四点 P0 P1 P2 P3, 生成 P1→P2 段。
    ///     切线由相邻点自动决定, 只需点不需速度; 向心参数化几乎不出现尖角/自交。严格过 P1 P2。
    /// </summary>
    public static class Spline
    {
        /// <summary>
        /// 三次 Hermite。u∈[0,1] 是 P1→P2 段内的归一参数; spanSeconds 是该段真实时长,
        /// 用于把"每秒速度"换算成 Hermite 单位区间切线 (m = v * span)。
        /// </summary>
        public static Vec3 Hermite(Vec3 p1, Vec3 v1, Vec3 p2, Vec3 v2, double u, double spanSeconds)
        {
            double u2 = u * u;
            double u3 = u2 * u;
            double h00 = 2 * u3 - 3 * u2 + 1;
            double h10 = u3 - 2 * u2 + u;
            double h01 = -2 * u3 + 3 * u2;
            double h11 = u3 - u2;
            Vec3 m1 = v1 * spanSeconds;
            Vec3 m2 = v2 * spanSeconds;
            return p1 * h00 + m1 * h10 + p2 * h01 + m2 * h11;
        }

        /// <summary>
        /// 向心 Catmull-Rom, 生成 P1→P2 段在参数 u∈[0,1] 处的点。
        /// t0..t3 是按向心参数化 (累积 |ΔP|^0.5) 的节点; 内部用 Barry-Goldman 递归 lerp。
        /// 传入的 u 会被映射到 [t1, t2] 区间。
        /// </summary>
        public static Vec3 CentripetalCatmullRom(Vec3 p0, Vec3 p1, Vec3 p2, Vec3 p3, double u)
        {
            // 向心节点 (α=0.5)
            double t0 = 0.0;
            double t1 = t0 + Math.Pow(Math.Max(Vec3.Distance(p0, p1), 1e-9), 0.5);
            double t2 = t1 + Math.Pow(Math.Max(Vec3.Distance(p1, p2), 1e-9), 0.5);
            double t3 = t2 + Math.Pow(Math.Max(Vec3.Distance(p2, p3), 1e-9), 0.5);

            double t = t1 + (t2 - t1) * u; // u∈[0,1] -> [t1,t2]

            Vec3 a1 = Lerp(p0, p1, t0, t1, t);
            Vec3 a2 = Lerp(p1, p2, t1, t2, t);
            Vec3 a3 = Lerp(p2, p3, t2, t3, t);
            Vec3 b1 = Lerp(a1, a2, t0, t2, t);
            Vec3 b2 = Lerp(a2, a3, t1, t3, t);
            return Lerp(b1, b2, t1, t2, t);
        }

        private static Vec3 Lerp(Vec3 a, Vec3 b, double ta, double tb, double t)
        {
            double denom = tb - ta;
            if (Math.Abs(denom) < 1e-12)
            {
                return a;
            }

            double w = (t - ta) / denom;
            return a * (1.0 - w) + b * w;
        }
    }
}

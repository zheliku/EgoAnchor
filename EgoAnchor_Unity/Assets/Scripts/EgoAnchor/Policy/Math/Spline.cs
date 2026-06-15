using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// 样条插值数学。位置用 Vector3；旋转在调用方用切空间向量复用同一套。
    ///
    /// - Hermite：已知两端点 P1 P2 + 两端切线速度 v1 v2，在其间做三次 Hermite。严格过 P1 P2。
    /// - 向心 Catmull-Rom (centripetal α=0.5)：已知四点 P0 P1 P2 P3，生成 P1→P2 段。
    ///   切线由相邻点自动决定，只需点不需速度；向心参数化几乎不出现尖角/自交。严格过 P1 P2。
    /// </summary>
    internal static class Spline
    {
        /// <summary>
        /// 三次 Hermite。u∈[0,1] 是 P1→P2 段内归一参数；spanSeconds 是该段真实时长，
        /// 用于把"每秒速度"换算成 Hermite 单位区间切线 (m = v * span)。
        /// </summary>
        public static Vector3 Hermite(Vector3 p1, Vector3 v1, Vector3 p2, Vector3 v2, float u, float spanSeconds)
        {
            float u2 = u * u;
            float u3 = u2 * u;
            float h00 = 2f * u3 - 3f * u2 + 1f;
            float h10 = u3 - 2f * u2 + u;
            float h01 = -2f * u3 + 3f * u2;
            float h11 = u3 - u2;
            Vector3 m1 = v1 * spanSeconds;
            Vector3 m2 = v2 * spanSeconds;
            return p1 * h00 + m1 * h10 + p2 * h01 + m2 * h11;
        }

        /// <summary>
        /// 向心 Catmull-Rom，生成 P1→P2 段在参数 u∈[0,1] 处的点。
        /// 内部按向心参数化 (累积 |ΔP|^0.5) 用 Barry-Goldman 递归 lerp。
        /// </summary>
        public static Vector3 CentripetalCatmullRom(Vector3 p0, Vector3 p1, Vector3 p2, Vector3 p3, float u)
        {
            const float alpha = 0.5f;
            float t0 = 0f;
            float t1 = t0 + Mathf.Pow(Mathf.Max(Vector3.Distance(p0, p1), 1e-6f), alpha);
            float t2 = t1 + Mathf.Pow(Mathf.Max(Vector3.Distance(p1, p2), 1e-6f), alpha);
            float t3 = t2 + Mathf.Pow(Mathf.Max(Vector3.Distance(p2, p3), 1e-6f), alpha);

            float t = Mathf.Lerp(t1, t2, u);

            Vector3 a1 = Lerp(p0, p1, t0, t1, t);
            Vector3 a2 = Lerp(p1, p2, t1, t2, t);
            Vector3 a3 = Lerp(p2, p3, t2, t3, t);
            Vector3 b1 = Lerp(a1, a2, t0, t2, t);
            Vector3 b2 = Lerp(a2, a3, t1, t3, t);
            return Lerp(b1, b2, t1, t2, t);
        }

        private static Vector3 Lerp(Vector3 a, Vector3 b, float ta, float tb, float t)
        {
            float denom = tb - ta;
            if (Mathf.Abs(denom) < 1e-9f)
            {
                return a;
            }

            float w = (t - ta) / denom;
            return a * (1f - w) + b * w;
        }
    }
}

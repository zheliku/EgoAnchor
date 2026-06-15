using EgoAnchor.Tools2.Math;

namespace EgoAnchor.Tools2.Predictors
{
    /// <summary>
    /// Savitzky-Golay 风格的实时平滑器:对最近 N 帧的位置用二次多项式最小二乘拟合,
    /// 取拟合曲线在最新时刻的值作为平滑输出。
    ///
    /// 这是实时 (因果) 平滑:只用过去 N 帧,不等待未来。等价于一个保形低通滤波器,
    /// 比简单 EWMA 更能保持信号的形状 (边缘、峰值),同时抑制高频抖动。
    ///
    /// 二次多项式拟合 (对长度为 N 的窗口):y(t) = a0 + a1*t + a2*t^2,
    /// 取 t=N-1 (最新点) 的拟合值。系数通过对窗口内点做最小二乘求得。
    /// 为避免每帧解线性方程组,这里用闭式公式 (对均匀采样的二次拟合有解析解)。
    ///
    /// 注:实际 render 间隔非完全均匀 (~16ms 有抖动),但近似均匀处理足够;
    /// 若需更精确可改用带时间权重的最小二乘,但代价是每帧解 3x3 方程组。
    /// </summary>
    public static class SavitzkyGolaySmoother
    {
        /// <summary>
        /// 对长度为 N 的窗口 (索引 0..N-1,均匀采样) 做二次多项式拟合,
        /// 返回最新点 (索引 N-1) 的平滑值。
        /// </summary>
        /// <param name="values">窗口数据 (长度 N,需 >= 3 才能做二次拟合)。</param>
        /// <returns>索引 N-1 处的二次拟合值;N<3 时返回原最新值。</returns>
        public static float SmoothLatest(float[] values)
        {
            int n = values.Length;
            if (n < 3)
            {
                return values[n - 1];
            }

            // 用 0..N-1 作为自变量 t,对 (t, y) 做二次最小二乘:y = a0 + a1*t + a2*t^2
            // 法方程 (3x3),闭式求解。记 S_k = sum(t^k), T_k = sum(t^k * y)
            double s0 = n;
            double s1 = 0, s2 = 0, s3 = 0, s4 = 0;
            double t0 = 0, t1 = 0, t2 = 0;
            for (int i = 0; i < n; i++)
            {
                double t = i;
                double t2v = t * t;
                double t3v = t2v * t;
                double t4v = t3v * t;
                s1 += t;
                s2 += t2v;
                s3 += t3v;
                s4 += t4v;
                double y = values[i];
                t0 += y;
                t1 += t * y;
                t2 += t2v * y;
            }

            // 法方程矩阵:[[s0,s1,s2],[s1,s2,s3],[s2,s3,s4]] * [a0,a1,a2]^T = [t0,t1,t2]^T
            // 解 3x3 线性方程组 (Cramer 法则)
            double m00 = s0, m01 = s1, m02 = s2;
            double m10 = s1, m11 = s2, m12 = s3;
            double m20 = s2, m21 = s3, m22 = s4;
            double det = m00 * (m11 * m22 - m12 * m21)
                       - m01 * (m10 * m22 - m12 * m20)
                       + m02 * (m10 * m21 - m11 * m20);
            if (System.Math.Abs(det) < 1e-12)
            {
                return values[n - 1];
            }

            // a0 = det([t0,m01,m02; t1,m11,m12; t2,m21,m22]) / det
            double da0 = t0 * (m11 * m22 - m12 * m21)
                       - m01 * (t1 * m22 - m12 * t2)
                       + m02 * (t1 * m21 - m11 * t2);
            // a1 = det([m00,t0,m02; m10,t1,m12; m20,t2,m22]) / det
            double da1 = m00 * (t1 * m22 - m12 * t2)
                       - t0 * (m10 * m22 - m12 * m20)
                       + m02 * (m10 * t2 - t1 * m20);
            // a2 = det([m00,m01,t0; m10,m11,t1; m20,m21,t2]) / det
            double da2 = m00 * (m11 * t2 - t1 * m21)
                       - m01 * (m10 * t2 - t1 * m20)
                       + t0 * (m10 * m21 - m11 * m20);
            double a0 = da0 / det;
            double a1 = da1 / det;
            double a2 = da2 / det;

            // 取最新点 t = N-1 的拟合值
            double latest = (n - 1);
            return (float)(a0 + a1 * latest + a2 * latest * latest);
        }
    }
}

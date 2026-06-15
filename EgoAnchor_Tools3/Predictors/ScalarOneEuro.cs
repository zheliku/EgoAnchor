using System;

namespace EgoAnchor.Tools3.Predictors
{
    /// <summary>
    /// 标量 One Euro 滤波器 (Casiez et al. 2012), 同时暴露平滑值和平滑速度 (供外推)。
    ///
    /// 自适应低通: 截止频率随信号变化速度自适应——信号慢时低 (更平滑), 快时高 (更跟手)。
    ///   1) 原始速度 dxRaw 经固定低通 (dCutoff) -> 平滑速度 dxHat;
    ///   2) 自适应截止 fc = minCutoff + beta*|dxHat|;
    ///   3) 用 fc 算的系数低通信号本身 -> 平滑值 xHat。
    ///
    /// 被 OneEuroPredictor (旧外推基线) 和 OneEuroMotionModel (残差淡化管线) 共用。
    /// </summary>
    public sealed class ScalarOneEuro
    {
        private readonly double minCutoff;
        private readonly double beta;
        private readonly double dCutoff;

        private double xHat;
        private double dxHat;
        private double lastTime;
        private bool initialized;

        public ScalarOneEuro(double minCutoff, double beta, double dCutoff)
        {
            this.minCutoff = minCutoff;
            this.beta = beta;
            this.dCutoff = dCutoff;
        }

        /// <summary>平滑后的值。</summary>
        public double Value => xHat;

        /// <summary>平滑后的速度 (单位/秒)。</summary>
        public double Velocity => dxHat;

        public bool Initialized => initialized;

        public void Init(double x, double t)
        {
            xHat = x;
            dxHat = 0.0;
            lastTime = t;
            initialized = true;
        }

        public void Filter(double x, double t)
        {
            if (!initialized)
            {
                Init(x, t);
                return;
            }

            double dt = t - lastTime;
            if (dt <= 1e-6)
            {
                dt = 1e-6;
            }

            lastTime = t;

            double dxRaw = (x - xHat) / dt;
            double aD = Alpha(dt, dCutoff);
            dxHat += aD * (dxRaw - dxHat);

            double cutoff = minCutoff + beta * Math.Abs(dxHat);
            double aX = Alpha(dt, cutoff);
            xHat += aX * (x - xHat);
        }

        private static double Alpha(double dt, double cutoff)
        {
            double tau = 1.0 / (2.0 * Math.PI * cutoff);
            return 1.0 / (1.0 + tau / dt);
        }
    }
}

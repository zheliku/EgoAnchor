using System;

namespace EgoAnchor.Tools3.Predictors
{
    /// <summary>
    /// 一维常速度 (constant-velocity) Kalman 滤波器。
    /// 状态 [位置, 速度]; 过程模型: 位置 += 速度*dt, 速度不变 (随机游走加噪声)。
    ///
    /// 与 Unity 侧 ConstVelocityKalman 结构一致, 便于和真实模块对齐数值。
    /// 协方差 P 是 2x2 对称矩阵, 用 p00/p01/p11 三个量表示。
    /// </summary>
    public sealed class ScalarCvKalman
    {
        public double Position;
        public double Velocity;

        private double p00, p01, p11;
        private bool initialized;

        public bool Initialized => initialized;

        /// <summary>用一帧测量直接初始化状态。</summary>
        public void Reset(double position, double measurementNoise, double initialVelocityVariance)
        {
            Position = position;
            Velocity = 0.0;
            p00 = measurementNoise;
            p01 = 0.0;
            p11 = initialVelocityVariance;
            initialized = true;
        }

        public void Clear()
        {
            Position = 0.0;
            Velocity = 0.0;
            p00 = p01 = p11 = 0.0;
            initialized = false;
        }

        /// <summary>预测步: 推进 dt 秒, processNoise 为速度过程噪声谱密度。</summary>
        public void Predict(double dt, double processNoise)
        {
            if (dt <= 0.0)
            {
                return;
            }

            // 状态外推
            Position += Velocity * dt;

            // 协方差外推 P = F P Fᵀ + Q, F = [[1,dt],[0,1]]
            double newP00 = p00 + dt * (2.0 * p01 + dt * p11);
            double newP01 = p01 + dt * p11;
            double newP11 = p11;

            // 过程噪声 (连续白噪声加速度模型的离散化)
            double dt2 = dt * dt;
            double dt3 = dt2 * dt;
            double q = processNoise;
            newP00 += q * dt3 / 3.0;
            newP01 += q * dt2 / 2.0;
            newP11 += q * dt;

            p00 = newP00;
            p01 = newP01;
            p11 = newP11;
        }

        /// <summary>更新步: 用位置测量 z 校正, measurementNoise 为测量方差 R。</summary>
        public void Correct(double z, double measurementNoise)
        {
            // 观测矩阵 H = [1, 0]
            double s = p00 + measurementNoise;     // 新息协方差
            if (s < 1e-12)
            {
                return;
            }

            double k0 = p00 / s;                    // 卡尔曼增益
            double k1 = p01 / s;
            double y = z - Position;                // 新息

            Position += k0 * y;
            Velocity += k1 * y;

            // P = (I - K H) P
            double newP00 = (1.0 - k0) * p00;
            double newP01 = (1.0 - k0) * p01;
            double newP11 = p11 - k1 * p01;

            p00 = newP00;
            p01 = newP01;
            p11 = newP11;
        }
    }
}

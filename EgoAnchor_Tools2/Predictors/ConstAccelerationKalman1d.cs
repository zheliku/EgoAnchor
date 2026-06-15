using EgoAnchor.Tools2.Math;

namespace EgoAnchor.Tools2.Predictors
{
    /// <summary>
    /// 单维常加速度 (Constant Acceleration) Kalman 滤波器。
    ///
    /// 状态向量 x = [position, velocity, acceleration]^T,只观测位置 (H = [1, 0, 0])。
    /// 与 Unity 侧 ConstVelocityKalman (状态 [pos, vel]) 相比多一阶加速度,
    /// 可以跟踪速度变化,二阶外推预测更准,对应论文里"Kalman Filter Prediction"的标准形态。
    ///
    /// 过程噪声采用标准离散白噪声加速度模型 (jerk 噪声驱动):
    ///   Q = q * [[dt^5/20, dt^4/8, dt^3/6],
    ///            [dt^4/8,  dt^3/3, dt^2/2],
    ///            [dt^3/6,  dt^2/2, dt    ]]
    /// 其中 q 是过程噪声强度 (对应 estimator 的 processNoise 参数)。
    /// </summary>
    public struct ConstAccelerationKalman1d
    {
        /// <summary>估计位置。</summary>
        public float Position;

        /// <summary>估计速度。</summary>
        public float Velocity;

        /// <summary>估计加速度。</summary>
        public float Acceleration;

        // 3x3 协方差矩阵,按行存储
        private float p00, p01, p02;
        private float p10, p11, p12;
        private float p20, p21, p22;

        /// <summary>是否已有状态。</summary>
        public bool HasState { get; private set; }

        /// <summary>重置到初始位置,速度/加速度清零。</summary>
        public void Reset(float position, float measurementNoise, float velocityVariance = 1.0f, float accelVariance = 1.0f)
        {
            Position = position;
            Velocity = 0.0f;
            Acceleration = 0.0f;
            // 初始协方差:位置不确定度 = 测量噪声,速度/加速度给较大不确定度
            p00 = System.Math.Max(measurementNoise * measurementNoise, 1e-12f);
            p11 = System.Math.Max(velocityVariance, 1e-9f);
            p22 = System.Math.Max(accelVariance, 1e-9f);
            p01 = p02 = p10 = p12 = p20 = p21 = 0.0f;
            HasState = true;
        }

        /// <summary>清空状态。</summary>
        public void Clear()
        {
            Position = 0.0f;
            Velocity = 0.0f;
            Acceleration = 0.0f;
            p00 = p01 = p02 = p10 = p11 = p12 = p20 = p21 = p22 = 0.0f;
            HasState = false;
        }

        /// <summary>
        /// 常加速度预测:x = F x, P = F P F^T + Q。
        /// F = [[1, dt, dt^2/2], [0, 1, dt], [0, 0, 1]]。
        /// </summary>
        public void Predict(float dt, float processNoise)
        {
            if (!HasState) return;

            float safeDt = AnchorMath.Max(dt, 0.0f);
            float q = AnchorMath.Max(processNoise, 0.0f);
            float dt2 = 0.5f * safeDt * safeDt;

            // 状态先验:F * x
            Position = Position + Velocity * safeDt + dt2 * Acceleration;
            Velocity = Velocity + Acceleration * safeDt;
            // Acceleration 不变 (常加速度模型)

            // 协方差先验:M = F * P (3x3 = 3x3 * 3x3)
            // F 行 0 = [1, dt, dt2]
            float m00 = p00 + safeDt * p10 + dt2 * p20;
            float m01 = p01 + safeDt * p11 + dt2 * p21;
            float m02 = p02 + safeDt * p12 + dt2 * p22;
            // F 行 1 = [0, 1, dt]
            float m10 = p10 + safeDt * p20;
            float m11 = p11 + safeDt * p21;
            float m12 = p12 + safeDt * p22;
            // F 行 2 = [0, 0, 1]
            float m20 = p20;
            float m21 = p21;
            float m22 = p22;

            // 协方差先验:N = M * F^T (3x3 = 3x3 * 3x3)
            // F^T 列 0 = [1, dt, dt2]^T => N[i][0] = M[i][0] + dt*M[i][1] + dt2*M[i][2]
            // F^T 列 1 = [0, 1, dt]^T   => N[i][1] = M[i][1] + dt*M[i][2]
            // F^T 列 2 = [0, 0, 1]^T     => N[i][2] = M[i][2]
            float n00 = m00 + safeDt * m01 + dt2 * m02;
            float n01 = m01 + safeDt * m02;
            float n02 = m02;
            float n10 = m10 + safeDt * m11 + dt2 * m12;
            float n11 = m11 + safeDt * m12;
            float n12 = m12;
            float n20 = m20 + safeDt * m21 + dt2 * m22;
            float n21 = m21 + safeDt * m22;
            float n22 = m22;

            // 加过程噪声 Q (jerk 驱动白噪声加速度模型,标准公式)
            float dt3 = safeDt * safeDt * safeDt;
            float dt4 = dt3 * safeDt;
            float dt5 = dt4 * safeDt;
            n00 += q * (dt5 / 20f);
            n01 += q * (dt4 / 8f);
            n02 += q * (dt3 / 6f);
            n10 += q * (dt4 / 8f);
            n11 += q * (dt3 / 3f);
            n12 += q * (safeDt * safeDt / 2f);
            n20 += q * (dt3 / 6f);
            n21 += q * (safeDt * safeDt / 2f);
            n22 += q * safeDt;

            p00 = n00; p01 = n01; p02 = n02;
            p10 = n10; p11 = n11; p12 = n12;
            p20 = n20; p21 = n21; p22 = n22;
        }

        /// <summary>位置测量校正 (H = [1,0,0])。</summary>
        public void Correct(float measurement, float measurementNoise)
        {
            if (!HasState)
            {
                Reset(measurement, measurementNoise);
                return;
            }

            float r = AnchorMath.Max(measurementNoise, 1e-12f);
            // 新息
            float innovation = measurement - Position;
            // 新息协方差 S = H P H^T + R = p00 + r
            float s = AnchorMath.Max(p00 + r, 1e-12f);
            // 卡尔曼增益 K = P H^T / S = [p00, p10, p20]^T / S
            float k0 = p00 / s;
            float k1 = p10 / s;
            float k2 = p20 / s;

            // 状态后验
            Position += k0 * innovation;
            Velocity += k1 * innovation;
            Acceleration += k2 * innovation;

            // 协方差后验:P = (I - K H) P
            // (I - K H) 第 i 行 = 第 i 行减去 k_i * [1,0,0],即只改第 0 列
            // P'[i][0] = P[i][0] - k_i * p00,其余列不变
            float n00 = p00 - k0 * p00;
            float n10 = p10 - k1 * p00;
            float n20 = p20 - k2 * p00;
            // p01,p02,p11,p12,p21,p22 不变
            p00 = n00;
            p10 = n10;
            p20 = n20;
        }
    }
}

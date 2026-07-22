using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// 一维位置+速度常速度 Kalman。
    /// Predict 和 Correct 分开，供 MotionModel 在测量时钟和渲染时钟上明确驱动。
    /// </summary>
    internal struct ConstVelocityKalman
    {
        /// <summary>估计位置。</summary>
        public float Position { get; private set; }

        /// <summary>估计速度。</summary>
        public float Velocity { get; private set; }

        /// <summary>位置方差。</summary>
        public float P00 { get; private set; }

        /// <summary>位置-速度协方差。</summary>
        public float P01 { get; private set; }

        /// <summary>速度-位置协方差。</summary>
        public float P10 { get; private set; }

        /// <summary>速度方差。</summary>
        public float P11 { get; private set; }

        /// <summary>是否已有状态。</summary>
        public bool HasState { get; private set; }

        /// <summary>
        /// 重置到初始位置。
        /// </summary>
        public void Reset(float position, float positionVariance = 0.0004f, float velocityVariance = 1.0f)
        {
            Reset(position, 0.0f, positionVariance, velocityVariance);
        }

        /// <summary>
        /// 重置到初始位置和速度。
        /// </summary>
        public void Reset(float position, float velocity, float positionVariance = 0.0004f, float velocityVariance = 1.0f)
        {
            Position = position;
            Velocity = velocity;
            P00 = Mathf.Max(positionVariance, 1e-9f);
            P01 = 0.0f;
            P10 = 0.0f;
            P11 = Mathf.Max(velocityVariance, 1e-9f);
            HasState = true;
        }

        /// <summary>
        /// 清空状态。
        /// </summary>
        public void Clear()
        {
            Position = 0.0f;
            Velocity = 0.0f;
            P00 = 0.0f;
            P01 = 0.0f;
            P10 = 0.0f;
            P11 = 0.0f;
            HasState = false;
        }

        /// <summary>
        /// 常速度预测：x = F x, P = F P F^T + Q。
        /// Q 使用连续白噪声加速度模型，accelerationNoise 是加速度噪声功率谱密度。
        /// </summary>
        public void Predict(float dt, float accelerationNoise)
        {
            if (!HasState)
            {
                return;
            }

            float safeDt = Mathf.Max(dt, 0.0f);
            float q = Mathf.Max(accelerationNoise, 0.0f);
            float dt2 = safeDt * safeDt;
            float dt3 = dt2 * safeDt;
            Position += Velocity * safeDt;

            // 连续白噪声加速度离散化：Q = q * [[dt^3/3, dt^2/2], [dt^2/2, dt]]。
            float processPositionVariance = q * dt3 / 3.0f;
            float processCrossCovariance = q * dt2 / 2.0f;
            float nextP00 = P00 + safeDt * (P10 + P01) + dt2 * P11 + processPositionVariance;
            float nextP01 = P01 + safeDt * P11 + processCrossCovariance;
            float nextP10 = P10 + safeDt * P11 + processCrossCovariance;
            float nextP11 = P11 + q * safeDt;
            P00 = nextP00;
            P01 = 0.5f * (nextP01 + nextP10);
            P10 = P01;
            P11 = nextP11;
        }

        /// <summary>
        /// 位置测量校正。
        /// </summary>
        public void Correct(float measurement, float measurementNoise)
        {
            if (!HasState)
            {
                Reset(measurement, positionVariance: measurementNoise);
                return;
            }

            float r = Mathf.Max(measurementNoise, 1e-9f);
            float priorP00 = Mathf.Max(P00, 0.0f);
            float priorP01 = 0.5f * (P01 + P10);
            float priorP11 = Mathf.Max(P11, 0.0f);
            float innovation = measurement - Position;
            float s = Mathf.Max(priorP00 + r, 1e-12f);
            float k0 = priorP00 / s;
            float k1 = priorP01 / s;

            Position += k0 * innovation;
            Velocity += k1 * innovation;

            // Joseph 形式显式保留对称性和半正定性，避免长序列 float 计算积累负方差。
            float oneMinusK0 = 1.0f - k0;
            float nextP00 = oneMinusK0 * oneMinusK0 * priorP00 + k0 * k0 * r;
            float nextP01 = oneMinusK0 * (priorP01 - k1 * priorP00) + k0 * k1 * r;
            float nextP11 = priorP11
                - 2.0f * k1 * priorP01
                + k1 * k1 * priorP00
                + k1 * k1 * r;
            StabilizeCovariance(nextP00, nextP01, nextP11);
        }

        /// <summary>
        /// 在不改变协方差的前提下重表达状态坐标。
        ///
        /// 旋转 Kalman 每次校正后会把切空间原点搬到当前姿态；此时位置和速度需要
        /// 写入新的局部坐标，但滤波器已经积累的置信度不能被重置。
        /// </summary>
        /// <param name="position">新坐标系中的位置状态。</param>
        /// <param name="velocity">新坐标系中的速度状态。</param>
        public void Rebase(float position, float velocity)
        {
            if (!HasState)
            {
                return;
            }

            Position = position;
            Velocity = velocity;
        }

        /// <summary>
        /// 将二维协方差投影回数值可接受的对称半正定范围。
        /// </summary>
        private void StabilizeCovariance(float p00, float p01, float p11)
        {
            P00 = Mathf.Max(p00, 0.0f);
            P11 = Mathf.Max(p11, 0.0f);
            float maxCross = Mathf.Sqrt(P00 * P11);
            P01 = Mathf.Clamp(p01, -maxCross, maxCross);
            P10 = P01;
        }

    }
}

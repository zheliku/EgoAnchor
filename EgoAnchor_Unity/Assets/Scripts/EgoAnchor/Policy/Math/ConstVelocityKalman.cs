using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// 一维位置+速度常速度 Kalman。
    /// Predict 和 Correct 分开，供 estimator 在测量时钟和渲染时钟上明确驱动。
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
        /// </summary>
        public void Predict(float dt, float processNoise)
        {
            if (!HasState)
            {
                return;
            }

            float safeDt = Mathf.Max(dt, 0.0f);
            float q = Mathf.Max(processNoise, 0.0f);
            Position += Velocity * safeDt;
            float nextP00 = P00 + safeDt * (P10 + P01) + safeDt * safeDt * P11 + q * safeDt;
            float nextP01 = P01 + safeDt * P11;
            float nextP10 = P10 + safeDt * P11;
            float nextP11 = P11 + q * safeDt;
            P00 = nextP00;
            P01 = nextP01;
            P10 = nextP10;
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
            float innovation = measurement - Position;
            float s = Mathf.Max(P00 + r, 1e-12f);
            float k0 = P00 / s;
            float k1 = P10 / s;

            Position += k0 * innovation;
            Velocity += k1 * innovation;

            float nextP00 = (1.0f - k0) * P00;
            float nextP01 = (1.0f - k0) * P01;
            float nextP10 = P10 - k1 * P00;
            float nextP11 = P11 - k1 * P01;
            P00 = nextP00;
            P01 = nextP01;
            P10 = nextP10;
            P11 = nextP11;
        }

        /// <summary>
        /// 将内部速度向观测速度融合，用于高延迟下更快获得可用的渲染外推速度。
        /// </summary>
        public void BlendVelocity(float observedVelocity, float blend)
        {
            if (!HasState)
            {
                return;
            }

            Velocity = Mathf.Lerp(Velocity, observedVelocity, Mathf.Clamp01(blend));
        }
    }
}

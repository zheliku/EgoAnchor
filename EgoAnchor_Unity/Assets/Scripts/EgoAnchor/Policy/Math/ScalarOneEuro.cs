using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// 标量 One Euro 滤波器 (Casiez et al. 2012)，同时暴露平滑值和平滑速度。
    ///
    /// 自适应低通：截止频率随信号变化速度自适应——信号慢时低 (更平滑)，快时高 (更跟手)。
    ///   1) 原始速度 dxRaw 经固定低通 (dCutoff) -> 平滑速度 dxHat；
    ///   2) 自适应截止 fc = minCutoff + beta*|dxHat|；
    ///   3) 用 fc 算的系数低通信号本身 -> 平滑值 xHat。
    ///
    /// 现由 OneEuroModel 使用：额外把 dxHat (平滑速度)
    /// 作为公共属性暴露，供运动模型做高频外推。纯 struct，不依赖 Mono。
    /// </summary>
    internal struct ScalarOneEuro
    {
        private float minCutoff;
        private float beta;
        private float dCutoff;

        private float xHat;
        private float dxHat;
        private float previousRawValue;
        private double lastTimeSeconds;
        private bool initialized;

        /// <summary>平滑后的值。</summary>
        public float Value => xHat;

        /// <summary>平滑后的速度，单位/秒。</summary>
        public float Velocity => dxHat;

        /// <summary>配置滤波参数（构造后或复用前调用）。</summary>
        public void Configure(float minCutoff, float beta, float dCutoff)
        {
            this.minCutoff = Mathf.Max(minCutoff, 1e-4f);
            this.beta = Mathf.Max(beta, 0.0f);
            this.dCutoff = Mathf.Max(dCutoff, 1e-4f);
        }

        /// <summary>清空滤波状态（保留参数）。</summary>
        public void Reset()
        {
            xHat = 0.0f;
            dxHat = 0.0f;
            previousRawValue = 0.0f;
            lastTimeSeconds = 0.0;
            initialized = false;
        }

        /// <summary>直接贴合到初始值，速度清零。</summary>
        public float Snap(float value, double timeSeconds)
        {
            xHat = value;
            dxHat = 0.0f;
            previousRawValue = value;
            lastTimeSeconds = timeSeconds;
            initialized = true;
            return xHat;
        }

        /// <summary>用新测量更新平滑值和平滑速度。</summary>
        public float Update(float value, double timeSeconds)
        {
            if (!initialized)
            {
                return Snap(value, timeSeconds);
            }

            double deltaSeconds = timeSeconds - lastTimeSeconds;
            if (deltaSeconds <= 0.0)
            {
                return xHat;
            }

            float dt = (float)deltaSeconds;
            lastTimeSeconds = timeSeconds;

            float dxRaw = (value - previousRawValue) / dt;
            previousRawValue = value;
            float aD = Alpha(dt, dCutoff);
            dxHat += aD * (dxRaw - dxHat);

            float cutoff = minCutoff + beta * Mathf.Abs(dxHat);
            float aX = Alpha(dt, cutoff);
            xHat += aX * (value - xHat);
            return xHat;
        }

        /// <summary>
        /// 把已初始化的滤波器搬到新的局部坐标系，同时保留时间与滤波历史。
        /// </summary>
        /// <param name="filteredValue">新坐标系中的平滑值。</param>
        /// <param name="rawValue">上一测量在新坐标系中的原始值。</param>
        /// <param name="velocity">新坐标系中的平滑速度。</param>
        public void Rebase(float filteredValue, float rawValue, float velocity)
        {
            if (!initialized)
            {
                return;
            }

            xHat = filteredValue;
            previousRawValue = rawValue;
            dxHat = velocity;
        }

        private static float Alpha(float dt, float cutoff)
        {
            float tau = 1.0f / (2.0f * Mathf.PI * Mathf.Max(cutoff, 1e-4f));
            return 1.0f / (1.0f + tau / Mathf.Max(dt, 1e-5f));
        }
    }
}

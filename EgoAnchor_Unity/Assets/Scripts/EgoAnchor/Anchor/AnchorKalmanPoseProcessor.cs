using UnityEngine;

namespace EgoAnchor.Anchor
{
    /// <summary>
    /// anchor 常速度卡尔曼滤波处理器。
    ///
    /// 位置使用 3 个独立的一维常速度 Kalman filter，适合低频、带噪声的外部 pose 流；
    /// 旋转暂用指数式 Slerp 低通，后续可替换成李代数/四元数滤波。
    ///
    /// 该处理器用于当前阶段的 smoothed anchor 输出；raw 输出仍由 PoseToAnchorRuntime 保留，
    /// 便于论文中做 baseline 对照。
    /// </summary>
    public sealed class AnchorKalmanPoseProcessor : AnchorPoseProcessor
    {
        /// <summary>位置测量噪声。</summary>
        [Header("Position Kalman")]
        [Tooltip("位置测量噪声。值越大，越不相信输入 pose，输出越稳但延迟越大。单位近似 m^2。")]
        [Min(0.000001f)]
        [SerializeField] private float positionMeasurementNoise = 0.0004f;

        /// <summary>位置过程噪声。</summary>
        [Tooltip("位置过程噪声。值越大，越允许目标快速运动，延迟更小但抖动更明显。")]
        [Min(0.000001f)]
        [SerializeField] private float positionProcessNoise = 0.02f;

        /// <summary>旋转响应速度。</summary>
        [Header("Rotation Filter")]
        [Tooltip("旋转响应速度，单位约为 1/s。值越大越快贴近输入，值越小越稳。")]
        [Min(0.01f)]
        [SerializeField] private float rotationResponseSpeed = 8f;

        /// <summary>首次收到位姿时是否直接贴合。</summary>
        [Tooltip("首次收到位姿时是否直接贴合，避免滤波器从原点缓慢收敛。")]
        [SerializeField] private bool snapOnFirstPose = true;

        /// <summary>是否已有滤波状态。</summary>
        private bool hasState;

        /// <summary>x 轴常速度 Kalman 状态。</summary>
        private AxisKalman xAxis;

        /// <summary>y 轴常速度 Kalman 状态。</summary>
        private AxisKalman yAxis;

        /// <summary>z 轴常速度 Kalman 状态。</summary>
        private AxisKalman zAxis;

        /// <summary>滤波后的旋转。</summary>
        private Quaternion filteredRotation = Quaternion.identity;

        /// <summary>上一帧样本时间，单位秒。</summary>
        private double lastSampleTime;

        /// <summary>当前滤波输出，仅用于调试读取。</summary>
        public Pose FilteredPose => new Pose(new Vector3(xAxis.Position, yAxis.Position, zAxis.Position), filteredRotation);

        /// <summary>
        /// 用常速度模型滤波位置，并用指数 Slerp 滤波旋转。
        /// </summary>
        protected override Pose ProcessPose(Pose inputPose, long frameId, double sampleTime)
        {
            if (!hasState)
            {
                xAxis = new AxisKalman(inputPose.position.x);
                yAxis = new AxisKalman(inputPose.position.y);
                zAxis = new AxisKalman(inputPose.position.z);
                filteredRotation = inputPose.rotation;
                lastSampleTime = sampleTime;
                hasState = true;

                if (snapOnFirstPose)
                {
                    return FilteredPose;
                }
            }

            float dt = Mathf.Max((float)(sampleTime - lastSampleTime), 1e-5f);
            lastSampleTime = sampleTime;

            float q = Mathf.Max(positionProcessNoise, 0.000001f);
            float r = Mathf.Max(positionMeasurementNoise, 0.000001f);
            xAxis.Update(inputPose.position.x, dt, q, r);
            yAxis.Update(inputPose.position.y, dt, q, r);
            zAxis.Update(inputPose.position.z, dt, q, r);

            float rotT = 1f - Mathf.Exp(-Mathf.Max(rotationResponseSpeed, 0.01f) * dt);
            filteredRotation = Quaternion.Slerp(filteredRotation, inputPose.rotation, rotT);
            return FilteredPose;
        }

        /// <summary>
        /// 清空 Kalman 状态，让下一条 pose 重新初始化。
        /// </summary>
        public override void ResetProcessor()
        {
            hasState = false;
            xAxis = default;
            yAxis = default;
            zAxis = default;
            filteredRotation = Quaternion.identity;
            lastSampleTime = 0.0;
        }

        /// <summary>
        /// 单轴常速度 Kalman filter。
        /// 状态向量为 [position, velocity]，测量量为 position。
        /// </summary>
        private struct AxisKalman
        {
            /// <summary>当前估计位置。</summary>
            public float Position;

            /// <summary>当前估计速度。</summary>
            private float velocity;

            /// <summary>协方差矩阵 P00。</summary>
            private float p00;

            /// <summary>协方差矩阵 P01。</summary>
            private float p01;

            /// <summary>协方差矩阵 P10。</summary>
            private float p10;

            /// <summary>协方差矩阵 P11。</summary>
            private float p11;

            /// <summary>用初始位置构造单轴 Kalman 状态。</summary>
            public AxisKalman(float initialPosition)
            {
                Position = initialPosition;
                velocity = 0f;
                p00 = 1f;
                p01 = 0f;
                p10 = 0f;
                p11 = 1f;
            }

            /// <summary>
            /// 执行一次 predict + update。
            /// </summary>
            /// <param name="measurement">位置测量值。</param>
            /// <param name="dt">采样间隔，单位秒。</param>
            /// <param name="processNoise">过程噪声。</param>
            /// <param name="measurementNoise">测量噪声。</param>
            public void Update(float measurement, float dt, float processNoise, float measurementNoise)
            {
                // Predict: x = F x, P = F P F^T + Q. F = [1 dt; 0 1].
                Position += velocity * dt;

                float nextP00 = p00 + dt * (p10 + p01) + dt * dt * p11 + processNoise * dt;
                float nextP01 = p01 + dt * p11;
                float nextP10 = p10 + dt * p11;
                float nextP11 = p11 + processNoise * dt;

                // Update with position measurement H = [1 0].
                float innovation = measurement - Position;
                float s = Mathf.Max(nextP00 + measurementNoise, 1e-9f);
                float k0 = nextP00 / s;
                float k1 = nextP10 / s;

                Position += k0 * innovation;
                velocity += k1 * innovation;

                p00 = (1f - k0) * nextP00;
                p01 = (1f - k0) * nextP01;
                p10 = nextP10 - k1 * nextP00;
                p11 = nextP11 - k1 * nextP01;
            }
        }
    }
}



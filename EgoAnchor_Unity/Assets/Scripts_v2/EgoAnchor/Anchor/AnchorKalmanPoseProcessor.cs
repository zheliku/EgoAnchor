using UnityEngine;

namespace EgoAnchor.V2.Anchor
{
    /// <summary>
    /// v2 anchor 常速度卡尔曼滤波处理器。
    ///
    /// 位置使用 3 个独立的一维常速度 Kalman filter，适合低频、带噪声的外部 pose 流；
    /// 旋转暂用指数式 Slerp 低通，后续可替换成李代数/四元数滤波。
    ///
    /// 该处理器用于当前阶段的 smoothed anchor 输出；raw 输出仍由 PoseToAnchorRuntime 保留，
    /// 便于论文中做 baseline 对照。
    /// </summary>
    public sealed class AnchorKalmanPoseProcessor : AnchorPoseProcessor
    {
        [Header("Position Kalman")]
        [Tooltip("位置测量噪声。值越大，越不相信输入 pose，输出越稳但延迟越大。单位近似 m^2。")]
        [Min(0.000001f)]
        [SerializeField] private float positionMeasurementNoise = 0.0004f;

        [Tooltip("位置过程噪声。值越大，越允许目标快速运动，延迟更小但抖动更明显。")]
        [Min(0.000001f)]
        [SerializeField] private float positionProcessNoise = 0.02f;

        [Header("Rotation Filter")]
        [Tooltip("旋转响应速度，单位约为 1/s。值越大越快贴近输入，值越小越稳。")]
        [Min(0.01f)]
        [SerializeField] private float rotationResponseSpeed = 8f;

        [Tooltip("首次收到位姿时是否直接贴合，避免滤波器从原点缓慢收敛。")]
        [SerializeField] private bool snapOnFirstPose = true;

        private bool _hasState;
        private AxisKalman _x;
        private AxisKalman _y;
        private AxisKalman _z;
        private Quaternion _filteredRotation = Quaternion.identity;
        private double _lastSampleTime;

        /// <summary>当前滤波输出，仅用于调试读取。</summary>
        public Pose FilteredPose => new Pose(new Vector3(_x.Position, _y.Position, _z.Position), _filteredRotation);

        protected override Pose ProcessPose(Pose inputPose, long frameId, double sampleTime)
        {
            if (!_hasState)
            {
                _x = new AxisKalman(inputPose.position.x);
                _y = new AxisKalman(inputPose.position.y);
                _z = new AxisKalman(inputPose.position.z);
                _filteredRotation = inputPose.rotation;
                _lastSampleTime = sampleTime;
                _hasState = true;

                if (snapOnFirstPose)
                {
                    return FilteredPose;
                }
            }

            float dt = Mathf.Max((float)(sampleTime - _lastSampleTime), 1e-5f);
            _lastSampleTime = sampleTime;

            float q = Mathf.Max(positionProcessNoise, 0.000001f);
            float r = Mathf.Max(positionMeasurementNoise, 0.000001f);
            _x.Update(inputPose.position.x, dt, q, r);
            _y.Update(inputPose.position.y, dt, q, r);
            _z.Update(inputPose.position.z, dt, q, r);

            float rotT = 1f - Mathf.Exp(-Mathf.Max(rotationResponseSpeed, 0.01f) * dt);
            _filteredRotation = Quaternion.Slerp(_filteredRotation, inputPose.rotation, rotT);
            return FilteredPose;
        }

        public override void ResetProcessor()
        {
            _hasState = false;
            _x = default;
            _y = default;
            _z = default;
            _filteredRotation = Quaternion.identity;
            _lastSampleTime = 0.0;
        }

        private struct AxisKalman
        {
            public float Position;
            private float _velocity;
            private float _p00;
            private float _p01;
            private float _p10;
            private float _p11;

            public AxisKalman(float initialPosition)
            {
                Position = initialPosition;
                _velocity = 0f;
                _p00 = 1f;
                _p01 = 0f;
                _p10 = 0f;
                _p11 = 1f;
            }

            public void Update(float measurement, float dt, float processNoise, float measurementNoise)
            {
                // Predict: x = F x, P = F P F^T + Q. F = [1 dt; 0 1].
                Position += _velocity * dt;

                float p00 = _p00 + dt * (_p10 + _p01) + dt * dt * _p11 + processNoise * dt;
                float p01 = _p01 + dt * _p11;
                float p10 = _p10 + dt * _p11;
                float p11 = _p11 + processNoise * dt;

                // Update with position measurement H = [1 0].
                float innovation = measurement - Position;
                float s = Mathf.Max(p00 + measurementNoise, 1e-9f);
                float k0 = p00 / s;
                float k1 = p10 / s;

                Position += k0 * innovation;
                _velocity += k1 * innovation;

                _p00 = (1f - k0) * p00;
                _p01 = (1f - k0) * p01;
                _p10 = p10 - k1 * p00;
                _p11 = p11 - k1 * p01;
            }
        }
    }
}

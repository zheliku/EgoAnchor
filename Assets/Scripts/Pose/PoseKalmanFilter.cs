using UnityEngine;

/// <summary>
/// PoseFollow 的卡尔曼滤波处理器。
///
/// 放入 PoseFollow.processors 列表后生效。位置使用 3 个独立的常速度 1D Kalman filter；
/// 旋转使用指数式 Slerp 低通。适合抑制物体静止时 pose 估计的细微抖动。
/// </summary>
public class PoseKalmanFilter : PoseProcessor
{
    [Header("Position Kalman")]
    [Tooltip("位置测量噪声。值越大，越不相信输入 pose，输出越稳但延迟越大。")]
    [Min(0.000001f)]
    [SerializeField] private float positionMeasurementNoise = 0.0004f;

    [Tooltip("位置过程噪声。值越大，越允许目标快速运动，延迟更小但抖动更明显。")]
    [Min(0.000001f)]
    [SerializeField] private float positionProcessNoise = 0.02f;

    [Header("Rotation Filter")]
    [Tooltip("旋转响应速度。值越大越快贴近输入，值越小越稳。")]
    [Min(0.01f)]
    [SerializeField] private float rotationResponseSpeed = 8f;

    [Tooltip("首次收到位姿时是否直接贴合。")]
    [SerializeField] private bool snapOnFirstPose = true;

    private bool _hasState;
    private AxisKalman _x;
    private AxisKalman _y;
    private AxisKalman _z;
    private Quaternion _filteredRotation = Quaternion.identity;

    public Pose FilteredPose => new Pose(new Vector3(_x.Position, _y.Position, _z.Position), _filteredRotation);

    protected override Pose ProcessPose(Pose inputPose, long frameId, float sampleTime)
    {
        float dt = Mathf.Max(Time.deltaTime, 1e-5f);

        if (!_hasState)
        {
            _x = new AxisKalman(inputPose.position.x);
            _y = new AxisKalman(inputPose.position.y);
            _z = new AxisKalman(inputPose.position.z);
            _filteredRotation = inputPose.rotation;
            _hasState = true;

            if (snapOnFirstPose)
            {
                return FilteredPose;
            }
        }

        float q = Mathf.Max(positionProcessNoise, 0.000001f);
        float r = Mathf.Max(positionMeasurementNoise, 0.000001f);
        _x.Update(inputPose.position.x, dt, q, r);
        _y.Update(inputPose.position.y, dt, q, r);
        _z.Update(inputPose.position.z, dt, q, r);

        float rotT = 1f - Mathf.Exp(-rotationResponseSpeed * dt);
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
            float s = p00 + measurementNoise;
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

using System.Globalization;
using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// 常速度 Kalman 运动模型 (去噪 + 最优速度估计)。
    ///
    /// 位置 x/y/z 三路一维 CV Kalman；旋转在最新估计姿态的局部切空间里三路 CV Kalman
    /// (估计姿态 + body angular velocity)。每次校正后重置切空间原点，避免固定首帧
    /// 参考在大角度、多轴旋转时产生 Log 分支跳变和角速度坐标基错配。
    ///
    /// 估计部分是经典 CV Kalman，但**没有 maxPredictAhead 限幅**——
    /// 外推不人为截断 (限幅正是旧版"平段+跳变"的根源)，平滑交给 SmoothingStrategy。
    /// </summary>
    public sealed class KalmanModel : MotionModel
    {
        /// <summary>位置加速度噪声功率谱密度，单位 m^2/s^3；越大越允许速度快速变化。</summary>
        [Tooltip("位置加速度噪声功率谱密度，单位 m^2/s^3；越大越允许速度快速变化，跟得更紧但更抖。当前冻结值 0.002。")]
        [SerializeField] private float positionAccelerationNoise = 0.002f;

        /// <summary>位置测量噪声，单位 m^2；越小越信任观测 (越接近过点)。</summary>
        [Tooltip("位置测量噪声，单位 m^2；越小越信任观测、越接近过点。当前冻结值 0.000004。")]
        [SerializeField] private float positionMeasurementNoise = 0.000004f;

        /// <summary>旋转加速度噪声功率谱密度，单位 rad^2/s^3。</summary>
        [Tooltip("旋转加速度噪声功率谱密度，单位 rad^2/s^3；旋转在四元数切空间过滤。当前冻结值 0.2。")]
        [SerializeField] private float rotationAccelerationNoise = 0.20f;

        /// <summary>旋转测量噪声，单位 rad^2。</summary>
        [Tooltip("旋转测量噪声，单位 rad^2；越小越信任观测。当前冻结值 0.0004。")]
        [SerializeField] private float rotationMeasurementNoise = 0.0004f;

        private ConstVelocityKalman x;
        private ConstVelocityKalman y;
        private ConstVelocityKalman z;
        private ConstVelocityKalman rx;
        private ConstVelocityKalman ry;
        private ConstVelocityKalman rz;
        private Quaternion rotationReference;
        private double lastTimeSeconds;
        private bool hasState;

        /// <summary>首帧位置速度方差，单位 (m/s)^2；写入指纹以区分启动阶段语义。</summary>
        private const float InitialPositionVelocityVariance = 1.0f;

        /// <summary>首帧角速度方差，单位 (rad/s)^2；写入指纹以区分启动阶段语义。</summary>
        private const float InitialRotationVelocityVariance = 1.0f;

        public override string ModelName => "kalman";
        public override string ConfigurationFingerprint => string.Format(
            CultureInfo.InvariantCulture,
            "q-model:cwna-v1|pos:{0:R},{1:R},{2:R}|rot:{3:R},{4:R},{5:R}",
            positionAccelerationNoise,
            positionMeasurementNoise,
            InitialPositionVelocityVariance,
            rotationAccelerationNoise,
            rotationMeasurementNoise,
            InitialRotationVelocityVariance);
        public override bool HasState => hasState;
        public override double LastObservationTimeSeconds => lastTimeSeconds;
        public override Vector3 LinearVelocity => new Vector3(x.Velocity, y.Velocity, z.Velocity);
        public override Vector3 AngularVelocityRad => new Vector3(rx.Velocity, ry.Velocity, rz.Velocity);

        public override ControlPoint LatestControlPoint
        {
            get
            {
                if (!hasState)
                {
                    return default;
                }

                Pose pose = new Pose(CurrentPosition(), CurrentRotation());
                return new ControlPoint(lastTimeSeconds, pose, LinearVelocity, AngularVelocityRad);
            }
        }

        public override void Snap(in AnchorObservation observation)
        {
            if (!IsFinite(observation.MeasurementTimeSeconds))
            {
                return;
            }

            Vector3 p = observation.WorldPose.position;
            x.Reset(p.x, positionMeasurementNoise, InitialPositionVelocityVariance);
            y.Reset(p.y, positionMeasurementNoise, InitialPositionVelocityVariance);
            z.Reset(p.z, positionMeasurementNoise, InitialPositionVelocityVariance);
            rotationReference = AnchorMath.Normalize(observation.WorldPose.rotation);
            rx.Reset(0.0f, rotationMeasurementNoise, InitialRotationVelocityVariance);
            ry.Reset(0.0f, rotationMeasurementNoise, InitialRotationVelocityVariance);
            rz.Reset(0.0f, rotationMeasurementNoise, InitialRotationVelocityVariance);
            lastTimeSeconds = observation.MeasurementTimeSeconds;
            hasState = true;
        }

        public override void UpdateState(in AnchorObservation observation)
        {
            if (!hasState)
            {
                Snap(observation);
                return;
            }

            double t = observation.MeasurementTimeSeconds;
            if (!IsFinite(t) || t <= lastTimeSeconds)
            {
                return;
            }

            float dt = (float)(t - lastTimeSeconds);
            x.Predict(dt, positionAccelerationNoise);
            y.Predict(dt, positionAccelerationNoise);
            z.Predict(dt, positionAccelerationNoise);
            rx.Predict(dt, rotationAccelerationNoise);
            ry.Predict(dt, rotationAccelerationNoise);
            rz.Predict(dt, rotationAccelerationNoise);
            lastTimeSeconds = t;

            Vector3 p = observation.WorldPose.position;
            x.Correct(p.x, positionMeasurementNoise);
            y.Correct(p.y, positionMeasurementNoise);
            z.Correct(p.z, positionMeasurementNoise);

            Quaternion measured = AnchorMath.AlignHemisphere(CurrentRotation(), observation.WorldPose.rotation);
            Vector3 err = AnchorMath.RelativeRotationLog(rotationReference, measured);
            rx.Correct(err.x, rotationMeasurementNoise);
            ry.Correct(err.y, rotationMeasurementNoise);
            rz.Correct(err.z, rotationMeasurementNoise);
            RecenterRotationState();
        }

        public override Pose PredictAt(double timeSeconds)
        {
            if (!hasState)
            {
                return Pose.identity;
            }

            float ahead = (float)(timeSeconds - lastTimeSeconds); // 不限幅
            Vector3 position = CurrentPosition() + LinearVelocity * ahead;
            Quaternion rotation = AnchorMath.Multiply(
                CurrentRotation(),
                AnchorMath.Exp(AngularVelocityRad * ahead));
            return new Pose(position, rotation);
        }

        public override void ResetModel()
        {
            x.Clear();
            y.Clear();
            z.Clear();
            rx.Clear();
            ry.Clear();
            rz.Clear();
            rotationReference = Quaternion.identity;
            lastTimeSeconds = 0.0;
            hasState = false;
        }

        private Vector3 CurrentPosition() => new Vector3(x.Position, y.Position, z.Position);

        private Vector3 CurrentRotationVector() => new Vector3(rx.Position, ry.Position, rz.Position);

        private Quaternion CurrentRotation()
        {
            return AnchorMath.Multiply(rotationReference, AnchorMath.Exp(CurrentRotationVector()));
        }

        /// <summary>判断运动时间戳是否为可参与状态传播的有限值。</summary>
        private static bool IsFinite(double value)
        {
            return !double.IsNaN(value) && !double.IsInfinity(value);
        }

        /// <summary>
        /// 把旋转误差状态吸收到参考姿态，并将角速度搬运到新的 body-local 切空间。
        ///
        /// 三个标量 Kalman 的协方差保持不变；旋转噪声配置在三轴上相同，因此这里只需
        /// 旋转速度向量并把位置状态归零，不引入新的轴向调参。
        /// </summary>
        private void RecenterRotationState()
        {
            Vector3 rotationVector = CurrentRotationVector();
            Quaternion rotationDelta = AnchorMath.Exp(rotationVector);
            Vector3 rotationVectorRate = new Vector3(rx.Velocity, ry.Velocity, rz.Velocity);
            Vector3 localVelocity = AnchorMath.ApplyRightJacobian(rotationVector, rotationVectorRate);

            rotationReference = AnchorMath.Multiply(rotationReference, rotationDelta);
            rx.Rebase(0.0f, localVelocity.x);
            ry.Rebase(0.0f, localVelocity.y);
            rz.Rebase(0.0f, localVelocity.z);
        }
    }
}

using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// 常速度 Kalman 运动模型 (去噪 + 最优速度估计)。
    ///
    /// 位置 x/y/z 三路一维 CV Kalman；旋转在最新姿态参考的切空间里三路 CV Kalman
    /// (估计姿态 + 角速度)。复用 ConstVelocityKalman struct。
    ///
    /// 与旧 KalmanEstimatorModule 估计部分一致，但**去掉了 maxPredictAhead 限幅**——
    /// 外推不再人为截断 (那正是旧版"平段+跳变"的根源)，平滑交给 SmoothingStrategy。
    /// </summary>
    public sealed class KalmanModel : MotionModel
    {
        /// <summary>位置过程噪声，单位 m^2/s；越大越允许速度快速变化。</summary>
        [Tooltip("位置过程噪声，单位 m^2/s；越大越允许速度快速变化，跟得更紧但更抖。默认 0.2。")]
        [SerializeField] private float positionProcessNoise = 0.20f;

        /// <summary>位置测量噪声，单位 m^2；越小越信任观测 (越接近过点)。</summary>
        [Tooltip("位置测量噪声，单位 m^2；越小越信任观测、越接近过点。默认 0.0004。")]
        [SerializeField] private float positionMeasurementNoise = 0.0004f;

        /// <summary>旋转过程噪声，单位 rad^2/s。</summary>
        [Tooltip("旋转过程噪声，单位 rad^2/s；旋转在四元数切空间过滤。默认 0.4。")]
        [SerializeField] private float rotationProcessNoise = 0.40f;

        /// <summary>旋转测量噪声，单位 rad^2。</summary>
        [Tooltip("旋转测量噪声，单位 rad^2；越小越信任观测。默认 0.0025。")]
        [SerializeField] private float rotationMeasurementNoise = 0.0025f;

        private ConstVelocityKalman x;
        private ConstVelocityKalman y;
        private ConstVelocityKalman z;
        private ConstVelocityKalman rx;
        private ConstVelocityKalman ry;
        private ConstVelocityKalman rz;
        private Quaternion rotationReference;
        private double lastTimeSeconds;
        private bool hasState;

        public override string ModelName => "kalman";
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
            Vector3 p = observation.WorldPose.position;
            x.Reset(p.x, positionMeasurementNoise, 1.0f);
            y.Reset(p.y, positionMeasurementNoise, 1.0f);
            z.Reset(p.z, positionMeasurementNoise, 1.0f);
            rotationReference = AnchorMath.Normalize(observation.WorldPose.rotation);
            rx.Reset(0.0f, rotationMeasurementNoise, 1.0f);
            ry.Reset(0.0f, rotationMeasurementNoise, 1.0f);
            rz.Reset(0.0f, rotationMeasurementNoise, 1.0f);
            lastTimeSeconds = MeasurementTime(observation);
            hasState = true;
        }

        public override void UpdateState(in AnchorObservation observation)
        {
            if (!hasState)
            {
                Snap(observation);
                return;
            }

            double t = MeasurementTime(observation);
            float dt = Mathf.Max((float)(t - lastTimeSeconds), 0.0f);
            x.Predict(dt, positionProcessNoise);
            y.Predict(dt, positionProcessNoise);
            z.Predict(dt, positionProcessNoise);
            rx.Predict(dt, rotationProcessNoise);
            ry.Predict(dt, rotationProcessNoise);
            rz.Predict(dt, rotationProcessNoise);
            lastTimeSeconds = t;

            Vector3 p = observation.WorldPose.position;
            x.Correct(p.x, positionMeasurementNoise);
            y.Correct(p.y, positionMeasurementNoise);
            z.Correct(p.z, positionMeasurementNoise);

            Quaternion measured = AnchorMath.AlignHemisphere(CurrentRotation(), observation.WorldPose.rotation);
            Vector3 err = AnchorMath.Log(AnchorMath.Multiply(AnchorMath.Inverse(rotationReference), measured));
            rx.Correct(err.x, rotationMeasurementNoise);
            ry.Correct(err.y, rotationMeasurementNoise);
            rz.Correct(err.z, rotationMeasurementNoise);
        }

        public override Pose PredictAt(double timeSeconds)
        {
            if (!hasState)
            {
                return Pose.identity;
            }

            float ahead = (float)(timeSeconds - lastTimeSeconds); // 不限幅
            Vector3 position = CurrentPosition() + LinearVelocity * ahead;
            Vector3 rotVec = new Vector3(rx.Position, ry.Position, rz.Position) + AngularVelocityRad * ahead;
            Quaternion rotation = AnchorMath.Multiply(rotationReference, AnchorMath.Exp(rotVec));
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

        private Quaternion CurrentRotation()
        {
            return AnchorMath.Multiply(rotationReference, AnchorMath.Exp(new Vector3(rx.Position, ry.Position, rz.Position)));
        }

        private static double MeasurementTime(in AnchorObservation observation)
        {
            return observation.HasCaptureTime ? observation.CaptureTimeSeconds : observation.SampleTimeSeconds;
        }
    }
}

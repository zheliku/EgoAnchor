using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// 常速度 Kalman estimator。
    /// 平移使用三个一维位置-速度 Kalman；旋转使用四元数参考姿态上的 Log/Exp 误差态和角速度。
    /// </summary>
    public sealed class KalmanEstimatorModule : AnchorEstimatorModule
    {
        private const int DefaultsVersion = 1;

        /// <summary>位置过程噪声，单位 m^2/s。</summary>
        [Tooltip("位置过程噪声，单位 m^2/s；越大越允许速度快速变化。")]
        [SerializeField] private float positionProcessNoise = 0.20f;

        /// <summary>位置测量噪声，单位 m^2。</summary>
        [Tooltip("位置测量噪声，单位 m^2；baseline 固定使用，不读取可靠性分数。")]
        [SerializeField] private float positionMeasurementNoise = 0.0004f;

        /// <summary>旋转过程噪声，单位 (rad^2)/s。</summary>
        [Tooltip("旋转过程噪声，单位 (rad^2)/s；旋转在四元数切空间中过滤。")]
        [SerializeField] private float rotationProcessNoise = 0.40f;

        /// <summary>旋转测量噪声，单位 rad^2。</summary>
        [Tooltip("旋转测量噪声，单位 rad^2；baseline 固定使用，不读取可靠性分数。")]
        [SerializeField] private float rotationMeasurementNoise = 0.0025f;

        /// <summary>允许预测到最近测量之后的最大时长，单位秒。</summary>
        [Tooltip("允许预测到最近测量之后的最大时长，单位秒。")]
        [SerializeField] private float maxPredictAheadSeconds = 0.18f;

        private int defaultsInitializedVersion = DefaultsVersion;
        private ConstVelocityKalman x;
        private ConstVelocityKalman y;
        private ConstVelocityKalman z;
        private ConstVelocityKalman rx;
        private ConstVelocityKalman ry;
        private ConstVelocityKalman rz;
        private Quaternion rotationReference = Quaternion.identity;
        private double lastTimeSeconds;
        private float latestScore = 1.0f;
        private bool hasEstimate;

        /// <summary>日志和 eval 使用的模块名。</summary>
        public override string ModuleName => "kalman_cv";

        /// <summary>是否已有可输出估计状态。</summary>
        public override bool HasEstimate => hasEstimate;

        /// <summary>当前估计线速度，单位米/秒。</summary>
        public override Vector3 LinearVelocity => new Vector3(x.Velocity, y.Velocity, z.Velocity);

        /// <summary>当前估计角速度，单位 rad/s。</summary>
        public override Vector3 AngularVelocityRad => new Vector3(rx.Velocity, ry.Velocity, rz.Velocity);

        /// <summary>最近一次接受的可靠性分数。</summary>
        public override float LastReliabilityScore => latestScore;

        /// <summary>直接重置 Kalman 状态到测量。</summary>
        public override void Snap(in AnchorObservation observation)
        {
            EnsureDefaults();
            Vector3 p = observation.WorldPose.position;
            x.Reset(p.x, positionMeasurementNoise, 1.0f);
            y.Reset(p.y, positionMeasurementNoise, 1.0f);
            z.Reset(p.z, positionMeasurementNoise, 1.0f);
            rotationReference = AnchorMath.Normalize(observation.WorldPose.rotation);
            rx.Reset(0.0f, rotationMeasurementNoise, 1.0f);
            ry.Reset(0.0f, rotationMeasurementNoise, 1.0f);
            rz.Reset(0.0f, rotationMeasurementNoise, 1.0f);
            lastTimeSeconds = MeasurementTime(observation);
            latestScore = observation.ReliabilityScore;
            hasEstimate = true;
        }

        /// <summary>按常速度 Kalman 预测到测量时间并校正。</summary>
        public override void UpdateEstimate(in AnchorObservation observation)
        {
            EnsureDefaults();
            if (!hasEstimate)
            {
                Snap(observation);
                return;
            }

            double time = MeasurementTime(observation);
            PredictStateTo(time);
            Vector3 p = observation.WorldPose.position;
            x.Correct(p.x, positionMeasurementNoise);
            y.Correct(p.y, positionMeasurementNoise);
            z.Correct(p.z, positionMeasurementNoise);

            Quaternion measured = AnchorMath.AlignHemisphere(CurrentRotation(), observation.WorldPose.rotation);
            Vector3 measuredError = AnchorMath.Log(AnchorMath.Multiply(AnchorMath.Inverse(rotationReference), measured));
            rx.Correct(measuredError.x, rotationMeasurementNoise);
            ry.Correct(measuredError.y, rotationMeasurementNoise);
            rz.Correct(measuredError.z, rotationMeasurementNoise);
            latestScore = observation.ReliabilityScore;
        }

        /// <summary>预测到指定渲染时间。</summary>
        public override AnchorEstimate PredictAt(double renderTimeSeconds)
        {
            EnsureDefaults();
            if (!hasEstimate)
            {
                return AnchorEstimate.Stationary(Pose.identity, renderTimeSeconds);
            }

            float ahead = Mathf.Clamp((float)(renderTimeSeconds - lastTimeSeconds), 0.0f, maxPredictAheadSeconds);
            Vector3 position = new Vector3(
                x.Position + x.Velocity * ahead,
                y.Position + y.Velocity * ahead,
                z.Position + z.Velocity * ahead
            );
            Vector3 rotVector = new Vector3(
                rx.Position + rx.Velocity * ahead,
                ry.Position + ry.Velocity * ahead,
                rz.Position + rz.Velocity * ahead
            );
            Pose pose = new Pose(position, AnchorMath.Multiply(rotationReference, AnchorMath.Exp(rotVector)));
            return new AnchorEstimate(pose, LinearVelocity, AngularVelocityRad, renderTimeSeconds, 1.0f, latestScore, ahead);
        }

        /// <summary>清空 Kalman 状态并恢复 headless 默认参数。</summary>
        public override void ResetModule()
        {
            EnsureDefaults();
            x.Clear();
            y.Clear();
            z.Clear();
            rx.Clear();
            ry.Clear();
            rz.Clear();
            rotationReference = Quaternion.identity;
            lastTimeSeconds = 0.0;
            latestScore = 1.0f;
            hasEstimate = false;
        }

        private void PredictStateTo(double timeSeconds)
        {
            float dt = Mathf.Max((float)(timeSeconds - lastTimeSeconds), 0.0f);
            if (dt <= 0.0f)
            {
                lastTimeSeconds = timeSeconds;
                return;
            }

            x.Predict(dt, positionProcessNoise);
            y.Predict(dt, positionProcessNoise);
            z.Predict(dt, positionProcessNoise);
            rx.Predict(dt, rotationProcessNoise);
            ry.Predict(dt, rotationProcessNoise);
            rz.Predict(dt, rotationProcessNoise);
            lastTimeSeconds = timeSeconds;
        }

        private Quaternion CurrentRotation()
        {
            return AnchorMath.Multiply(rotationReference, AnchorMath.Exp(new Vector3(rx.Position, ry.Position, rz.Position)));
        }

        private void EnsureDefaults()
        {
            if (defaultsInitializedVersion == DefaultsVersion)
            {
                return;
            }

            positionProcessNoise = 0.20f;
            positionMeasurementNoise = 0.0004f;
            rotationProcessNoise = 0.40f;
            rotationMeasurementNoise = 0.0025f;
            maxPredictAheadSeconds = 0.18f;
            defaultsInitializedVersion = DefaultsVersion;
        }

        private static double MeasurementTime(in AnchorObservation observation)
        {
            return observation.HasCaptureTime ? observation.CaptureTimeSeconds : observation.SampleTimeSeconds;
        }
    }
}

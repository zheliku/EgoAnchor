using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// EgoAnchor score-aware estimator。
    /// 结构仍是常速度估计，但测量噪声和预测速度按可靠性分数调节，用于主方法/消融。
    /// </summary>
    public sealed class EgoAnchorEstimatorModule : AnchorEstimatorModule
    {
        private const int DefaultsVersion = 1;

        /// <summary>基础位置过程噪声，单位 m^2/s。</summary>
        [Tooltip("基础位置过程噪声，单位 m^2/s。")]
        [SerializeField] private float positionProcessNoise = 0.16f;

        /// <summary>基础位置测量噪声，单位 m^2。</summary>
        [Tooltip("基础位置测量噪声，单位 m^2；实际使用时会按可靠性分数放大。")]
        [SerializeField] private float positionMeasurementNoise = 0.00035f;

        /// <summary>基础旋转过程噪声，单位 (rad^2)/s。</summary>
        [Tooltip("基础旋转过程噪声，单位 (rad^2)/s。")]
        [SerializeField] private float rotationProcessNoise = 0.35f;

        /// <summary>基础旋转测量噪声，单位 rad^2。</summary>
        [Tooltip("基础旋转测量噪声，单位 rad^2；实际使用时会按可靠性分数放大。")]
        [SerializeField] private float rotationMeasurementNoise = 0.0020f;

        /// <summary>低分测量放大噪声的倍数上限。</summary>
        [Tooltip("低分测量放大噪声的倍数上限；只用于 EgoAnchor 方法，不用于 vanilla baseline。")]
        [SerializeField] private float lowScoreNoiseMultiplier = 16.0f;

        /// <summary>低分时预测速度保留比例。</summary>
        [Tooltip("低分时预测速度保留比例；低可靠性下减少外推漂移。")]
        [SerializeField] private float lowScoreVelocityKeep = 0.20f;

        /// <summary>允许预测到最近测量之后的最大时长，单位秒。</summary>
        [Tooltip("允许预测到最近测量之后的最大时长，单位秒。")]
        [SerializeField] private float maxPredictAheadSeconds = 0.16f;

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
        public override string ModuleName => "egoanchor_estimator";

        /// <summary>是否已有可输出估计状态。</summary>
        public override bool HasEstimate => hasEstimate;

        /// <summary>当前估计线速度，单位米/秒。</summary>
        public override Vector3 LinearVelocity => DampedVelocity(new Vector3(x.Velocity, y.Velocity, z.Velocity));

        /// <summary>当前估计角速度，单位 rad/s。</summary>
        public override Vector3 AngularVelocityRad => DampedVelocity(new Vector3(rx.Velocity, ry.Velocity, rz.Velocity));

        /// <summary>最近一次接受的可靠性分数。</summary>
        public override float LastReliabilityScore => latestScore;

        /// <summary>直接重置到测量。</summary>
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

        /// <summary>按可靠性分数调节测量权重后校正状态。</summary>
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
            float multiplier = ReliabilityNoiseMultiplier(observation.ReliabilityScore);
            float posNoise = positionMeasurementNoise * multiplier;
            float rotNoise = rotationMeasurementNoise * multiplier;
            Vector3 p = observation.WorldPose.position;
            x.Correct(p.x, posNoise);
            y.Correct(p.y, posNoise);
            z.Correct(p.z, posNoise);

            Quaternion measured = AnchorMath.AlignHemisphere(CurrentRotation(), observation.WorldPose.rotation);
            Vector3 measuredError = AnchorMath.Log(AnchorMath.Multiply(AnchorMath.Inverse(rotationReference), measured));
            rx.Correct(measuredError.x, rotNoise);
            ry.Correct(measuredError.y, rotNoise);
            rz.Correct(measuredError.z, rotNoise);
            latestScore = Mathf.Clamp01(observation.ReliabilityScore);
        }

        /// <summary>预测到渲染时间，低分时自动缩短速度外推。</summary>
        public override AnchorEstimate PredictAt(double renderTimeSeconds)
        {
            EnsureDefaults();
            if (!hasEstimate)
            {
                return AnchorEstimate.Stationary(Pose.identity, renderTimeSeconds);
            }

            float ahead = Mathf.Clamp((float)(renderTimeSeconds - lastTimeSeconds), 0.0f, maxPredictAheadSeconds);
            Vector3 linear = LinearVelocity;
            Vector3 angular = AngularVelocityRad;
            Vector3 position = new Vector3(x.Position, y.Position, z.Position) + linear * ahead;
            Vector3 rotVector = new Vector3(rx.Position, ry.Position, rz.Position) + angular * ahead;
            Pose pose = new Pose(position, AnchorMath.Multiply(rotationReference, AnchorMath.Exp(rotVector)));
            return new AnchorEstimate(pose, linear, angular, renderTimeSeconds, latestScore, latestScore);
        }

        /// <summary>清空状态并恢复 headless 默认参数。</summary>
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

        private float ReliabilityNoiseMultiplier(float score)
        {
            float inverse = 1.0f - Mathf.Clamp01(score);
            return Mathf.Lerp(1.0f, Mathf.Max(lowScoreNoiseMultiplier, 1.0f), inverse * inverse);
        }

        private Vector3 DampedVelocity(Vector3 value)
        {
            float keep = Mathf.Lerp(Mathf.Clamp01(lowScoreVelocityKeep), 1.0f, Mathf.Clamp01(latestScore));
            return value * keep;
        }

        private void EnsureDefaults()
        {
            if (defaultsInitializedVersion == DefaultsVersion)
            {
                return;
            }

            positionProcessNoise = 0.16f;
            positionMeasurementNoise = 0.00035f;
            rotationProcessNoise = 0.35f;
            rotationMeasurementNoise = 0.0020f;
            lowScoreNoiseMultiplier = 16.0f;
            lowScoreVelocityKeep = 0.20f;
            maxPredictAheadSeconds = 0.16f;
            defaultsInitializedVersion = DefaultsVersion;
        }

        private static double MeasurementTime(in AnchorObservation observation)
        {
            return observation.HasCaptureTime ? observation.CaptureTimeSeconds : observation.SampleTimeSeconds;
        }
    }
}

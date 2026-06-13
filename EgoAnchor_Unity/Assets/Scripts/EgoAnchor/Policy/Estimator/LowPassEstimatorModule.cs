using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// 简单低通 + 常速度前推 estimator。
    /// 平移用指数低通，旋转用四元数切空间指数低通，速度从滤波后状态估计。
    /// </summary>
    public sealed class LowPassEstimatorModule : AnchorEstimatorModule
    {
        private const int DefaultsVersion = 1;

        /// <summary>位置低通响应速率，单位 1/s。</summary>
        [Tooltip("位置低通响应速率，单位 1/s；越大越跟手，越小越平滑。")]
        [SerializeField] private float positionRate = 8.0f;

        /// <summary>旋转低通响应速率，单位 1/s。</summary>
        [Tooltip("旋转低通响应速率，单位 1/s；旋转在四元数切空间中更新，不使用 Euler。")]
        [SerializeField] private float rotationRate = 8.0f;

        /// <summary>速度低通响应速率，单位 1/s。</summary>
        [Tooltip("速度低通响应速率，单位 1/s；用于渲染帧之间的前推。")]
        [SerializeField] private float velocityRate = 6.0f;

        /// <summary>允许预测到最近测量之后的最大时长，单位秒。</summary>
        [Tooltip("允许预测到最近测量之后的最大时长，单位秒，避免长时间无输入时继续漂移。")]
        [SerializeField] private float maxPredictAheadSeconds = 0.18f;

        private int defaultsInitializedVersion = DefaultsVersion;
        private Pose filteredPose = Pose.identity;
        private Pose lastRawPose = Pose.identity;
        private double lastTimeSeconds;
        private Vector3 linearVelocity;
        private Vector3 angularVelocityRad;
        private float latestScore = 1.0f;
        private bool hasEstimate;

        /// <summary>日志和 eval 使用的模块名。</summary>
        public override string ModuleName => "lowpass_predict";

        /// <summary>是否已有可输出估计状态。</summary>
        public override bool HasEstimate => hasEstimate;

        /// <summary>当前估计线速度，单位米/秒。</summary>
        public override Vector3 LinearVelocity => linearVelocity;

        /// <summary>当前估计角速度，单位 rad/s。</summary>
        public override Vector3 AngularVelocityRad => angularVelocityRad;

        /// <summary>最近一次接受的可靠性分数。</summary>
        public override float LastReliabilityScore => latestScore;

        /// <summary>直接贴合到测量。</summary>
        public override void Snap(in AnchorObservation observation)
        {
            EnsureDefaults();
            filteredPose = observation.WorldPose;
            lastRawPose = observation.WorldPose;
            lastTimeSeconds = MeasurementTime(observation);
            linearVelocity = Vector3.zero;
            angularVelocityRad = Vector3.zero;
            latestScore = observation.ReliabilityScore;
            hasEstimate = true;
        }

        /// <summary>用低通状态融合一帧新测量。</summary>
        public override void UpdateEstimate(in AnchorObservation observation)
        {
            EnsureDefaults();
            if (!hasEstimate)
            {
                Snap(observation);
                return;
            }

            double time = MeasurementTime(observation);
            float dt = Mathf.Max((float)(time - lastTimeSeconds), 1e-5f);
            Vector3 rawLinearVelocity = (observation.WorldPose.position - lastRawPose.position) / dt;
            Vector3 rawAngularVelocity = AnchorMath.AngularVelocity(lastRawPose.rotation, observation.WorldPose.rotation, dt);
            float velocityAlpha = ExponentialAlpha(velocityRate, dt);
            linearVelocity = Vector3.Lerp(linearVelocity, rawLinearVelocity, velocityAlpha);
            angularVelocityRad = Vector3.Lerp(angularVelocityRad, rawAngularVelocity, velocityAlpha);

            float positionAlpha = ExponentialAlpha(positionRate, dt);
            float rotationAlpha = ExponentialAlpha(rotationRate, dt);
            filteredPose = new Pose(
                Vector3.Lerp(filteredPose.position, observation.WorldPose.position, positionAlpha),
                BlendRotation(filteredPose.rotation, observation.WorldPose.rotation, rotationAlpha)
            );
            lastRawPose = observation.WorldPose;
            lastTimeSeconds = time;
            latestScore = observation.ReliabilityScore;
        }

        /// <summary>将低通状态按速度前推到渲染时间。</summary>
        public override AnchorEstimate PredictAt(double renderTimeSeconds)
        {
            EnsureDefaults();
            float ahead = hasEstimate ? Mathf.Clamp((float)(renderTimeSeconds - lastTimeSeconds), 0.0f, maxPredictAheadSeconds) : 0.0f;
            Pose predicted = AnchorMath.Integrate(filteredPose, linearVelocity, angularVelocityRad, ahead);
            return new AnchorEstimate(predicted, linearVelocity, angularVelocityRad, renderTimeSeconds, 1.0f, latestScore, ahead);
        }

        /// <summary>清空估计状态并恢复 headless 默认参数。</summary>
        public override void ResetModule()
        {
            EnsureDefaults();
            filteredPose = Pose.identity;
            lastRawPose = Pose.identity;
            lastTimeSeconds = 0.0;
            linearVelocity = Vector3.zero;
            angularVelocityRad = Vector3.zero;
            latestScore = 1.0f;
            hasEstimate = false;
        }

        private void EnsureDefaults()
        {
            if (defaultsInitializedVersion == DefaultsVersion)
            {
                return;
            }

            positionRate = 8.0f;
            rotationRate = 8.0f;
            velocityRate = 6.0f;
            maxPredictAheadSeconds = 0.18f;
            defaultsInitializedVersion = DefaultsVersion;
        }

        private static double MeasurementTime(in AnchorObservation observation)
        {
            return observation.HasCaptureTime ? observation.CaptureTimeSeconds : observation.SampleTimeSeconds;
        }

        private static float ExponentialAlpha(float rate, float dt)
        {
            return 1.0f - Mathf.Exp(-Mathf.Max(rate, 0.0f) * Mathf.Max(dt, 0.0f));
        }

        private static Quaternion BlendRotation(Quaternion from, Quaternion to, float alpha)
        {
            Quaternion aligned = AnchorMath.AlignHemisphere(from, to);
            Vector3 delta = AnchorMath.Log(AnchorMath.Multiply(AnchorMath.Inverse(from), aligned));
            return AnchorMath.Multiply(from, AnchorMath.Exp(delta * Mathf.Clamp01(alpha)));
        }
    }
}

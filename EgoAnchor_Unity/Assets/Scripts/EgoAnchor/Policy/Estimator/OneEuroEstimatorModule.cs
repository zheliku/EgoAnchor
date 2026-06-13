using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// Vanilla One Euro estimator。
    /// baseline 固定使用同一组 cutoff 参数，不读取可靠性分数；旋转在四元数切空间中过滤。
    /// </summary>
    public sealed class OneEuroEstimatorModule : AnchorEstimatorModule
    {
        private const int DefaultsVersion = 1;
        private const float SafeMaxPredictAheadSeconds = 0.12f;

        /// <summary>最低截止频率，单位 Hz。</summary>
        [Tooltip("最低截止频率，单位 Hz；越低越平滑。")]
        [SerializeField] private float minCutoff = 1.0f;

        /// <summary>速度自适应系数。</summary>
        [Tooltip("速度自适应系数 beta；越大越能在快速运动时降低滞后。")]
        [SerializeField] private float beta = 0.25f;

        /// <summary>导数低通截止频率，单位 Hz。</summary>
        [Tooltip("导数低通截止频率，单位 Hz。")]
        [SerializeField] private float derivativeCutoff = 1.0f;

        /// <summary>允许预测到最近测量之后的最大时长，单位秒；One Euro 只做短窗口补帧。</summary>
        [Tooltip("允许预测到最近测量之后的最大时长，单位秒；One Euro 只做短窗口补帧，运行时硬上限为 0.12s。")]
        [SerializeField] private float maxPredictAheadSeconds = SafeMaxPredictAheadSeconds;

        private int defaultsInitializedVersion = DefaultsVersion;
        private OneEuroVector3 positionFilter;
        private OneEuroRotation rotationFilter;
        private Pose filteredPose = Pose.identity;
        private Pose previousFilteredPose = Pose.identity;
        private double lastTimeSeconds;
        private Vector3 linearVelocity;
        private Vector3 angularVelocityRad;
        private float latestScore = 1.0f;
        private bool hasEstimate;

        /// <summary>日志和 eval 使用的模块名。</summary>
        public override string ModuleName => "oneeuro_vanilla";

        /// <summary>是否已有可输出估计状态。</summary>
        public override bool HasEstimate => hasEstimate;

        /// <summary>当前估计线速度，单位米/秒。</summary>
        public override Vector3 LinearVelocity => linearVelocity;

        /// <summary>当前估计角速度，单位 rad/s。</summary>
        public override Vector3 AngularVelocityRad => angularVelocityRad;

        /// <summary>最近一次接受的可靠性分数。</summary>
        public override float LastReliabilityScore => latestScore;

        /// <summary>直接贴合到测量并初始化 One Euro 状态。</summary>
        public override void Snap(in AnchorObservation observation)
        {
            EnsureDefaults();
            double time = MeasurementTime(observation);
            filteredPose = new Pose(
                positionFilter.Snap(observation.WorldPose.position, time),
                rotationFilter.Snap(observation.WorldPose.rotation, time)
            );
            previousFilteredPose = filteredPose;
            lastTimeSeconds = time;
            linearVelocity = Vector3.zero;
            angularVelocityRad = Vector3.zero;
            latestScore = observation.ReliabilityScore;
            hasEstimate = true;
        }

        /// <summary>按官方 One Euro 公式更新平移和旋转滤波值。</summary>
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
            previousFilteredPose = filteredPose;
            filteredPose = new Pose(
                positionFilter.Update(observation.WorldPose.position, time),
                rotationFilter.Update(observation.WorldPose.rotation, time)
            );
            linearVelocity = (filteredPose.position - previousFilteredPose.position) / dt;
            angularVelocityRad = AnchorMath.AngularVelocity(previousFilteredPose.rotation, filteredPose.rotation, dt);
            lastTimeSeconds = time;
            latestScore = observation.ReliabilityScore;
        }

        /// <summary>用滤波状态和估计速度前推到渲染时间。</summary>
        public override AnchorEstimate PredictAt(double renderTimeSeconds)
        {
            EnsureDefaults();
            float ahead = hasEstimate ? Mathf.Clamp((float)(renderTimeSeconds - lastTimeSeconds), 0.0f, EffectiveMaxPredictAheadSeconds()) : 0.0f;
            Pose predicted = AnchorMath.Integrate(filteredPose, linearVelocity, angularVelocityRad, ahead);
            return new AnchorEstimate(predicted, linearVelocity, angularVelocityRad, renderTimeSeconds, 1.0f, latestScore, ahead);
        }

        /// <summary>清空滤波状态并恢复 headless 默认参数。</summary>
        public override void ResetModule()
        {
            EnsureDefaults();
            positionFilter.Reset();
            rotationFilter.Reset();
            filteredPose = Pose.identity;
            previousFilteredPose = Pose.identity;
            lastTimeSeconds = 0.0;
            linearVelocity = Vector3.zero;
            angularVelocityRad = Vector3.zero;
            latestScore = 1.0f;
            hasEstimate = false;
        }

        private void EnsureDefaults()
        {
            if (defaultsInitializedVersion != DefaultsVersion)
            {
                minCutoff = 1.0f;
                beta = 0.25f;
                derivativeCutoff = 1.0f;
                maxPredictAheadSeconds = SafeMaxPredictAheadSeconds;
                defaultsInitializedVersion = DefaultsVersion;
            }

            maxPredictAheadSeconds = Mathf.Clamp(maxPredictAheadSeconds, 0.0f, SafeMaxPredictAheadSeconds);
            if (positionFilter == null || rotationFilter == null)
            {
                positionFilter = new OneEuroVector3(minCutoff, beta, derivativeCutoff);
                rotationFilter = new OneEuroRotation(minCutoff, beta, derivativeCutoff);
            }
        }

        private float EffectiveMaxPredictAheadSeconds()
        {
            return Mathf.Clamp(maxPredictAheadSeconds, 0.0f, SafeMaxPredictAheadSeconds);
        }

        private static double MeasurementTime(in AnchorObservation observation)
        {
            return observation.HasCaptureTime ? observation.CaptureTimeSeconds : observation.SampleTimeSeconds;
        }

        /// <summary>
        /// 一维 One Euro 滤波器。
        /// </summary>
        private sealed class OneEuroFloat
        {
            private readonly float minCutoff;
            private readonly float beta;
            private readonly float derivativeCutoff;
            private bool hasValue;
            private float value;
            private float rawValue;
            private float derivative;
            private double lastTimeSeconds;

            /// <summary>构造一维 One Euro 滤波器。</summary>
            public OneEuroFloat(float minCutoff = 1.0f, float beta = 0.0f, float derivativeCutoff = 1.0f)
            {
                this.minCutoff = Mathf.Max(minCutoff, 1e-4f);
                this.beta = Mathf.Max(beta, 0.0f);
                this.derivativeCutoff = Mathf.Max(derivativeCutoff, 1e-4f);
            }

            /// <summary>当前滤波值。</summary>
            public float Value => value;

            /// <summary>是否已有滤波值。</summary>
            public bool HasValue => hasValue;

            /// <summary>清空滤波状态。</summary>
            public void Reset()
            {
                hasValue = false;
                value = 0.0f;
                rawValue = 0.0f;
                derivative = 0.0f;
                lastTimeSeconds = 0.0;
            }

            /// <summary>直接贴合到初始值。</summary>
            public float Snap(float nextValue, double timeSeconds)
            {
                hasValue = true;
                value = nextValue;
                rawValue = nextValue;
                derivative = 0.0f;
                lastTimeSeconds = timeSeconds;
                return value;
            }

            /// <summary>用新测量更新滤波值。</summary>
            public float Update(float nextValue, double timeSeconds)
            {
                if (!hasValue)
                {
                    return Snap(nextValue, timeSeconds);
                }

                float dt = Mathf.Max((float)(timeSeconds - lastTimeSeconds), 1e-5f);
                float rawDerivative = (nextValue - rawValue) / dt;
                derivative = Lerp(derivative, rawDerivative, Alpha(dt, derivativeCutoff));
                float cutoff = minCutoff + beta * Mathf.Abs(derivative);
                value = Lerp(value, nextValue, Alpha(dt, cutoff));
                rawValue = nextValue;
                lastTimeSeconds = timeSeconds;
                return value;
            }

            private static float Alpha(float dt, float cutoff)
            {
                float tau = 1.0f / (2.0f * Mathf.PI * Mathf.Max(cutoff, 1e-4f));
                return 1.0f / (1.0f + tau / Mathf.Max(dt, 1e-5f));
            }

            private static float Lerp(float a, float b, float t)
            {
                return a + (b - a) * Mathf.Clamp01(t);
            }
        }

        /// <summary>
        /// Vector3 One Euro 滤波器。
        /// </summary>
        private sealed class OneEuroVector3
        {
            private readonly OneEuroFloat x;
            private readonly OneEuroFloat y;
            private readonly OneEuroFloat z;

            /// <summary>构造 Vector3 One Euro 滤波器。</summary>
            public OneEuroVector3(float minCutoff = 1.0f, float beta = 0.0f, float derivativeCutoff = 1.0f)
            {
                x = new OneEuroFloat(minCutoff, beta, derivativeCutoff);
                y = new OneEuroFloat(minCutoff, beta, derivativeCutoff);
                z = new OneEuroFloat(minCutoff, beta, derivativeCutoff);
            }

            /// <summary>是否已有滤波值。</summary>
            public bool HasValue => x.HasValue && y.HasValue && z.HasValue;

            /// <summary>当前滤波值。</summary>
            public Vector3 Value => new Vector3(x.Value, y.Value, z.Value);

            /// <summary>清空滤波状态。</summary>
            public void Reset()
            {
                x.Reset();
                y.Reset();
                z.Reset();
            }

            /// <summary>直接贴合到初始值。</summary>
            public Vector3 Snap(Vector3 value, double timeSeconds)
            {
                return new Vector3(
                    x.Snap(value.x, timeSeconds),
                    y.Snap(value.y, timeSeconds),
                    z.Snap(value.z, timeSeconds)
                );
            }

            /// <summary>用新测量更新滤波值。</summary>
            public Vector3 Update(Vector3 value, double timeSeconds)
            {
                return new Vector3(
                    x.Update(value.x, timeSeconds),
                    y.Update(value.y, timeSeconds),
                    z.Update(value.z, timeSeconds)
                );
            }
        }

        /// <summary>
        /// 四元数 One Euro 滤波器，在切空间中过滤旋转误差。
        /// </summary>
        private sealed class OneEuroRotation
        {
            private readonly OneEuroVector3 derivativeFilter;
            private readonly float minCutoff;
            private readonly float beta;
            private bool hasValue;
            private Quaternion value = Quaternion.identity;
            private Quaternion rawValue = Quaternion.identity;
            private double lastTimeSeconds;

            /// <summary>构造四元数 One Euro 滤波器。</summary>
            public OneEuroRotation(float minCutoff = 1.0f, float beta = 0.0f, float derivativeCutoff = 1.0f)
            {
                this.minCutoff = Mathf.Max(minCutoff, 1e-4f);
                this.beta = Mathf.Max(beta, 0.0f);
                derivativeFilter = new OneEuroVector3(derivativeCutoff, 0.0f, derivativeCutoff);
            }

            /// <summary>是否已有滤波值。</summary>
            public bool HasValue => hasValue;

            /// <summary>当前滤波旋转。</summary>
            public Quaternion Value => value;

            /// <summary>清空滤波状态。</summary>
            public void Reset()
            {
                hasValue = false;
                value = Quaternion.identity;
                rawValue = Quaternion.identity;
                lastTimeSeconds = 0.0;
                derivativeFilter.Reset();
            }

            /// <summary>直接贴合到初始旋转。</summary>
            public Quaternion Snap(Quaternion rotation, double timeSeconds)
            {
                value = AnchorMath.Normalize(rotation);
                rawValue = value;
                lastTimeSeconds = timeSeconds;
                hasValue = true;
                derivativeFilter.Reset();
                return value;
            }

            /// <summary>用新测量更新滤波旋转。</summary>
            public Quaternion Update(Quaternion rotation, double timeSeconds)
            {
                Quaternion target = AnchorMath.Normalize(rotation);
                if (!hasValue)
                {
                    return Snap(target, timeSeconds);
                }

                float dt = Mathf.Max((float)(timeSeconds - lastTimeSeconds), 1e-5f);
                Quaternion alignedRaw = AnchorMath.AlignHemisphere(rawValue, target);
                Vector3 rawVelocity = AnchorMath.Log(AnchorMath.Multiply(AnchorMath.Inverse(rawValue), alignedRaw)) / dt;
                Vector3 filteredVelocity = derivativeFilter.Update(rawVelocity, timeSeconds);
                float cutoff = minCutoff + beta * filteredVelocity.magnitude;
                float alpha = Alpha(dt, cutoff);
                Quaternion alignedTarget = AnchorMath.AlignHemisphere(value, target);
                Vector3 delta = AnchorMath.Log(AnchorMath.Multiply(AnchorMath.Inverse(value), alignedTarget));
                value = AnchorMath.Multiply(value, AnchorMath.Exp(delta * alpha));
                rawValue = alignedRaw;
                lastTimeSeconds = timeSeconds;
                return value;
            }

            private static float Alpha(float dt, float cutoff)
            {
                float tau = 1.0f / (2.0f * Mathf.PI * Mathf.Max(cutoff, 1e-4f));
                return 1.0f / (1.0f + tau / Mathf.Max(dt, 1e-5f));
            }
        }
    }
}

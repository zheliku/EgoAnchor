using EgoAnchor.Tools2.Data;
using EgoAnchor.Tools2.Math;
using EgoAnchor.Tools2.Sim;

namespace EgoAnchor.Tools2.Predictors
{
    /// <summary>
    /// One Euro Filter + 预测模型预测器:经典自适应低通 + 短窗口外推。
    ///
    /// 实现逻辑 (完全复刻 Unity 侧 OneEuroEstimatorModule):
    /// - 位置:三个独立一维 One Euro 滤波器 (x/y/z)。
    /// - 旋转:切空间 One Euro,在当前滤波值与测量之间按角轴误差做指数低通。
    /// - 速度:从滤波后状态差分得到 (不是从原始测量)。
    /// - PredictAt(renderTime):用滤波状态 + 估计速度积分到 render 时间,
    ///   ahead 硬上限 0.12s (One Euro 只做短补帧,避免长预测漂移)。
    ///
    /// One Euro 核心:截止频率 cutoff = minCutoff + beta * |速度|,静止时低频 (平滑),
    /// 快速运动时高频 (跟手),自适应兼顾平滑与低延迟。
    /// baseline 固定参数,不读 score。
    /// </summary>
    public sealed class OneEuroPredictor : IAnchorPredictor
    {
        private const float SafeMaxPredictAheadSeconds = 0.12f;

        /// <summary>最低截止频率,单位 Hz。</summary>
        private const float MinCutoff = 1.0f;

        /// <summary>速度自适应系数。</summary>
        private const float Beta = 0.25f;

        /// <summary>导数低通截止频率,单位 Hz。</summary>
        private const float DerivativeCutoff = 1.0f;

        private readonly OneEuroVec3 positionFilter = new OneEuroVec3(MinCutoff, Beta, DerivativeCutoff);
        private readonly OneEuroRotation rotationFilter = new OneEuroRotation(MinCutoff, Beta, DerivativeCutoff);

        private Vec3 filteredPos = Vec3.Zero;
        private QuaternionM filteredRot = QuaternionM.Identity;
        private Vec3 prevFilteredPos = Vec3.Zero;
        private QuaternionM prevFilteredRot = QuaternionM.Identity;
        private double lastTimeSeconds;
        private Vec3 linearVelocity = Vec3.Zero;
        private Vec3 angularVelocityRad = Vec3.Zero;
        private bool hasEstimate;

        /// <summary>算法标签。</summary>
        public string Label => "oneeuro_predict";

        /// <summary>是否已积累至少一个观测。</summary>
        public bool HasEstimate => hasEstimate;

        /// <summary>清空状态。</summary>
        public void Reset()
        {
            positionFilter.Reset();
            rotationFilter.Reset();
            filteredPos = Vec3.Zero;
            filteredRot = QuaternionM.Identity;
            prevFilteredPos = Vec3.Zero;
            prevFilteredRot = QuaternionM.Identity;
            lastTimeSeconds = 0.0;
            linearVelocity = Vec3.Zero;
            angularVelocityRad = Vec3.Zero;
            hasEstimate = false;
        }

        /// <summary>提交观测:首帧 Snap,后续 One Euro 更新 + 速度差分。</summary>
        public void SubmitObservation(in PoseObservation observation)
        {
            double time = observation.CaptureTimeSeconds;
            if (!hasEstimate)
            {
                filteredPos = positionFilter.Snap(observation.Position, time);
                filteredRot = rotationFilter.Snap(observation.Rotation, time);
                prevFilteredPos = filteredPos;
                prevFilteredRot = filteredRot;
                lastTimeSeconds = time;
                linearVelocity = Vec3.Zero;
                angularVelocityRad = Vec3.Zero;
                hasEstimate = true;
                return;
            }

            float dt = AnchorMath.Max((float)(time - lastTimeSeconds), 1e-5f);
            prevFilteredPos = filteredPos;
            prevFilteredRot = filteredRot;
            filteredPos = positionFilter.Update(observation.Position, time);
            filteredRot = rotationFilter.Update(observation.Rotation, time);
            linearVelocity = (filteredPos - prevFilteredPos) / dt;
            angularVelocityRad = AnchorMath.AngularVelocity(prevFilteredRot, filteredRot, dt);
            lastTimeSeconds = time;
        }

        /// <summary>预测到 render 时间:滤波状态 + 速度积分,短窗口。</summary>
        public (Vec3 position, QuaternionM rotation) PredictAt(double renderTimeSeconds)
        {
            float ahead = hasEstimate
                ? AnchorMath.Clamp((float)(renderTimeSeconds - lastTimeSeconds), 0.0f, SafeMaxPredictAheadSeconds)
                : 0.0f;
            return AnchorMath.Integrate(filteredPos, filteredRot, linearVelocity, angularVelocityRad, ahead);
        }

        /// <summary>一维 One Euro 滤波器。</summary>
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

            public OneEuroFloat(float minCutoff, float beta, float derivativeCutoff)
            {
                this.minCutoff = AnchorMath.Max(minCutoff, 1e-4f);
                this.beta = AnchorMath.Max(beta, 0.0f);
                this.derivativeCutoff = AnchorMath.Max(derivativeCutoff, 1e-4f);
            }

            public float Snap(float nextValue, double timeSeconds)
            {
                hasValue = true;
                value = nextValue;
                rawValue = nextValue;
                derivative = 0.0f;
                lastTimeSeconds = timeSeconds;
                return value;
            }

            public void Reset()
            {
                hasValue = false;
                value = 0.0f;
                rawValue = 0.0f;
                derivative = 0.0f;
                lastTimeSeconds = 0.0;
            }

            public float Update(float nextValue, double timeSeconds)
            {
                if (!hasValue)
                {
                    return Snap(nextValue, timeSeconds);
                }

                float dt = AnchorMath.Max((float)(timeSeconds - lastTimeSeconds), 1e-5f);
                float rawDerivative = (nextValue - rawValue) / dt;
                derivative = Lerp(derivative, rawDerivative, Alpha(dt, derivativeCutoff));
                float cutoff = minCutoff + beta * Abs(derivative);
                value = Lerp(value, nextValue, Alpha(dt, cutoff));
                rawValue = nextValue;
                lastTimeSeconds = timeSeconds;
                return value;
            }

            private static float Alpha(float dt, float cutoff)
            {
                float tau = 1.0f / (2.0f * AnchorMath.PI * AnchorMath.Max(cutoff, 1e-4f));
                return 1.0f / (1.0f + tau / AnchorMath.Max(dt, 1e-5f));
            }

            private static float Lerp(float a, float b, float t) => a + (b - a) * AnchorMath.Clamp01(t);
            private static float Abs(float v) => v < 0f ? -v : v;
        }

        /// <summary>三维 One Euro 滤波器。</summary>
        private sealed class OneEuroVec3
        {
            private readonly OneEuroFloat x, y, z;

            public OneEuroVec3(float minCutoff, float beta, float derivativeCutoff)
            {
                x = new OneEuroFloat(minCutoff, beta, derivativeCutoff);
                y = new OneEuroFloat(minCutoff, beta, derivativeCutoff);
                z = new OneEuroFloat(minCutoff, beta, derivativeCutoff);
            }

            public void Reset() { x.Reset(); y.Reset(); z.Reset(); }

            public Vec3 Snap(Vec3 v, double t) => new Vec3(x.Snap(v.X, t), y.Snap(v.Y, t), z.Snap(v.Z, t));

            public Vec3 Update(Vec3 v, double t) => new Vec3(x.Update(v.X, t), y.Update(v.Y, t), z.Update(v.Z, t));
        }

        /// <summary>四元数 One Euro 滤波器 (切空间)。</summary>
        private sealed class OneEuroRotation
        {
            private readonly OneEuroVec3 derivativeFilter;
            private readonly float minCutoff;
            private readonly float beta;
            private bool hasValue;
            private QuaternionM value = QuaternionM.Identity;
            private QuaternionM rawValue = QuaternionM.Identity;
            private double lastTimeSeconds;

            public OneEuroRotation(float minCutoff, float beta, float derivativeCutoff)
            {
                this.minCutoff = AnchorMath.Max(minCutoff, 1e-4f);
                this.beta = AnchorMath.Max(beta, 0.0f);
                derivativeFilter = new OneEuroVec3(derivativeCutoff, 0.0f, derivativeCutoff);
            }

            public void Reset()
            {
                hasValue = false;
                value = QuaternionM.Identity;
                rawValue = QuaternionM.Identity;
                lastTimeSeconds = 0.0;
                derivativeFilter.Reset();
            }

            public QuaternionM Snap(QuaternionM rotation, double timeSeconds)
            {
                value = AnchorMath.Normalize(rotation);
                rawValue = value;
                lastTimeSeconds = timeSeconds;
                hasValue = true;
                derivativeFilter.Reset();
                return value;
            }

            public QuaternionM Update(QuaternionM rotation, double timeSeconds)
            {
                QuaternionM target = AnchorMath.Normalize(rotation);
                if (!hasValue)
                {
                    return Snap(target, timeSeconds);
                }

                float dt = AnchorMath.Max((float)(timeSeconds - lastTimeSeconds), 1e-5f);
                QuaternionM alignedRaw = AnchorMath.AlignHemisphere(rawValue, target);
                Vec3 rawVelocity = AnchorMath.Log(AnchorMath.Multiply(AnchorMath.Inverse(rawValue), alignedRaw)) / dt;
                Vec3 filteredVelocity = derivativeFilter.Update(rawVelocity, timeSeconds);
                float cutoff = minCutoff + beta * filteredVelocity.Magnitude;
                float alpha = Alpha(dt, cutoff);
                QuaternionM alignedTarget = AnchorMath.AlignHemisphere(value, target);
                Vec3 delta = AnchorMath.Log(AnchorMath.Multiply(AnchorMath.Inverse(value), alignedTarget));
                value = AnchorMath.Multiply(value, AnchorMath.Exp(delta * alpha));
                rawValue = alignedRaw;
                lastTimeSeconds = timeSeconds;
                return value;
            }

            private static float Alpha(float dt, float cutoff)
            {
                float tau = 1.0f / (2.0f * AnchorMath.PI * AnchorMath.Max(cutoff, 1e-4f));
                return 1.0f / (1.0f + tau / AnchorMath.Max(dt, 1e-5f));
            }
        }
    }
}

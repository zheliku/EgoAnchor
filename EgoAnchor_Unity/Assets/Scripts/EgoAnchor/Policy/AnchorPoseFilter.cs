using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// 滤波器对外的输出预测模式。
    /// </summary>
    public enum AnchorPredictMode
    {
        /// <summary>保持提交位姿，不做任何外推。</summary>
        Hold,

        /// <summary>跟踪外推：常速度前推到目标时刻，地平线被 maxPredictAheadSeconds 截断；静止模式下退化为保持。</summary>
        Track,

        /// <summary>续航外推：速度按时间常数指数阻尼，位移有界，用于测量缺失的 Coasting 段。</summary>
        Coast,
    }

    /// <summary>
    /// 一次测量相对滤波器预测的 innovation 统计，供门控与运动分类消费。
    /// </summary>
    public readonly struct InnovationStats
    {
        /// <summary>位置 innovation 马氏距离平方（3 自由度）。</summary>
        public readonly float PosD2;

        /// <summary>旋转 innovation 马氏距离平方。</summary>
        public readonly float RotD2;

        /// <summary>测量与预测的位置差模长，单位米。</summary>
        public readonly float TranslationMeters;

        /// <summary>测量与预测的旋转差，单位度。</summary>
        public readonly float RotationDegrees;

        /// <summary>构造 innovation 统计。</summary>
        public InnovationStats(float posD2, float rotD2, float translationMeters, float rotationDegrees)
        {
            PosD2 = posD2;
            RotD2 = rotD2;
            TranslationMeters = translationMeters;
            RotationDegrees = rotationDegrees;
        }
    }

    /// <summary>
    /// 统一的可靠性/运动自适应 6DoF anchor 滤波器。
    ///
    /// 位置为 3 个独立的一维常速度 Kalman（数学形式与 AnchorKalmanPoseProcessor.AxisKalman 同型，
    /// 但为支持预览预测、ZUPT 与逐帧自适应噪声而独立实现）；旋转为误差态四元数 + 角速度，
    /// 协方差用标量近似。内部状态停留在最后一次测量的 capture 时刻（提交态），
    /// PredictAt 只做瞬态前推不提交，因此天然支持"测量在过去、输出在现在"的异步时间轴。
    /// 本类不依赖 UnityEngine 生命周期与 Time，全部时间显式传入，可被 smoke 工具直接驱动。
    /// </summary>
    public sealed class AnchorPoseFilter
    {
        /// <summary>当前参数包。</summary>
        private AnchorPolicyConfig config;

        /// <summary>x 轴常速度 Kalman 状态。</summary>
        private ScalarKalman2 xAxis;

        /// <summary>y 轴常速度 Kalman 状态。</summary>
        private ScalarKalman2 yAxis;

        /// <summary>z 轴常速度 Kalman 状态。</summary>
        private ScalarKalman2 zAxis;

        /// <summary>提交态朝向。</summary>
        private Quaternion orientation = Quaternion.identity;

        /// <summary>体角速度估计，单位 rad/s。</summary>
        private Vector3 angularVelocityRad;

        /// <summary>旋转误差协方差（标量近似），单位 rad^2。</summary>
        private float rotationVariance;

        /// <summary>提交态对应的时间，单位秒。</summary>
        private double stateTimeSeconds;

        /// <summary>是否已有提交态。</summary>
        private bool hasState;

        /// <summary>是否处于静止模式（ZUPT + 静止过程噪声）。</summary>
        private bool staticMode;

        /// <summary>
        /// 构造滤波器。
        /// </summary>
        /// <param name="config">参数包；为空时使用默认参数。</param>
        public AnchorPoseFilter(AnchorPolicyConfig config = null)
        {
            this.config = config ?? new AnchorPolicyConfig();
        }

        /// <summary>是否已有提交态。</summary>
        public bool HasState => hasState;

        /// <summary>提交态时间，单位秒。</summary>
        public double StateTimeSeconds => stateTimeSeconds;

        /// <summary>提交态位置。</summary>
        public Vector3 Position => new Vector3(xAxis.Position, yAxis.Position, zAxis.Position);

        /// <summary>提交态朝向。</summary>
        public Quaternion Orientation => orientation;

        /// <summary>估计线速度，单位米/秒。</summary>
        public Vector3 Velocity => new Vector3(xAxis.Velocity, yAxis.Velocity, zAxis.Velocity);

        /// <summary>估计角速度，单位 rad/s。</summary>
        public Vector3 AngularVelocityRad => angularVelocityRad;

        /// <summary>估计角速度模长，单位度/秒。</summary>
        public float AngularSpeedDps => angularVelocityRad.magnitude * Mathf.Rad2Deg;

        /// <summary>三轴位置协方差均值，单位 m^2。</summary>
        public float PositionVariance => (xAxis.P00 + yAxis.P00 + zAxis.P00) / 3f;

        /// <summary>旋转误差协方差，单位 rad^2。</summary>
        public float RotationVariance => rotationVariance;

        /// <summary>是否处于静止模式。</summary>
        public bool StaticMode => staticMode;

        /// <summary>
        /// 热更参数包，不清空滤波状态。
        /// </summary>
        /// <param name="newConfig">新的参数包。</param>
        public void ApplyConfig(AnchorPolicyConfig newConfig)
        {
            if (newConfig != null)
            {
                config = newConfig;
            }
        }

        /// <summary>
        /// 清空全部滤波状态。
        /// </summary>
        public void Reset()
        {
            xAxis = default;
            yAxis = default;
            zAxis = default;
            orientation = Quaternion.identity;
            angularVelocityRad = Vector3.zero;
            rotationVariance = 0f;
            stateTimeSeconds = 0.0;
            hasState = false;
            staticMode = false;
        }

        /// <summary>
        /// 硬贴合到给定位姿：清空速度并把协方差重置到单次测量水平。
        /// 用于首测量、重定位与瞬移恢复。
        /// </summary>
        /// <param name="pose">目标 world pose。</param>
        /// <param name="timeSeconds">该位姿对应的 capture 时间，单位秒。</param>
        public void Snap(Pose pose, double timeSeconds)
        {
            xAxis = new ScalarKalman2(pose.position.x, config.positionMeasurementNoise);
            yAxis = new ScalarKalman2(pose.position.y, config.positionMeasurementNoise);
            zAxis = new ScalarKalman2(pose.position.z, config.positionMeasurementNoise);
            orientation = NormalizeQuaternion(pose.rotation);
            angularVelocityRad = Vector3.zero;
            rotationVariance = config.rotationMeasurementNoise;
            stateTimeSeconds = timeSeconds;
            hasState = true;
            staticMode = false;
        }

        /// <summary>
        /// 设置静止模式。静止时使用静止过程噪声，并在每次校正后清零速度（ZUPT），
        /// 让输出几乎不抖也不外推噪声。
        /// </summary>
        /// <param name="enabled">是否进入静止模式。</param>
        public void SetStaticMode(bool enabled)
        {
            staticMode = enabled;
        }

        /// <summary>
        /// 清零速度与角速度，用于超过续航上限后的冻结保持。
        /// </summary>
        public void DecayToHold()
        {
            xAxis.ZeroVelocity();
            yAxis.ZeroVelocity();
            zAxis.ZeroVelocity();
            angularVelocityRad = Vector3.zero;
        }

        /// <summary>
        /// 冻结提交：把当前 coast 外推位姿"封账"进提交态并清零速度，使冻结显示与
        /// 冻结前最后一帧外推输出连续（不回跳到旧提交位姿）；协方差按完整间隔增长，
        /// 让后续测量门随冻结时长自动变宽。速度清零后重复调用幂等。
        /// </summary>
        /// <param name="nowSeconds">当前时间，单位秒。</param>
        public void FreezeCoast(double nowSeconds)
        {
            if (!hasState)
            {
                return;
            }

            float gap = Mathf.Max((float)(nowSeconds - stateTimeSeconds), 0f);
            if (gap <= 0f)
            {
                DecayToHold();
                return;
            }

            float q = ProcessNoise();
            float hPos = CoastHorizon(gap, config.velocityDampingTauSeconds);
            float hRot = CoastHorizon(gap, config.angularVelocityDampingTau);

            xAxis.FreezeCoast(gap, hPos, q);
            yAxis.FreezeCoast(gap, hPos, q);
            zAxis.FreezeCoast(gap, hPos, q);
            orientation = NormalizeQuaternion(MultiplyQuaternion(orientation, QuaternionExp(angularVelocityRad * hRot)));
            rotationVariance += RotationProcessNoise() * gap;
            angularVelocityRad = Vector3.zero;
            stateTimeSeconds = nowSeconds;
        }

        /// <summary>
        /// 用一帧测量校正滤波器：先把提交态预测到测量时刻，再按给定测量噪声更新。
        /// </summary>
        /// <param name="measured">测量到的 world pose。</param>
        /// <param name="timeSeconds">该测量的 capture 时间，单位秒。</param>
        /// <param name="rPos">本帧位置测量噪声（已含可靠性/静止放大），单位 m^2。</param>
        /// <param name="rRot">本帧旋转测量噪声（已含可靠性/静止放大），单位 rad^2。</param>
        public void Correct(Pose measured, double timeSeconds, float rPos, float rRot)
        {
            if (!hasState)
            {
                Snap(measured, timeSeconds);
                return;
            }

            float dt = Mathf.Max((float)(timeSeconds - stateTimeSeconds), 1e-5f);
            float q = ProcessNoise();

            xAxis.Predict(dt, q);
            yAxis.Predict(dt, q);
            zAxis.Predict(dt, q);
            xAxis.Update(measured.position.x, Mathf.Max(rPos, 1e-9f));
            yAxis.Update(measured.position.y, Mathf.Max(rPos, 1e-9f));
            zAxis.Update(measured.position.z, Mathf.Max(rPos, 1e-9f));

            // 旋转 predict：按角速度积分朝向，协方差线性增长，角速度持续阻尼。
            orientation = NormalizeQuaternion(MultiplyQuaternion(orientation, QuaternionExp(angularVelocityRad * dt)));
            rotationVariance += RotationProcessNoise() * dt;
            angularVelocityRad *= Mathf.Exp(-dt / Mathf.Max(config.angularVelocityDampingTau, 1e-3f));

            // 旋转 update：误差向量 θ = Log(q_pred^-1 ⊗ q_meas)，标量增益校正朝向与角速度。
            Quaternion measuredRotation = AlignSign(orientation, NormalizeQuaternion(measured.rotation));
            Vector3 theta = QuaternionLog(MultiplyQuaternion(ConjugateQuaternion(orientation), measuredRotation));
            float k = rotationVariance / Mathf.Max(rotationVariance + Mathf.Max(rRot, 1e-9f), 1e-12f);
            orientation = NormalizeQuaternion(MultiplyQuaternion(orientation, QuaternionExp(theta * k)));

            float maxOmegaRad = config.angularVelocityMaxDps * Mathf.Deg2Rad;
            Vector3 omegaCorrection = theta * (config.angularVelocityGainBeta * k / Mathf.Max(dt, 1e-3f));
            angularVelocityRad += ClampMagnitude(omegaCorrection, maxOmegaRad);
            angularVelocityRad = ClampMagnitude(angularVelocityRad, maxOmegaRad);
            rotationVariance *= 1f - k;

            if (staticMode)
            {
                // ZUPT：静止时不让噪声积累成速度，协方差速度项也被压住。
                xAxis.ApplyZupt(q);
                yAxis.ApplyZupt(q);
                zAxis.ApplyZupt(q);
                angularVelocityRad = Vector3.zero;
            }

            stateTimeSeconds = timeSeconds;
        }

        /// <summary>
        /// 计算一帧测量相对当前预测的 innovation 统计，不改变滤波状态。
        /// 均值与协方差都按完整间隔做常速度预测，与 Correct 内部的 predict 一致；
        /// 间隔越久协方差越大，跳变门自动变宽，长间隙后的重获自然顺滑。
        /// </summary>
        /// <param name="measured">测量到的 world pose。</param>
        /// <param name="timeSeconds">该测量的 capture 时间，单位秒。</param>
        /// <param name="rPos">本帧位置测量噪声，单位 m^2。</param>
        /// <param name="rRot">本帧旋转测量噪声，单位 rad^2。</param>
        /// <returns>innovation 统计；无提交态时返回全零。</returns>
        public InnovationStats EvaluateInnovation(Pose measured, double timeSeconds, float rPos, float rRot)
        {
            if (!hasState)
            {
                return new InnovationStats(0f, 0f, 0f, 0f);
            }

            float dt = Mathf.Max((float)(timeSeconds - stateTimeSeconds), 0f);
            float q = ProcessNoise();

            float posD2 = 0f;
            float translationSq = 0f;
            AccumulateAxisInnovation(in xAxis, measured.position.x, dt, q, rPos, ref posD2, ref translationSq);
            AccumulateAxisInnovation(in yAxis, measured.position.y, dt, q, rPos, ref posD2, ref translationSq);
            AccumulateAxisInnovation(in zAxis, measured.position.z, dt, q, rPos, ref posD2, ref translationSq);

            Quaternion predicted = NormalizeQuaternion(MultiplyQuaternion(orientation, QuaternionExp(angularVelocityRad * dt)));
            Quaternion measuredRotation = AlignSign(predicted, NormalizeQuaternion(measured.rotation));
            Vector3 theta = QuaternionLog(MultiplyQuaternion(ConjugateQuaternion(predicted), measuredRotation));
            float predictedRotVariance = rotationVariance + RotationProcessNoise() * dt;
            float rotD2 = theta.sqrMagnitude / Mathf.Max(predictedRotVariance + Mathf.Max(rRot, 1e-9f), 1e-12f);

            return new InnovationStats(
                posD2,
                rotD2,
                Mathf.Sqrt(translationSq),
                theta.magnitude * Mathf.Rad2Deg
            );
        }

        /// <summary>
        /// 按指定模式把提交态预测到目标时刻，只读不提交。
        /// </summary>
        /// <param name="timeSeconds">目标时间（通常为渲染时刻），单位秒。</param>
        /// <param name="mode">预测模式。</param>
        /// <returns>预测出的 world pose；无提交态时返回 identity。</returns>
        public Pose PredictAt(double timeSeconds, AnchorPredictMode mode)
        {
            if (!hasState)
            {
                return Pose.identity;
            }

            float gap = Mathf.Max((float)(timeSeconds - stateTimeSeconds), 0f);
            float hPos;
            float hRot;
            switch (mode)
            {
                case AnchorPredictMode.Track when !staticMode:
                    hPos = Mathf.Min(gap, config.maxPredictAheadSeconds);
                    hRot = hPos;
                    break;
                case AnchorPredictMode.Coast:
                    hPos = CoastHorizon(gap, config.velocityDampingTauSeconds);
                    hRot = CoastHorizon(gap, config.angularVelocityDampingTau);
                    break;
                default:
                    hPos = 0f;
                    hRot = 0f;
                    break;
            }

            Vector3 position = Position + Velocity * hPos;
            Quaternion rotation = hRot > 0f
                ? NormalizeQuaternion(MultiplyQuaternion(orientation, QuaternionExp(angularVelocityRad * hRot)))
                : orientation;
            return new Pose(position, rotation);
        }

        /// <summary>
        /// 按当前运动模式取位置过程噪声。
        /// </summary>
        private float ProcessNoise()
        {
            return staticMode ? config.processNoiseStatic : config.processNoiseMoving;
        }

        /// <summary>
        /// 按当前运动模式取旋转过程噪声。
        /// </summary>
        private float RotationProcessNoise()
        {
            return staticMode ? config.rotationProcessNoiseStatic : config.rotationProcessNoise;
        }

        /// <summary>
        /// 累加单轴位置 innovation 的马氏距离平方与平移平方。
        /// </summary>
        private static void AccumulateAxisInnovation(
            in ScalarKalman2 axis,
            float measurement,
            float dt,
            float q,
            float rPos,
            ref float posD2,
            ref float translationSq)
        {
            float predictedPosition = axis.Position + axis.Velocity * dt;
            float predictedP00 = axis.PreviewP00(dt, q);
            float innovation = measurement - predictedPosition;
            posD2 += innovation * innovation / Mathf.Max(predictedP00 + Mathf.Max(rPos, 1e-9f), 1e-12f);
            translationSq += innovation * innovation;
        }

        /// <summary>
        /// Coasting 外推的有效时长：前 maxPredictAheadSeconds 段保持线性（与跟踪态前推连续），
        /// 之后按时间常数指数阻尼，总外推时长有界于 maxPredictAhead + tau。
        /// </summary>
        private float CoastHorizon(float gap, float tauSeconds)
        {
            float linear = Mathf.Min(gap, config.maxPredictAheadSeconds);
            float excess = Mathf.Max(gap - config.maxPredictAheadSeconds, 0f);
            if (tauSeconds <= 0f)
            {
                return gap;
            }

            return linear + tauSeconds * (1f - Mathf.Exp(-excess / tauSeconds));
        }

        /// <summary>
        /// 限制向量模长。
        /// </summary>
        private static Vector3 ClampMagnitude(Vector3 value, float maxMagnitude)
        {
            float sqr = value.sqrMagnitude;
            if (sqr <= maxMagnitude * maxMagnitude || sqr <= 1e-20f)
            {
                return value;
            }

            return value * (maxMagnitude / Mathf.Sqrt(sqr));
        }

        /// <summary>
        /// 保证测量四元数与参考在同一半球，取最短弧误差。
        /// </summary>
        private static Quaternion AlignSign(Quaternion reference, Quaternion value)
        {
            float dot = reference.x * value.x + reference.y * value.y + reference.z * value.z + reference.w * value.w;
            if (dot < 0f)
            {
                return new Quaternion(-value.x, -value.y, -value.z, -value.w);
            }

            return value;
        }

        /// <summary>
        /// 四元数乘法（不依赖引擎原生调用，保证 smoke 离线环境可用）。
        /// </summary>
        private static Quaternion MultiplyQuaternion(Quaternion a, Quaternion b)
        {
            return new Quaternion(
                a.w * b.x + a.x * b.w + a.y * b.z - a.z * b.y,
                a.w * b.y - a.x * b.z + a.y * b.w + a.z * b.x,
                a.w * b.z + a.x * b.y - a.y * b.x + a.z * b.w,
                a.w * b.w - a.x * b.x - a.y * b.y - a.z * b.z
            );
        }

        /// <summary>
        /// 单位四元数共轭（即逆）。
        /// </summary>
        private static Quaternion ConjugateQuaternion(Quaternion q)
        {
            return new Quaternion(-q.x, -q.y, -q.z, q.w);
        }

        /// <summary>
        /// 四元数归一化；模长过小时回退 identity。
        /// </summary>
        private static Quaternion NormalizeQuaternion(Quaternion q)
        {
            float norm = Mathf.Sqrt(q.x * q.x + q.y * q.y + q.z * q.z + q.w * q.w);
            if (norm <= 1e-12f)
            {
                return Quaternion.identity;
            }

            float inv = 1f / norm;
            return new Quaternion(q.x * inv, q.y * inv, q.z * inv, q.w * inv);
        }

        /// <summary>
        /// 旋转向量 -> 四元数（Exp 映射）。输入为完整角的轴角向量，单位 rad。
        /// </summary>
        private static Quaternion QuaternionExp(Vector3 rotationVector)
        {
            float angle = rotationVector.magnitude;
            if (angle < 1e-8f)
            {
                // 小角度一阶近似，避免除零。
                return NormalizeQuaternion(new Quaternion(
                    rotationVector.x * 0.5f,
                    rotationVector.y * 0.5f,
                    rotationVector.z * 0.5f,
                    1f
                ));
            }

            float half = angle * 0.5f;
            float scale = Mathf.Sin(half) / angle;
            return new Quaternion(
                rotationVector.x * scale,
                rotationVector.y * scale,
                rotationVector.z * scale,
                Mathf.Cos(half)
            );
        }

        /// <summary>
        /// 四元数 -> 旋转向量（Log 映射）。调用方需保证 w >= 0（最短弧）。
        /// </summary>
        private static Vector3 QuaternionLog(Quaternion q)
        {
            Vector3 vector = new Vector3(q.x, q.y, q.z);
            float sinHalf = vector.magnitude;
            if (sinHalf < 1e-8f)
            {
                // 接近零旋转时 sin(θ/2) ≈ θ/2。
                return vector * 2f;
            }

            float half = Mathf.Atan2(sinHalf, q.w);
            return vector * (2f * half / sinHalf);
        }

        /// <summary>
        /// 单轴常速度 Kalman。状态为 [position, velocity]，测量为 position。
        /// 与 AnchorKalmanPoseProcessor.AxisKalman 数学同型，但拆分 predict/update、
        /// 提供协方差预览与 ZUPT，供统一滤波器按异步时间轴驱动。
        /// </summary>
        private struct ScalarKalman2
        {
            /// <summary>当前估计位置。</summary>
            public float Position;

            /// <summary>当前估计速度。</summary>
            public float Velocity;

            /// <summary>协方差 P00（位置方差）。</summary>
            public float P00;

            /// <summary>协方差 P01。</summary>
            public float P01;

            /// <summary>协方差 P10。</summary>
            public float P10;

            /// <summary>协方差 P11（速度方差）。</summary>
            public float P11;

            /// <summary>
            /// 用初始位置构造：位置方差取单次测量噪声，速度未知取 1。
            /// </summary>
            /// <param name="initialPosition">初始位置。</param>
            /// <param name="measurementNoise">测量噪声基准，作为初始位置方差。</param>
            public ScalarKalman2(float initialPosition, float measurementNoise)
            {
                Position = initialPosition;
                Velocity = 0f;
                P00 = Mathf.Max(measurementNoise, 1e-9f);
                P01 = 0f;
                P10 = 0f;
                P11 = 1f;
            }

            /// <summary>
            /// 常速度 predict：x = F x，P = F P F^T + Q，F = [1 dt; 0 1]。
            /// </summary>
            /// <param name="dt">时间步长，单位秒。</param>
            /// <param name="processNoise">过程噪声。</param>
            public void Predict(float dt, float processNoise)
            {
                Position += Velocity * dt;
                float nextP00 = P00 + dt * (P10 + P01) + dt * dt * P11 + processNoise * dt;
                float nextP01 = P01 + dt * P11;
                float nextP10 = P10 + dt * P11;
                float nextP11 = P11 + processNoise * dt;
                P00 = nextP00;
                P01 = nextP01;
                P10 = nextP10;
                P11 = nextP11;
            }

            /// <summary>
            /// 位置测量 update：H = [1 0]。
            /// </summary>
            /// <param name="measurement">位置测量。</param>
            /// <param name="measurementNoise">测量噪声。</param>
            public void Update(float measurement, float measurementNoise)
            {
                float innovation = measurement - Position;
                float s = Mathf.Max(P00 + measurementNoise, 1e-12f);
                float k0 = P00 / s;
                float k1 = P10 / s;

                Position += k0 * innovation;
                Velocity += k1 * innovation;

                float nextP00 = (1f - k0) * P00;
                float nextP01 = (1f - k0) * P01;
                float nextP10 = P10 - k1 * P00;
                float nextP11 = P11 - k1 * P01;
                P00 = nextP00;
                P01 = nextP01;
                P10 = nextP10;
                P11 = nextP11;
            }

            /// <summary>
            /// 只读预览 predict 后的位置方差，不改变状态。
            /// </summary>
            /// <param name="dt">时间步长，单位秒。</param>
            /// <param name="processNoise">过程噪声。</param>
            /// <returns>预测后的 P00。</returns>
            public float PreviewP00(float dt, float processNoise)
            {
                return P00 + dt * (P10 + P01) + dt * dt * P11 + processNoise * dt;
            }

            /// <summary>
            /// 静止 ZUPT：强压速度、钳制速度方差并清零位置-速度交叉项。
            /// 交叉项必须随速度一起清零，否则强行改写速度后协方差失去正定性，
            /// 会在后续 update 中产生灾难性增益。
            /// </summary>
            /// <param name="processNoise">当前过程噪声，作为速度方差上限。</param>
            public void ApplyZupt(float processNoise)
            {
                Velocity *= 0.1f;
                P11 = Mathf.Min(P11, Mathf.Max(processNoise, 1e-9f));
                P01 = 0f;
                P10 = 0f;
            }

            /// <summary>
            /// 冻结提交：位置按阻尼外推时长前移后清零速度，协方差按完整间隔增长。
            /// </summary>
            /// <param name="fullGap">距上次提交的完整时长，单位秒。</param>
            /// <param name="dampedHorizon">阻尼后的有效外推时长，单位秒。</param>
            /// <param name="processNoise">过程噪声。</param>
            public void FreezeCoast(float fullGap, float dampedHorizon, float processNoise)
            {
                Position += Velocity * dampedHorizon;
                float nextP00 = P00 + fullGap * (P10 + P01) + fullGap * fullGap * P11 + processNoise * fullGap;
                float nextP11 = P11 + processNoise * fullGap;
                P00 = nextP00;
                P01 = 0f;
                P10 = 0f;
                P11 = nextP11;
                Velocity = 0f;
            }

            /// <summary>
            /// 清零速度，用于冻结保持。
            /// </summary>
            public void ZeroVelocity()
            {
                Velocity = 0f;
            }
        }
    }
}

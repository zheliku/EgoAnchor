using EgoAnchor.Tools2.Data;
using EgoAnchor.Tools2.Math;
using EgoAnchor.Tools2.Sim;

namespace EgoAnchor.Tools2.Predictors
{
    /// <summary>
    /// 常加速度 (Constant Acceleration) Kalman 预测器:论文级"卡尔曼滤波 + 预测插值"baseline。
    ///
    /// 实现逻辑:
    /// - 平移:x/y/z 三轴各跑一个 3 维 CA Kalman (状态 [pos, vel, acc])。
    /// - 旋转:维护一个参考四元数 q_ref,把测量旋转映射到切空间误差角轴 [θx,θy,θz],
    ///   再用三个 CA Kalman 分别滤波误差角轴及其角速度、角加速度。
    ///   当前姿态 = q_ref * Exp([θx,θy,θz])。
    /// - SubmitObservation:先 Predict 到测量时间 (predict 步),再用测量位置和切空间误差做 Correct。
    /// - PredictAt(renderTime):在状态上做二阶外推
    ///     pos = pos_i + vel_i*ahead + 0.5*acc_i*ahead^2
    ///     θ   = θ_i  + ω_i *ahead + 0.5*α_i *ahead^2
    ///     rot = q_ref * Exp(θ)
    ///   ahead 夹取到 [0, maxPredictAheadSeconds]。
    ///
    /// 旋转全程用切空间 Log/Exp (与 Unity 侧一致),不用 SLERP/Euler。
    /// </summary>
    public class KalmanCaPredictor : IAnchorPredictor
    {
        /// <summary>位置过程噪声强度,单位 m^2/s^3 (jerk 噪声驱动)。</summary>
        protected float PositionProcessNoise = 0.2f;

        /// <summary>位置测量噪声方差,单位 m^2。</summary>
        protected float PositionMeasurementNoise = 0.0004f;

        /// <summary>旋转过程噪声强度,单位 (rad^2)/s^3。</summary>
        protected float RotationProcessNoise = 0.4f;

        /// <summary>旋转测量噪声方差,单位 rad^2。</summary>
        protected float RotationMeasurementNoise = 0.0025f;

        /// <summary>允许预测到最近测量之后的最大时长,单位秒。</summary>
        protected float MaxPredictAheadSeconds = 0.18f;

        private ConstAccelerationKalman1d x, y, z;
        private ConstAccelerationKalman1d rx, ry, rz;
        private QuaternionM rotationReference = QuaternionM.Identity;
        private double lastTimeSeconds;
        private bool hasEstimate;

        /// <summary>算法标签。</summary>
        public virtual string Label => "kalman_ca";

        /// <summary>是否已积累至少一个观测。</summary>
        public bool HasEstimate => hasEstimate;

        /// <summary>清空状态。</summary>
        public virtual void Reset()
        {
            x.Clear(); y.Clear(); z.Clear();
            rx.Clear(); ry.Clear(); rz.Clear();
            rotationReference = QuaternionM.Identity;
            lastTimeSeconds = 0.0;
            hasEstimate = false;
        }

        /// <summary>提交观测:首帧 Snap (硬重置),后续预测+校正。</summary>
        public void SubmitObservation(in PoseObservation observation)
        {
            if (!hasEstimate)
            {
                Snap(observation);
                return;
            }

            double time = observation.CaptureTimeSeconds;
            PredictStateTo(time);

            // 位置校正
            float posR = ResolvePositionMeasurementNoise(observation);
            x.Correct(observation.Position.X, posR);
            y.Correct(observation.Position.Y, posR);
            z.Correct(observation.Position.Z, posR);

            // 旋转校正:把测量旋转映射到参考四元数切空间误差
            float rotR = ResolveRotationMeasurementNoise(observation);
            QuaternionM measured = AnchorMath.AlignHemisphere(CurrentRotation(), observation.Rotation);
            Vec3 measuredError = AnchorMath.Log(AnchorMath.Multiply(AnchorMath.Inverse(rotationReference), measured));
            rx.Correct(measuredError.X, rotR);
            ry.Correct(measuredError.Y, rotR);
            rz.Correct(measuredError.Z, rotR);

            OnAfterCorrect(observation);
        }

        /// <summary>预测到 render 时间,二阶外推。</summary>
        public (Vec3 position, QuaternionM rotation) PredictAt(double renderTimeSeconds)
        {
            if (!hasEstimate)
            {
                return (Vec3.Zero, QuaternionM.Identity);
            }

            float ahead = AnchorMath.Clamp((float)(renderTimeSeconds - lastTimeSeconds), 0.0f, MaxPredictAheadSeconds);
            float halfAhead2 = 0.5f * ahead * ahead;

            Vec3 position = new Vec3(
                x.Position + x.Velocity * ahead + x.Acceleration * halfAhead2,
                y.Position + y.Velocity * ahead + y.Acceleration * halfAhead2,
                z.Position + z.Velocity * ahead + z.Acceleration * halfAhead2);

            Vec3 rotVector = new Vec3(
                rx.Position + rx.Velocity * ahead + rx.Acceleration * halfAhead2,
                ry.Position + ry.Velocity * ahead + ry.Acceleration * halfAhead2,
                rz.Position + rz.Velocity * ahead + rz.Acceleration * halfAhead2);

            QuaternionM rotation = AnchorMath.Multiply(rotationReference, AnchorMath.Exp(rotVector));
            return (position, rotation);
        }

        /// <summary>
        /// 解算位置测量噪声;子类 (EgoAnchor 增强) 可按 score 调节。
        /// 默认 baseline 固定使用 PositionMeasurementNoise。
        /// </summary>
        protected virtual float ResolvePositionMeasurementNoise(in PoseObservation observation)
        {
            return PositionMeasurementNoise;
        }

        /// <summary>
        /// 解算旋转测量噪声;子类可按 score 调节。
        /// 默认 baseline 固定使用 RotationMeasurementNoise。
        /// </summary>
        protected virtual float ResolveRotationMeasurementNoise(in PoseObservation observation)
        {
            return RotationMeasurementNoise;
        }

        /// <summary>校正后的钩子;子类可在此做观测速度融合等增强。</summary>
        protected virtual void OnAfterCorrect(in PoseObservation observation)
        {
        }

        /// <summary>当前估计旋转 = 参考姿态 * Exp(误差态)。</summary>
        protected QuaternionM CurrentRotation()
        {
            return AnchorMath.Multiply(rotationReference, AnchorMath.Exp(new Vec3(rx.Position, ry.Position, rz.Position)));
        }

        /// <summary>把 6 个 Kalman 预测到指定测量时间。</summary>
        protected void PredictStateTo(double timeSeconds)
        {
            float dt = AnchorMath.Max((float)(timeSeconds - lastTimeSeconds), 0.0f);
            if (dt <= 0.0f)
            {
                lastTimeSeconds = timeSeconds;
                return;
            }

            x.Predict(dt, PositionProcessNoise);
            y.Predict(dt, PositionProcessNoise);
            z.Predict(dt, PositionProcessNoise);
            rx.Predict(dt, RotationProcessNoise);
            ry.Predict(dt, RotationProcessNoise);
            rz.Predict(dt, RotationProcessNoise);
            lastTimeSeconds = timeSeconds;
        }

        /// <summary>硬重置所有状态到该观测。</summary>
        protected void Snap(in PoseObservation observation)
        {
            Vec3 p = observation.Position;
            x.Reset(p.X, PositionMeasurementNoise);
            y.Reset(p.Y, PositionMeasurementNoise);
            z.Reset(p.Z, PositionMeasurementNoise);
            rotationReference = AnchorMath.Normalize(observation.Rotation);
            rx.Reset(0.0f, RotationMeasurementNoise);
            ry.Reset(0.0f, RotationMeasurementNoise);
            rz.Reset(0.0f, RotationMeasurementNoise);
            lastTimeSeconds = observation.CaptureTimeSeconds;
            hasEstimate = true;
        }
    }
}

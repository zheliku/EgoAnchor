using System.Globalization;
using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// One Euro 运动模型 (自适应低通去噪 + 平滑速度)。
    ///
    /// 位置 x/y/z 各一路标量 One Euro；旋转在最新平滑姿态的局部切空间里三路 One Euro。
    /// 提供平滑值 (当作去噪 pose) 和平滑速度 (当作外推切线)。
    /// 同样不限幅外推，平滑交给 SmoothingStrategy。
    /// </summary>
    public sealed class OneEuroModel : MotionModel
    {
        /// <summary>位置通道最小截止频率，单位 Hz。</summary>
        [Header("Position / 平移参数")]
        [Tooltip("位置通道最小截止频率 (Hz)；单位为米。默认 0.8。")]
        [SerializeField] private float positionMinCutoff = 0.8f;

        /// <summary>位置通道速度自适应系数，单位 Hz/(m/s)。</summary>
        [Tooltip("位置通道速度自适应系数 beta，单位 Hz/(m/s)。默认 6。")]
        [SerializeField] private float positionBeta = 6.0f;

        /// <summary>位置通道导数低通截止频率，单位 Hz。</summary>
        [Tooltip("位置通道导数低通截止频率 (Hz)。默认 2。")]
        [SerializeField] private float positionDerivativeCutoff = 2.0f;

        /// <summary>旋转通道最小截止频率，单位 Hz。</summary>
        [Header("Rotation / 旋转参数")]
        [Tooltip("旋转通道最小截止频率 (Hz)；角速度单位为弧度/秒。默认 1。")]
        [SerializeField] private float rotationMinCutoff = 1.0f;

        /// <summary>旋转通道速度自适应系数，单位 Hz/(rad/s)。</summary>
        [Tooltip("旋转通道速度自适应系数 beta，单位 Hz/(rad/s)。默认 1。")]
        [SerializeField] private float rotationBeta = 1.0f;

        /// <summary>旋转通道导数低通截止频率，单位 Hz。</summary>
        [Tooltip("旋转通道导数低通截止频率 (Hz)。默认 2。")]
        [SerializeField] private float rotationDerivativeCutoff = 2.0f;

        private ScalarOneEuro px;
        private ScalarOneEuro py;
        private ScalarOneEuro pz;
        private ScalarOneEuro rxFilter;
        private ScalarOneEuro ryFilter;
        private ScalarOneEuro rzFilter;
        private Quaternion rotationReference;
        private double lastTimeSeconds;
        private bool hasState;

        public override string ModelName => "oneeuro";
        public override string ConfigurationFingerprint => string.Format(
            CultureInfo.InvariantCulture,
            "pos:{0:R},{1:R},{2:R}|rot:{3:R},{4:R},{5:R}",
            positionMinCutoff,
            positionBeta,
            positionDerivativeCutoff,
            rotationMinCutoff,
            rotationBeta,
            rotationDerivativeCutoff);
        public override bool HasState => hasState;
        public override double LastObservationTimeSeconds => lastTimeSeconds;

        public override Vector3 LinearVelocity => new Vector3(px.Velocity, py.Velocity, pz.Velocity);

        public override Vector3 AngularVelocityRad => new Vector3(rxFilter.Velocity, ryFilter.Velocity, rzFilter.Velocity);

        public override ControlPoint LatestControlPoint
        {
            get
            {
                if (!hasState)
                {
                    return default;
                }

                return new ControlPoint(lastTimeSeconds, new Pose(CurrentPosition(), CurrentRotation()), LinearVelocity, AngularVelocityRad);
            }
        }

        public override void Snap(in AnchorObservation observation)
        {
            ConfigureFilters();
            Vector3 p = observation.WorldPose.position;
            double t = observation.MeasurementTimeSeconds;
            px.Snap(p.x, t);
            py.Snap(p.y, t);
            pz.Snap(p.z, t);
            rotationReference = AnchorMath.Normalize(observation.WorldPose.rotation);
            rxFilter.Snap(0.0f, t);
            ryFilter.Snap(0.0f, t);
            rzFilter.Snap(0.0f, t);
            lastTimeSeconds = t;
            hasState = true;
        }

        public override void UpdateState(in AnchorObservation observation)
        {
            if (!hasState)
            {
                Snap(observation);
                return;
            }

            Vector3 p = observation.WorldPose.position;
            double t = observation.MeasurementTimeSeconds;
            if (t <= lastTimeSeconds)
            {
                return;
            }
            px.Update(p.x, t);
            py.Update(p.y, t);
            pz.Update(p.z, t);

            Quaternion measured = AnchorMath.AlignHemisphere(rotationReference, observation.WorldPose.rotation);
            Vector3 err = AnchorMath.RelativeRotationLog(rotationReference, measured);
            rxFilter.Update(err.x, t);
            ryFilter.Update(err.y, t);
            rzFilter.Update(err.z, t);
            RecenterRotationState(measured);
            lastTimeSeconds = t;
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
            px.Reset();
            py.Reset();
            pz.Reset();
            rxFilter.Reset();
            ryFilter.Reset();
            rzFilter.Reset();
            rotationReference = Quaternion.identity;
            lastTimeSeconds = 0.0;
            hasState = false;
        }

        private void ConfigureFilters()
        {
            px.Configure(positionMinCutoff, positionBeta, positionDerivativeCutoff);
            py.Configure(positionMinCutoff, positionBeta, positionDerivativeCutoff);
            pz.Configure(positionMinCutoff, positionBeta, positionDerivativeCutoff);
            rxFilter.Configure(rotationMinCutoff, rotationBeta, rotationDerivativeCutoff);
            ryFilter.Configure(rotationMinCutoff, rotationBeta, rotationDerivativeCutoff);
            rzFilter.Configure(rotationMinCutoff, rotationBeta, rotationDerivativeCutoff);
        }

        private Vector3 CurrentPosition() => new Vector3(px.Value, py.Value, pz.Value);

        private Vector3 CurrentRotationVector() => new Vector3(rxFilter.Value, ryFilter.Value, rzFilter.Value);

        private Quaternion CurrentRotation()
        {
            return AnchorMath.Multiply(rotationReference, AnchorMath.Exp(CurrentRotationVector()));
        }

        /// <summary>
        /// 把平滑旋转吸收到参考姿态，并保留搬运后的 body-local 角速度与原始测量残差。
        /// 这样 One-Euro 预测与其他运动模型共享同一角速度坐标约定。
        /// </summary>
        /// <param name="measured">本次已经完成半球对齐的测量姿态。</param>
        private void RecenterRotationState(Quaternion measured)
        {
            Vector3 rotationVector = CurrentRotationVector();
            Quaternion rotationDelta = AnchorMath.Exp(rotationVector);
            Quaternion nextReference = AnchorMath.Multiply(rotationReference, rotationDelta);
            Vector3 rotationVectorRate = new Vector3(
                rxFilter.Velocity,
                ryFilter.Velocity,
                rzFilter.Velocity);
            Vector3 localVelocity = AnchorMath.ApplyRightJacobian(rotationVector, rotationVectorRate);
            Vector3 rawResidual = AnchorMath.RelativeRotationLog(nextReference, measured);

            rotationReference = nextReference;
            rxFilter.Rebase(0.0f, rawResidual.x, localVelocity.x);
            ryFilter.Rebase(0.0f, rawResidual.y, localVelocity.y);
            rzFilter.Rebase(0.0f, rawResidual.z, localVelocity.z);
        }
    }
}

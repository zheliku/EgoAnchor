using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// One Euro 运动模型 (自适应低通去噪 + 平滑速度)。
    ///
    /// 位置 x/y/z 各一路标量 One Euro；旋转在最新姿态参考的切空间里三路 One Euro。
    /// 提供平滑值 (当作去噪 pose) 和平滑速度 (当作外推切线)。
    /// 同样不限幅外推，平滑交给 SmoothingStrategy。
    /// </summary>
    public sealed class OneEuroModel : MotionModel
    {
        /// <summary>最小截止频率，单位 Hz；越小越平滑、滞后越大。</summary>
        [Tooltip("最小截止频率 (Hz)；越小越平滑、滞后越大。默认 1。")]
        [SerializeField] private float minCutoff = 1.0f;

        /// <summary>速度自适应系数 beta；越大快速运动时越跟手 (减滞后)。</summary>
        [Tooltip("速度自适应系数 beta；越大快速运动时越跟手、滞后越小。默认 0.25。")]
        [SerializeField] private float beta = 0.25f;

        /// <summary>导数 (速度) 低通截止频率，单位 Hz。</summary>
        [Tooltip("导数 (速度) 低通截止频率 (Hz)；一般保持 1。")]
        [SerializeField] private float derivativeCutoff = 1.0f;

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
            px.Update(p.x, t);
            py.Update(p.y, t);
            pz.Update(p.z, t);

            Quaternion measured = AnchorMath.AlignHemisphere(rotationReference, observation.WorldPose.rotation);
            Vector3 err = AnchorMath.RelativeRotationLog(rotationReference, measured);
            rxFilter.Update(err.x, t);
            ryFilter.Update(err.y, t);
            rzFilter.Update(err.z, t);
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
            Vector3 rotVec = CurrentRotationVector() + AngularVelocityRad * ahead;
            Quaternion rotation = AnchorMath.Multiply(rotationReference, AnchorMath.Exp(rotVec));
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
            px.Configure(minCutoff, beta, derivativeCutoff);
            py.Configure(minCutoff, beta, derivativeCutoff);
            pz.Configure(minCutoff, beta, derivativeCutoff);
            rxFilter.Configure(minCutoff, beta, derivativeCutoff);
            ryFilter.Configure(minCutoff, beta, derivativeCutoff);
            rzFilter.Configure(minCutoff, beta, derivativeCutoff);
        }

        private Vector3 CurrentPosition() => new Vector3(px.Value, py.Value, pz.Value);

        private Vector3 CurrentRotationVector() => new Vector3(rxFilter.Value, ryFilter.Value, rzFilter.Value);

        private Quaternion CurrentRotation()
        {
            return AnchorMath.Multiply(rotationReference, AnchorMath.Exp(CurrentRotationVector()));
        }
    }
}

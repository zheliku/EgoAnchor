using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// 匀速 (constant-velocity, CV) 运动模型。
    ///
    /// 用最近两帧观测差分估计线速度和角速度，不做去噪。外推：
    ///   pos = p_last + v*(t - t_last)；rot = q_last * Exp(omega*(t - t_last))。
    ///
    /// 它是最朴素的运动模型：控制点 = 原始观测 (不滤波)，速度 = 相邻观测差分。
    /// 配 B 路 = 朴素外推；配 C 路 = "原始点插值"。论文里作为不去噪的对照。
    /// 无额外参数。
    /// </summary>
    public sealed class ConstantVelocityModel : MotionModel
    {
        private bool hasState;
        private double lastTimeSeconds;
        private Pose lastPose;
        private Vector3 linVel;
        private Vector3 angVel;

        public override string ModelName => "cv";
        public override bool HasState => hasState;
        public override double LastObservationTimeSeconds => lastTimeSeconds;
        public override Vector3 LinearVelocity => linVel;
        public override Vector3 AngularVelocityRad => angVel;

        public override ControlPoint LatestControlPoint =>
            hasState ? new ControlPoint(lastTimeSeconds, lastPose, linVel, angVel) : default;

        public override void Snap(in AnchorObservation observation)
        {
            lastPose = observation.WorldPose;
            lastTimeSeconds = observation.MeasurementTimeSeconds;
            linVel = Vector3.zero;
            angVel = Vector3.zero;
            hasState = true;
        }

        public override void UpdateState(in AnchorObservation observation)
        {
            if (!hasState)
            {
                Snap(observation);
                return;
            }

            double t = observation.MeasurementTimeSeconds;
            float dt = Mathf.Max((float)(t - lastTimeSeconds), 1e-4f);
            Pose pose = observation.WorldPose;

            linVel = (pose.position - lastPose.position) / dt;
            angVel = AnchorMath.AngularVelocity(lastPose.rotation, pose.rotation, dt);

            lastPose = pose;
            lastTimeSeconds = t;
        }

        public override Pose PredictAt(double timeSeconds)
        {
            if (!hasState)
            {
                return Pose.identity;
            }

            float ahead = (float)(timeSeconds - lastTimeSeconds); // 不限幅
            return AnchorMath.Integrate(lastPose, linVel, angVel, ahead);
        }

        public override void ResetModel()
        {
            hasState = false;
            lastTimeSeconds = 0.0;
            lastPose = Pose.identity;
            linVel = Vector3.zero;
            angVel = Vector3.zero;
        }
    }
}

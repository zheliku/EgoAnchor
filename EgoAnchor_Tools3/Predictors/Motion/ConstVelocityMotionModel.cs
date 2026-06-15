using System;
using EgoAnchor.Tools3.Core;
using EgoAnchor.Tools3.Data;

namespace EgoAnchor.Tools3.Predictors.Motion
{
    /// <summary>
    /// 常速度 (constant-velocity) 运动模型, 最朴素的版本。
    ///
    /// 用最近两帧观测差分估计线速度和角速度 (角速度在最新观测姿态的切空间里), 不做去噪。
    /// 外推: pos = p_last + v*(t - t_last); rot = q_last * Exp(omega*(t - t_last))。
    ///
    /// 对应"DR 的速度估计方式", 是残差淡化管线里最简单的运动模型, 用来和 Kalman/OneEuro 对照——
    /// 看去噪到底带来多少提升。
    /// </summary>
    public sealed class ConstVelocityMotionModel : IMotionModel
    {
        private bool hasEstimate;
        private double lastTime;
        private Vec3 lastPos;
        private Quat lastRot = Quat.Identity;

        private Vec3 linVel;       // m/s
        private Vec3 angVel;       // 切空间半角向量速度 (rad/s 的一半口径, 与 Quat.Exp 配套)

        public string Name => "cv";

        public bool HasEstimate => hasEstimate;

        public double LastObservationTime => lastTime;

        public void Reset()
        {
            hasEstimate = false;
            lastRot = Quat.Identity;
            linVel = Vec3.Zero;
            angVel = Vec3.Zero;
        }

        public void OnObservation(in Observation observation)
        {
            Vec3 p = observation.Pose.Position;
            Quat q = observation.Pose.Rotation.Normalized();
            double t = observation.TimeSeconds;

            if (hasEstimate)
            {
                double dt = Math.Max(t - lastTime, 1e-4);
                linVel = (p - lastPos) / dt;

                // 角速度: 上一帧姿态相对当前姿态的切空间偏移, 取反除 dt
                Quat prevAligned = Quat.AlignHemisphere(q, lastRot);
                Vec3 prevErr = Quat.Log(q.Inverse() * prevAligned);
                angVel = (Vec3.Zero - prevErr) / dt;
            }

            lastPos = p;
            lastRot = q;
            lastTime = t;
            hasEstimate = true;
        }

        public Pose PredictAt(double timeSeconds)
        {
            if (!hasEstimate)
            {
                return Pose.Identity;
            }

            double ahead = timeSeconds - lastTime;
            Vec3 pos = lastPos + linVel * ahead;
            Quat rot = lastRot * Quat.Exp(angVel * ahead);
            return new Pose(pos, rot.Normalized());
        }
    }
}

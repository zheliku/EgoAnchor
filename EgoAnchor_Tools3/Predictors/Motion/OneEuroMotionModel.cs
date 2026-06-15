using System;
using EgoAnchor.Tools3.Core;
using EgoAnchor.Tools3.Data;

namespace EgoAnchor.Tools3.Predictors.Motion
{
    /// <summary>
    /// One Euro 运动模型 (自适应低通去噪 + 平滑速度)。
    ///
    /// 位置 x/y/z 各一路标量 One Euro; 旋转在最新姿态参考的切空间里三路 One Euro。
    /// 提供平滑值 (当作"当前姿态/位置") 和平滑速度 (当作外推切线)。
    /// 与旧 OneEuroPredictor 估计部分一致, 同样去掉外推限幅, 交给残差淡化消跳变。
    /// </summary>
    public sealed class OneEuroMotionModel : IMotionModel
    {
        private readonly double minCutoff;
        private readonly double beta;
        private readonly double dCutoff;

        private readonly ScalarOneEuro[] pos = new ScalarOneEuro[3];
        private readonly ScalarOneEuro[] rot = new ScalarOneEuro[3];
        private Quat rotationReference = Quat.Identity;
        private double lastTime;
        private bool hasEstimate;

        public OneEuroMotionModel(double minCutoff = 1.0, double beta = 0.25, double dCutoff = 1.0)
        {
            this.minCutoff = minCutoff;
            this.beta = beta;
            this.dCutoff = dCutoff;
            Reset();
        }

        public string Name => "oneeuro";

        public bool HasEstimate => hasEstimate;

        public double LastObservationTime => lastTime;

        public void Reset()
        {
            for (int i = 0; i < 3; i++)
            {
                pos[i] = new ScalarOneEuro(minCutoff, beta, dCutoff);
                rot[i] = new ScalarOneEuro(minCutoff, beta, dCutoff);
            }

            rotationReference = Quat.Identity;
            lastTime = 0.0;
            hasEstimate = false;
        }

        public void OnObservation(in Observation observation)
        {
            double t = observation.TimeSeconds;
            Vec3 p = observation.Pose.Position;

            if (!hasEstimate)
            {
                rotationReference = observation.Pose.Rotation.Normalized();
                pos[0].Init(p.X, t); pos[1].Init(p.Y, t); pos[2].Init(p.Z, t);
                rot[0].Init(0, t); rot[1].Init(0, t); rot[2].Init(0, t);
                lastTime = t;
                hasEstimate = true;
                return;
            }

            pos[0].Filter(p.X, t);
            pos[1].Filter(p.Y, t);
            pos[2].Filter(p.Z, t);

            Quat measured = Quat.AlignHemisphere(rotationReference, observation.Pose.Rotation.Normalized());
            Vec3 err = Quat.Log(rotationReference.Inverse() * measured);
            rot[0].Filter(err.X, t);
            rot[1].Filter(err.Y, t);
            rot[2].Filter(err.Z, t);

            lastTime = t;
        }

        public Pose PredictAt(double timeSeconds)
        {
            if (!hasEstimate)
            {
                return Pose.Identity;
            }

            double ahead = timeSeconds - lastTime; // 不限幅
            var position = new Vec3(
                pos[0].Value + pos[0].Velocity * ahead,
                pos[1].Value + pos[1].Velocity * ahead,
                pos[2].Value + pos[2].Velocity * ahead);
            var rotVec = new Vec3(
                rot[0].Value + rot[0].Velocity * ahead,
                rot[1].Value + rot[1].Velocity * ahead,
                rot[2].Value + rot[2].Velocity * ahead);
            Quat rotation = rotationReference * Quat.Exp(rotVec);
            return new Pose(position, rotation.Normalized());
        }
    }
}

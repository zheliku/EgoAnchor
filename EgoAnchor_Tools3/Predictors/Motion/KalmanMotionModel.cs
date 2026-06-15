using System;
using EgoAnchor.Tools3.Core;
using EgoAnchor.Tools3.Data;

namespace EgoAnchor.Tools3.Predictors.Motion
{
    /// <summary>
    /// 常速度 Kalman 运动模型 (去噪 + 最优速度估计)。
    ///
    /// 复用 ScalarCvKalman: 位置 x/y/z 三路一维 CV Kalman; 旋转在最新姿态参考的切空间里三路。
    /// 与旧 KalmanPredictor 的估计部分一致, 但**去掉了 maxPredictAhead 限幅**——
    /// 外推不再人为截断 (这正是旧版"平段+跳变"的根源), 让残差淡化去消跳变。
    /// </summary>
    public sealed class KalmanMotionModel : IMotionModel
    {
        private readonly double positionProcessNoise;
        private readonly double positionMeasurementNoise;
        private readonly double rotationProcessNoise;
        private readonly double rotationMeasurementNoise;

        private readonly ScalarCvKalman x = new();
        private readonly ScalarCvKalman y = new();
        private readonly ScalarCvKalman z = new();
        private readonly ScalarCvKalman rx = new();
        private readonly ScalarCvKalman ry = new();
        private readonly ScalarCvKalman rz = new();
        private Quat rotationReference = Quat.Identity;
        private double lastTime;
        private bool hasEstimate;

        public KalmanMotionModel(
            double positionProcessNoise = 0.20,
            double positionMeasurementNoise = 0.0004,
            double rotationProcessNoise = 0.40,
            double rotationMeasurementNoise = 0.0025)
        {
            this.positionProcessNoise = positionProcessNoise;
            this.positionMeasurementNoise = positionMeasurementNoise;
            this.rotationProcessNoise = rotationProcessNoise;
            this.rotationMeasurementNoise = rotationMeasurementNoise;
        }

        public string Name => "kalman";

        public bool HasEstimate => hasEstimate;

        public double LastObservationTime => lastTime;

        public void Reset()
        {
            x.Clear(); y.Clear(); z.Clear();
            rx.Clear(); ry.Clear(); rz.Clear();
            rotationReference = Quat.Identity;
            lastTime = 0.0;
            hasEstimate = false;
        }

        public void OnObservation(in Observation observation)
        {
            Vec3 p = observation.Pose.Position;
            double t = observation.TimeSeconds;

            if (!hasEstimate)
            {
                Snap(observation);
                return;
            }

            double dt = Math.Max(t - lastTime, 0.0);
            x.Predict(dt, positionProcessNoise);
            y.Predict(dt, positionProcessNoise);
            z.Predict(dt, positionProcessNoise);
            rx.Predict(dt, rotationProcessNoise);
            ry.Predict(dt, rotationProcessNoise);
            rz.Predict(dt, rotationProcessNoise);
            lastTime = t;

            x.Correct(p.X, positionMeasurementNoise);
            y.Correct(p.Y, positionMeasurementNoise);
            z.Correct(p.Z, positionMeasurementNoise);

            Quat current = CurrentRotation();
            Quat measured = Quat.AlignHemisphere(current, observation.Pose.Rotation.Normalized());
            Vec3 err = Quat.Log(rotationReference.Inverse() * measured);
            rx.Correct(err.X, rotationMeasurementNoise);
            ry.Correct(err.Y, rotationMeasurementNoise);
            rz.Correct(err.Z, rotationMeasurementNoise);
        }

        public Pose PredictAt(double timeSeconds)
        {
            if (!hasEstimate)
            {
                return Pose.Identity;
            }

            double ahead = timeSeconds - lastTime; // 不限幅
            var pos = new Vec3(
                x.Position + x.Velocity * ahead,
                y.Position + y.Velocity * ahead,
                z.Position + z.Velocity * ahead);
            var rotVec = new Vec3(
                rx.Position + rx.Velocity * ahead,
                ry.Position + ry.Velocity * ahead,
                rz.Position + rz.Velocity * ahead);
            Quat rot = rotationReference * Quat.Exp(rotVec);
            return new Pose(pos, rot.Normalized());
        }

        private void Snap(in Observation observation)
        {
            Vec3 p = observation.Pose.Position;
            x.Reset(p.X, positionMeasurementNoise, 1.0);
            y.Reset(p.Y, positionMeasurementNoise, 1.0);
            z.Reset(p.Z, positionMeasurementNoise, 1.0);
            rotationReference = observation.Pose.Rotation.Normalized();
            rx.Reset(0.0, rotationMeasurementNoise, 1.0);
            ry.Reset(0.0, rotationMeasurementNoise, 1.0);
            rz.Reset(0.0, rotationMeasurementNoise, 1.0);
            lastTime = observation.TimeSeconds;
            hasEstimate = true;
        }

        private Quat CurrentRotation()
        {
            return rotationReference * Quat.Exp(new Vec3(rx.Position, ry.Position, rz.Position));
        }
    }
}

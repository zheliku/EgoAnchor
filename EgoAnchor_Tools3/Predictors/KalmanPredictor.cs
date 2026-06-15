using System;
using EgoAnchor.Tools3.Core;
using EgoAnchor.Tools3.Data;
using EgoAnchor.Tools3.Sim;

namespace EgoAnchor.Tools3.Predictors
{
    /// <summary>
    /// 卡尔曼滤波 + 预测插值 (constant-velocity Kalman prediction)。
    ///
    /// 把轨迹建模为状态空间 [位置, 速度], 每收到一帧观测做"预测+校正", 渲染时用状态方程
    /// 以任意频率外推, 天然得到高频输出。测量噪声 R 设得很小 -> 高度信任观测, 近似过点;
    /// 同时滤掉抖动。
    ///
    /// 平移: x/y/z 三路独立的一维 CV Kalman。
    /// 旋转: 在相对参考四元数的切空间 (半角向量) 上跑三路一维 CV Kalman, 等价于估计姿态+角速度,
    ///       渲染时 Exp 回四元数。与真实 KalmanEstimatorModule 完全同构。
    ///
    /// 实时性: 递推算法, 每帧 O(1), 是最契合实时高频输出的方法之一。
    /// 默认参数取自真实模块 (posProc=0.2, posMeas=0.0004, rotProc=0.4, rotMeas=0.0025, ahead=0.18s)。
    /// </summary>
    public sealed class KalmanPredictor : IPredictor
    {
        private readonly double positionProcessNoise;
        private readonly double positionMeasurementNoise;
        private readonly double rotationProcessNoise;
        private readonly double rotationMeasurementNoise;
        private readonly double maxPredictAhead;

        private readonly ScalarCvKalman x = new();
        private readonly ScalarCvKalman y = new();
        private readonly ScalarCvKalman z = new();
        private readonly ScalarCvKalman rx = new();
        private readonly ScalarCvKalman ry = new();
        private readonly ScalarCvKalman rz = new();
        private Quat rotationReference = Quat.Identity;
        private double lastTime;
        private bool hasEstimate;

        public KalmanPredictor(
            double positionProcessNoise = 0.20,
            double positionMeasurementNoise = 0.0004,
            double rotationProcessNoise = 0.40,
            double rotationMeasurementNoise = 0.0025,
            double maxPredictAhead = 0.18)
        {
            this.positionProcessNoise = positionProcessNoise;
            this.positionMeasurementNoise = positionMeasurementNoise;
            this.rotationProcessNoise = rotationProcessNoise;
            this.rotationMeasurementNoise = rotationMeasurementNoise;
            this.maxPredictAhead = maxPredictAhead;
        }

        public string Label => "kalman_cv";

        public bool HasEstimate => hasEstimate;

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

            // 预测状态到测量时刻
            double dt = Math.Max(t - lastTime, 0.0);
            x.Predict(dt, positionProcessNoise);
            y.Predict(dt, positionProcessNoise);
            z.Predict(dt, positionProcessNoise);
            rx.Predict(dt, rotationProcessNoise);
            ry.Predict(dt, rotationProcessNoise);
            rz.Predict(dt, rotationProcessNoise);
            lastTime = t;

            // 位置校正
            x.Correct(p.X, positionMeasurementNoise);
            y.Correct(p.Y, positionMeasurementNoise);
            z.Correct(p.Z, positionMeasurementNoise);

            // 旋转校正: 把测量姿态转成相对参考的切空间误差再校正
            Quat current = CurrentRotation();
            Quat measured = Quat.AlignHemisphere(current, observation.Pose.Rotation.Normalized());
            Vec3 err = Quat.Log(rotationReference.Inverse() * measured);
            rx.Correct(err.X, rotationMeasurementNoise);
            ry.Correct(err.Y, rotationMeasurementNoise);
            rz.Correct(err.Z, rotationMeasurementNoise);
        }

        public Pose PredictAt(double renderTimeSeconds)
        {
            if (!hasEstimate)
            {
                return Pose.Identity;
            }

            double ahead = Math.Clamp(renderTimeSeconds - lastTime, 0.0, maxPredictAhead);

            var position = new Vec3(
                x.Position + x.Velocity * ahead,
                y.Position + y.Velocity * ahead,
                z.Position + z.Velocity * ahead);

            var rotVec = new Vec3(
                rx.Position + rx.Velocity * ahead,
                ry.Position + ry.Velocity * ahead,
                rz.Position + rz.Velocity * ahead);

            Quat rotation = rotationReference * Quat.Exp(rotVec);
            return new Pose(position, rotation.Normalized());
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

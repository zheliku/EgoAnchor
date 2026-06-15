using System;
using EgoAnchor.Tools3.Core;
using EgoAnchor.Tools3.Data;
using EgoAnchor.Tools3.Sim;

namespace EgoAnchor.Tools3.Predictors
{
    /// <summary>
    /// One Euro Filter + 预测模型。
    ///
    /// One Euro 是一个自适应低通滤波器 (Casiez et al. 2012): 截止频率随信号变化速度自适应——
    /// 信号慢时截止频率低 (更平滑, 抑抖), 信号快时截止频率高 (更跟手, 减延迟)。
    /// 核心:
    ///   - 对原始信号 x 估计其变化率 dx, 对 dx 做固定低通得到平滑速度 dxHat;
    ///   - 截止频率 fc = minCutoff + beta * |dxHat|;
    ///   - 用 fc 算的自适应系数 a 对 x 做低通得到平滑值 xHat。
    ///
    /// 预测: One Euro 本身只平滑不外推, 这里在平滑值之上叠加一阶外推:
    ///   render(t) = xHat + dxHat * clamp(t - tLast, 0, maxPredictAhead)
    /// 即用平滑后的速度把 pose 外推到渲染时刻, 抵消采样间隔造成的滞后。
    ///
    /// 位置: 对 x/y/z 各跑一路标量 One Euro。
    /// 旋转: 在"相对参考四元数的切空间向量"上跑 One Euro (与位置同构), 再 Exp 回四元数。
    /// 参考真实模块 OneEuroEstimatorModule 的参数 (beta=0.25, minCutoff=1, dCutoff=1, ahead=0.12s)。
    /// </summary>
    public sealed class OneEuroPredictor : IPredictor
    {
        private readonly double minCutoff;
        private readonly double beta;
        private readonly double dCutoff;
        private readonly double maxPredictAhead;

        private readonly ScalarOneEuro[] pos = new ScalarOneEuro[3];
        private readonly ScalarOneEuro[] rot = new ScalarOneEuro[3];
        private Quat rotationReference = Quat.Identity;
        private double lastTime;
        private bool hasEstimate;

        public OneEuroPredictor(
            double minCutoff = 1.0,
            double beta = 0.25,
            double dCutoff = 1.0,
            double maxPredictAhead = 0.12)
        {
            this.minCutoff = minCutoff;
            this.beta = beta;
            this.dCutoff = dCutoff;
            this.maxPredictAhead = maxPredictAhead;
            Reset();
        }

        public string Label => "oneeuro_predict";

        public bool HasEstimate => hasEstimate;

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
                // 第一帧: 初始化滤波器, 参考姿态设为当前旋转
                rotationReference = observation.Pose.Rotation.Normalized();
                pos[0].Init(p.X, t);
                pos[1].Init(p.Y, t);
                pos[2].Init(p.Z, t);
                rot[0].Init(0, t);
                rot[1].Init(0, t);
                rot[2].Init(0, t);
                lastTime = t;
                hasEstimate = true;
                return;
            }

            pos[0].Filter(p.X, t);
            pos[1].Filter(p.Y, t);
            pos[2].Filter(p.Z, t);

            // 旋转: 测到的姿态相对参考的切空间误差 (半角向量)
            Quat measured = Quat.AlignHemisphere(rotationReference, observation.Pose.Rotation.Normalized());
            Vec3 err = Quat.Log(rotationReference.Inverse() * measured);
            rot[0].Filter(err.X, t);
            rot[1].Filter(err.Y, t);
            rot[2].Filter(err.Z, t);

            lastTime = t;
        }

        public Pose PredictAt(double renderTimeSeconds)
        {
            if (!hasEstimate)
            {
                return Pose.Identity;
            }

            double ahead = Math.Clamp(renderTimeSeconds - lastTime, 0.0, maxPredictAhead);

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

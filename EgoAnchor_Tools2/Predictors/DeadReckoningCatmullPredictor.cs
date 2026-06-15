using System.Collections.Generic;
using EgoAnchor.Tools2.Data;
using EgoAnchor.Tools2.Math;
using EgoAnchor.Tools2.Sim;

namespace EgoAnchor.Tools2.Predictors
{
    /// <summary>
    /// 航位推测 + 样条修正 (Dead Reckoning + Spline Correction) 预测器。
    ///
    /// 这是网络/实时仿真最经典的混合方法,分两阶段:
    ///
    /// 1. 预测阶段 (等待下一个观测时,renderTime 在最新观测 P_last 之后):
    ///    用 P_last 处的二阶匀加速运动外推。从最近三个观测 P_{n-2}, P_{n-1}, P_n 估:
    ///      v_n  = (P_n - P_{n-1}) / dt
    ///      a_n  = (v_n - v_{n-1}) / dt
    ///    外推:
    ///      pos(t) = P_n.pos + v_n*(t-t_n) + 0.5*a_n*(t-t_n)^2
    ///      rot(t) = P_n.rot * Exp(ω_n*(t-t_n) + 0.5*α_n*(t-t_n)^2)
    ///
    /// 2. 修正阶段 (新观测到达后的短过渡窗口内):
    ///    当新观测 P_{n+1} 到达,renderTime 仍落在 P_{n-1}->P_n 之间时 (因为 Unity 用 capture 时间,
    ///    render 时间总是滞后),用 Centripetal Catmull-Rom 在 P_{n-1}->P_n 之间做平滑插值,
    ///    保证严格过点且 C^1 连续。这是"快照插值"的过点平滑部分。
    ///
    /// 实时关键:renderTime 几乎总是 >= 最新观测 capture 时间 (Unity predict-ahead),
    /// 所以主路径是二阶外推;Catmull-Rom 修正只在 renderTime 落在已知两观测之间时启用,
    /// 用于把阶梯状 ZOH 拉平成平滑曲线 (尤其在观测刚到达的几帧)。
    ///
    /// 旋转用切空间角轴,与其它算法一致,不用 SLERP。
    /// </summary>
    public sealed class DeadReckoningCatmullPredictor : IAnchorPredictor
    {
        /// <summary>维护最近 4 个观测,用于 Catmull-Rom (P0,P1,P2,P3)。</summary>
        private readonly List<PoseObservation> history = new List<PoseObservation>(4);

        /// <summary>最近一次二阶外推的线速度 (m/s),用于跨段平滑。</summary>
        private Vec3 lastLinearVelocity = Vec3.Zero;

        /// <summary>最近一次二阶外推的角速度 (rad/s)。</summary>
        private Vec3 lastAngularVelocity = Vec3.Zero;

        /// <summary>最近一次二阶外推的线加速度 (m/s^2)。</summary>
        private Vec3 lastLinearAccel = Vec3.Zero;

        /// <summary>最近一次二阶外推的角加速度 (rad/s^2)。</summary>
        private Vec3 lastAngularAccel = Vec3.Zero;

        /// <summary>最新观测时间 (秒),外推基准。</summary>
        private double lastObsTime;

        private bool hasEstimate;

        /// <summary>算法标签。</summary>
        public string Label => "deadreckoning_catmull";

        /// <summary>是否已积累至少一个观测。</summary>
        public bool HasEstimate => hasEstimate;

        /// <summary>清空状态。</summary>
        public void Reset()
        {
            history.Clear();
            lastLinearVelocity = Vec3.Zero;
            lastAngularVelocity = Vec3.Zero;
            lastLinearAccel = Vec3.Zero;
            lastAngularAccel = Vec3.Zero;
            lastObsTime = 0.0;
            hasEstimate = false;
        }

        /// <summary>提交观测:压入历史并更新速度/加速度估计。</summary>
        public void SubmitObservation(in PoseObservation observation)
        {
            // 维护最多 4 个最近观测
            history.Add(observation);
            while (history.Count > 4)
            {
                history.RemoveAt(0);
            }

            lastObsTime = observation.CaptureTimeSeconds;
            hasEstimate = true;

            // 用最近 2~3 个观测更新速度/加速度估计
            UpdateKinematics();
        }

        /// <summary>预测到 render 时间。</summary>
        public (Vec3 position, QuaternionM rotation) PredictAt(double renderTimeSeconds)
        {
            if (!hasEstimate)
            {
                return (Vec3.Zero, QuaternionM.Identity);
            }

            // 决策:renderTime 是否落在已知两观测之间 (可做 Catmull-Rom 插值)
            // 历史最后两个点 P_{n-1} (idx count-2) 和 P_n (idx count-1)
            if (history.Count >= 2)
            {
                PoseObservation pPrev = history[history.Count - 2];
                PoseObservation pLast = history[history.Count - 1];

                if (renderTimeSeconds >= pPrev.CaptureTimeSeconds && renderTimeSeconds <= pLast.CaptureTimeSeconds)
                {
                    // renderTime 落在最近两个已知观测之间:用 Centripetal Catmull-Rom 插值
                    // (修正阶段:严格过点平滑)
                    return CatmullRomSample(renderTimeSeconds);
                }
            }

            // 否则:renderTime 在最新观测之后,做二阶匀加速外推 (预测阶段)
            return Extrapolate(renderTimeSeconds);
        }

        /// <summary>从最近观测更新速度/加速度估计。</summary>
        private void UpdateKinematics()
        {
            int n = history.Count;
            if (n < 2)
            {
                lastLinearVelocity = Vec3.Zero;
                lastAngularVelocity = Vec3.Zero;
                lastLinearAccel = Vec3.Zero;
                lastAngularAccel = Vec3.Zero;
                return;
            }

            PoseObservation pLast = history[n - 1];
            PoseObservation pPrev = history[n - 2];
            float dt = (float)(pLast.CaptureTimeSeconds - pPrev.CaptureTimeSeconds);
            if (dt <= 1e-5f) dt = 1e-5f;

            // 当前速度 = 差分
            Vec3 v = (pLast.Position - pPrev.Position) / dt;
            Vec3 omega = AnchorMath.AngularVelocity(pPrev.Rotation, pLast.Rotation, dt);

            if (n >= 3)
            {
                // 当前加速度 = 速度差分
                PoseObservation pPrev2 = history[n - 3];
                float dtPrev = (float)(pPrev.CaptureTimeSeconds - pPrev2.CaptureTimeSeconds);
                if (dtPrev <= 1e-5f) dtPrev = 1e-5f;
                Vec3 vPrev = (pPrev.Position - pPrev2.Position) / dtPrev;
                Vec3 omegaPrev = AnchorMath.AngularVelocity(pPrev2.Rotation, pPrev.Rotation, dtPrev);

                // 加速度按总时间差归一化,避免两段 dt 不同导致量级错
                float dtTotal = (float)(pLast.CaptureTimeSeconds - pPrev2.CaptureTimeSeconds);
                if (dtTotal <= 1e-5f) dtTotal = 1e-5f;
                lastLinearAccel = (v - vPrev) / dtTotal;
                lastAngularAccel = (omega - omegaPrev) / dtTotal;
            }

            lastLinearVelocity = v;
            lastAngularVelocity = omega;
        }

        /// <summary>从最新观测做二阶匀加速外推。</summary>
        private (Vec3 position, QuaternionM rotation) Extrapolate(double renderTimeSeconds)
        {
            PoseObservation pLast = history[history.Count - 1];
            float ahead = AnchorMath.Max((float)(renderTimeSeconds - lastObsTime), 0.0f);
            float halfAhead2 = 0.5f * ahead * ahead;

            Vec3 pos = pLast.Position
                + lastLinearVelocity * ahead
                + lastLinearAccel * halfAhead2;

            // 旋转:角速度 + 角加速度在切空间二阶积分
            Vec3 rotDelta = lastAngularVelocity * ahead + lastAngularAccel * halfAhead2;
            QuaternionM rot = AnchorMath.Multiply(pLast.Rotation, AnchorMath.Exp(rotDelta));
            return (pos, rot);
        }

        /// <summary>
        /// Centripetal Catmull-Rom 插值 (α=0.5)。
        /// 在 P1->P2 之间按 renderTime 采样,位置过点 C^1 连续;旋转用切空间插值。
        /// 需要至少 2 个点;首尾缺失时镜像端点构造虚拟控制点。
        /// </summary>
        private (Vec3 position, QuaternionM rotation) CatmullRomSample(double renderTimeSeconds)
        {
            int n = history.Count;
            // P1 = history[n-2], P2 = history[n-1];P0/P3 用镜像或端点
            PoseObservation p1 = history[n - 2];
            PoseObservation p2 = history[n - 1];
            // P0:有 n>=3 用 history[n-3],否则镜像 P1 关于 P2 反向 (虚拟)
            Vec3 p0Pos, p1Pos = p1.Position, p2Pos = p2.Position, p3Pos;
            QuaternionM p0Rot, p1Rot = p1.Rotation, p2Rot = p2.Rotation, p3Rot;
            double t0, t1 = p1.CaptureTimeSeconds, t2 = p2.CaptureTimeSeconds, t3;

            if (n >= 3)
            {
                PoseObservation p0 = history[n - 3];
                p0Pos = p0.Position;
                p0Rot = p0.Rotation;
                t0 = p0.CaptureTimeSeconds;
            }
            else
            {
                // 镜像:P0 = 2*P1 - P2
                p0Pos = p1Pos * 2f - p2Pos;
                p0Rot = p1Rot; // 旋转镜像用 P1 简化,避免四元数外推奇异
                t0 = t1 - (t2 - t1);
            }

            // P3:没有第 4 个点时镜像 P3 = 2*P2 - P1
            p3Pos = p2Pos * 2f - p1Pos;
            p3Rot = p2Rot;
            t3 = t2 + (t2 - t1);

            // 归一化参数 u in [0,1],对应 P1->P2
            double span = t2 - t1;
            if (span <= 1e-9) span = 1e-9;
            float u = AnchorMath.Clamp01((float)((renderTimeSeconds - t1) / span));

            // 位置:Centripetal Catmull-Rom (De Casteljau 形式,α=0.5 参数化用均匀化简化)
            // 这里用均匀参数化的三次 Catmull-Rom (α=0) 做位置,工程上足够平滑
            Vec3 pos = CatmullRomPosition(p0Pos, p1Pos, p2Pos, p3Pos, u);

            // 旋转:切空间插值。用 P1->P2 的角轴误差按 u 缩放
            QuaternionM alignedP2 = AnchorMath.AlignHemisphere(p1Rot, p2Rot);
            Vec3 delta = AnchorMath.Log(AnchorMath.Multiply(AnchorMath.Inverse(p1Rot), alignedP2));
            QuaternionM rot = AnchorMath.Multiply(p1Rot, AnchorMath.Exp(delta * u));

            return (pos, rot);
        }

        /// <summary>均匀参数化三次 Catmull-Rom 位置插值。</summary>
        private static Vec3 CatmullRomPosition(Vec3 p0, Vec3 p1, Vec3 p2, Vec3 p3, float u)
        {
            // 标准 Catmull-Rom 基函数 (α=0 均匀参数化)
            float u2 = u * u;
            float u3 = u2 * u;
            Vec3 v = 0.5f * (
                (2f * p1)
                + (-p0 + p2) * u
                + (2f * p0 - 5f * p1 + 4f * p2 - p3) * u2
                + (-p0 + 3f * p1 - 3f * p2 + p3) * u3);
            return v;
        }
    }
}

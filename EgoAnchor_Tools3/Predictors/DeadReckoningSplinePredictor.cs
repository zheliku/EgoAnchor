using System;
using EgoAnchor.Tools3.Core;
using EgoAnchor.Tools3.Data;
using EgoAnchor.Tools3.Sim;

namespace EgoAnchor.Tools3.Predictors
{
    /// <summary>
    /// 航位推测 + 样条修正 (Dead Reckoning + Spline Correction)。
    ///
    /// 这是网络游戏 / 实时仿真的经典方案, 专为"零延迟 + 平滑无跳变"设计。两阶段:
    ///
    /// 1) 航位推测 (Dead Reckoning): 在两帧观测之间, 用上一帧的位置和估计速度做一阶外推
    ///        x(t) = x0 + v0 * (t - t0)
    ///    任意时刻都能立即给出 pose, 绝不卡顿等待。
    ///
    /// 2) 样条修正 (Spline Correction): 新观测到达时, 当前渲染位置 (DR 外推到的地方) 和新观测
    ///    之间通常有偏差。不硬跳 (会突变), 而是构造一段三次 Hermite 曲线, 在一个修正窗口
    ///    (correctionWindow, 默认≈一个观测周期) 内从"当前渲染 pose + 当前渲染速度"平滑过渡到
    ///    "新观测 pose + 新观测速度"。Hermite 同时匹配两端的位置和速度 => C¹ 连续:
    ///    位置不跳、速度不跳, 且窗口结束时精确命中新观测点 (过点)。
    ///
    /// 因此整条渲染轨迹 = 一段段首尾速度连续的 Hermite 拼接, 视觉上连续平滑;
    /// 窗口内是"边修正边继续 DR", 窗口结束后纯 DR 直到下一帧。
    ///
    /// 位置用三维 Hermite; 旋转用四元数: 参考姿态切空间里的角速度做 DR, 修正时对切空间向量
    /// 做同样的 Hermite (等价于对姿态做带速度匹配的平滑过渡)。
    /// </summary>
    public sealed class DeadReckoningSplinePredictor : IPredictor
    {
        private readonly double correctionWindow; // 修正窗口时长 (秒)
        private readonly double maxDeadReckonAhead; // DR 外推上限, 防止长时间丢观测时飞走

        // 最近两帧观测, 用于估计观测速度
        private bool hasPrev;
        private Pose prevObsPose;
        private double prevObsTime;

        private bool hasEstimate;

        // 当前 Hermite 修正段的端点状态 (位置 + 旋转用切空间向量统一处理)
        private double segStartTime;
        private double segEndTime;
        private Vec3 segP0, segV0, segP1, segV1;            // 位置端点 + 速度
        private Quat segRotRef;                              // 旋转参考 (用 segP1 对应观测的姿态做参考)
        private Vec3 segR0, segRv0, segR1, segRv1;          // 旋转切空间端点 + 角速度
        // 段结束后用于纯 DR 的状态 (= 段末端的 pose 和速度)
        private double drBaseTime;
        private Vec3 drBaseP, drVel;
        private Quat drRotRef;
        private Vec3 drBaseR, drRvel;

        // 记录上一次渲染输出, 作为下一个修正段的起点 (保证段间连续)
        private bool hasLastRender;
        private double lastRenderTime;
        private Pose lastRenderPose;
        private Vec3 lastRenderVel;       // 位置速度 (数值微分)
        private Vec3 lastRenderRvel;      // 旋转切空间角速度

        public DeadReckoningSplinePredictor(double correctionWindow = 0.20, double maxDeadReckonAhead = 0.40)
        {
            this.correctionWindow = correctionWindow;
            this.maxDeadReckonAhead = maxDeadReckonAhead;
        }

        public string Label => "deadreckoning_spline";

        public bool HasEstimate => hasEstimate;

        public void Reset()
        {
            hasPrev = false;
            hasEstimate = false;
            hasLastRender = false;
            prevObsPose = Pose.Identity;
            prevObsTime = 0.0;
            segRotRef = Quat.Identity;
            drRotRef = Quat.Identity;
        }

        public void OnObservation(in Observation observation)
        {
            double t = observation.TimeSeconds;
            Pose obs = new Pose(observation.Pose.Position, observation.Pose.Rotation.Normalized());

            if (!hasEstimate)
            {
                // 第一帧: 没有速度信息, 直接定位, DR 速度为 0
                hasEstimate = true;
                hasPrev = true;
                prevObsPose = obs;
                prevObsTime = t;

                drBaseTime = t;
                drBaseP = obs.Position;
                drVel = Vec3.Zero;
                drRotRef = obs.Rotation;
                drBaseR = Vec3.Zero;
                drRvel = Vec3.Zero;

                // 没有上一帧渲染, 修正段退化为常量
                lastRenderTime = t;
                lastRenderPose = obs;
                lastRenderVel = Vec3.Zero;
                lastRenderRvel = Vec3.Zero;
                hasLastRender = true;
                StartTrivialSegment(t, obs);
                return;
            }

            // 估计新观测处的速度 (用最近两帧观测的差分)
            Vec3 obsVel = Vec3.Zero;
            Vec3 obsRvel = Vec3.Zero;
            Quat obsRotRef = obs.Rotation;
            if (hasPrev)
            {
                double dtObs = Math.Max(t - prevObsTime, 1e-4);
                obsVel = (obs.Position - prevObsPose.Position) / dtObs;

                // 旋转角速度 (切空间, 相对新观测姿态参考): 用上一帧姿态映射到该参考再除以 dt
                Quat prevAligned = Quat.AlignHemisphere(obsRotRef, prevObsPose.Rotation);
                Vec3 prevErr = Quat.Log(obsRotRef.Inverse() * prevAligned); // 上一帧相对当前观测的偏移
                // 角速度方向: 从 prev 指向 current(=0), 所以速度 ≈ (0 - prevErr)/dt
                obsRvel = (Vec3.Zero - prevErr) / dtObs;
            }

            // 取当前渲染状态作为修正段起点 (若刚好有上一渲染帧)
            Vec3 startP = hasLastRender ? lastRenderPose.Position : prevObsPose.Position;
            Vec3 startV = hasLastRender ? lastRenderVel : Vec3.Zero;
            Quat startRot = hasLastRender ? lastRenderPose.Rotation : prevObsPose.Rotation;

            // 用新观测姿态作为旋转参考, 把起点姿态和终点姿态都映射到该参考的切空间
            Quat startAligned = Quat.AlignHemisphere(obsRotRef, startRot.Normalized());
            Vec3 startR = Quat.Log(obsRotRef.Inverse() * startAligned);
            Vec3 startRv = hasLastRender ? lastRenderRvel : Vec3.Zero;

            // 建立新的 Hermite 修正段: [now, now+window] 从 (start) 平滑到 (obs)
            segStartTime = t;
            segEndTime = t + correctionWindow;
            segP0 = startP;
            segV0 = startV;
            segP1 = obs.Position;
            segV1 = obsVel;

            segRotRef = obsRotRef;
            segR0 = startR;
            segRv0 = startRv;
            segR1 = Vec3.Zero;     // 终点就是观测姿态本身 => 切空间为 0
            segRv1 = obsRvel;

            // 段结束后的纯 DR 基准 = 段末端 (= 观测点 + 观测速度)
            drBaseTime = segEndTime;
            drBaseP = obs.Position; // 注意: Hermite 末端位置 = segP1 = obs.Position
            drVel = obsVel;
            drRotRef = obsRotRef;
            drBaseR = Vec3.Zero;
            drRvel = obsRvel;

            prevObsPose = obs;
            prevObsTime = t;
            hasPrev = true;
        }

        public Pose PredictAt(double renderTimeSeconds)
        {
            if (!hasEstimate)
            {
                return Pose.Identity;
            }

            Pose result;
            if (renderTimeSeconds <= segEndTime)
            {
                // 在修正窗口内: 走 Hermite
                double span = Math.Max(segEndTime - segStartTime, 1e-6);
                double u = Math.Clamp((renderTimeSeconds - segStartTime) / span, 0.0, 1.0);

                Vec3 pos = Hermite(segP0, segV0, segP1, segV1, u, span);
                Vec3 rv = Hermite(segR0, segRv0, segR1, segRv1, u, span);
                Quat rot = segRotRef * Quat.Exp(rv);
                result = new Pose(pos, rot.Normalized());
            }
            else
            {
                // 窗口外: 纯航位推测, 限制最大外推时长
                double ahead = Math.Clamp(renderTimeSeconds - drBaseTime, 0.0, maxDeadReckonAhead);
                Vec3 pos = drBaseP + drVel * ahead;
                Vec3 rv = drBaseR + drRvel * ahead;
                Quat rot = drRotRef * Quat.Exp(rv);
                result = new Pose(pos, rot.Normalized());
            }

            // 数值微分更新"上一渲染帧"的速度, 供下一个修正段做 C¹ 衔接
            if (hasLastRender)
            {
                double dt = renderTimeSeconds - lastRenderTime;
                if (dt > 1e-6)
                {
                    lastRenderVel = (result.Position - lastRenderPose.Position) / dt;
                    // 旋转角速度: 在 result 旋转参考下取相对上一帧的切空间增量
                    Quat prevAligned = Quat.AlignHemisphere(result.Rotation, lastRenderPose.Rotation);
                    Vec3 d = Quat.Log(result.Rotation.Inverse() * prevAligned);
                    lastRenderRvel = (Vec3.Zero - d) / dt;
                }
            }

            lastRenderTime = renderTimeSeconds;
            lastRenderPose = result;
            hasLastRender = true;
            return result;
        }

        /// <summary>第一帧时的平凡段: 起止相同, 速度为 0。</summary>
        private void StartTrivialSegment(double t, Pose obs)
        {
            segStartTime = t;
            segEndTime = t; // 立即结束, 之后走 DR
            segP0 = segP1 = obs.Position;
            segV0 = segV1 = Vec3.Zero;
            segRotRef = obs.Rotation;
            segR0 = segR1 = Vec3.Zero;
            segRv0 = segRv1 = Vec3.Zero;
        }

        /// <summary>
        /// 三次 Hermite 插值。参数 u∈[0,1], span 是该段的真实时长 (秒), 用于把"每秒速度"
        /// 换算到 Hermite 的单位区间切线 (m1 = v * span)。
        /// </summary>
        private static Vec3 Hermite(Vec3 p0, Vec3 v0, Vec3 p1, Vec3 v1, double u, double span)
        {
            double u2 = u * u;
            double u3 = u2 * u;
            double h00 = 2 * u3 - 3 * u2 + 1;
            double h10 = u3 - 2 * u2 + u;
            double h01 = -2 * u3 + 3 * u2;
            double h11 = u3 - u2;
            Vec3 m0 = v0 * span;
            Vec3 m1 = v1 * span;
            return p0 * h00 + m0 * h10 + p1 * h01 + m1 * h11;
        }
    }
}

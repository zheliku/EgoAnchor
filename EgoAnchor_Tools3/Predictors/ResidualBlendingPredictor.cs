using System;
using System.Collections.Generic;
using EgoAnchor.Tools3.Core;
using EgoAnchor.Tools3.Data;
using EgoAnchor.Tools3.Predictors.Motion;
using EgoAnchor.Tools3.Sim;

namespace EgoAnchor.Tools3.Predictors
{
    /// <summary>
    /// 「高频外推 + 残差淡化」通用管线 (工业级做法, 如 Source 引擎 / Oculus ASW 的位置部分)。
    ///
    /// 运动模型 (CV / Kalman / OneEuro) 负责"估计运动状态 + 外推到当前时刻";
    /// 本类负责"消跳变": 不在新观测到达时一次性纠正, 而是把误差当作"债", 每帧还一点点 (指数衰减),
    /// 在接下来十几个 60fps 帧里悄悄把轨迹平滑拉回。**零延迟 + 零跳变 + 无 overshoot。**
    ///
    /// 三步管线:
    ///   1) 高频外推 (每个渲染帧):  base = model.PredictAt(now)
    ///      渲染输出 render = base ⊕ residual    (residual = 当前待还的债)
    ///      然后 residual 衰减: residual *= decayPerFrame
    ///   2) 新观测到达 (每 ~200ms):  model.OnObservation(z) 更新运动状态
    ///   3) 重置残差 (历史纠偏):     residual = (刚才渲染到的 pose) ⊖ (更新后 model 在 now 的预测)
    ///      => 下一帧 render = newModel.PredictAt(now) ⊕ residual ≈ 上一帧 render  (C⁰ 连续, 不跳)
    ///         之后 residual 衰减到 0, 轨迹平滑收敛到新模型的最优轨迹。
    ///
    /// 位置残差是 Vec3 (米); 旋转残差是切空间半角向量 (配 Quat.Exp), SLERP 式还债。
    /// </summary>
    public sealed class ResidualBlendingPredictor : IPredictor
    {
        private readonly IMotionModel model;
        private readonly double decayPerFrame; // 每帧保留的残差比例 (0.9 = 每帧还 10%)

        private Vec3 posResidual = Vec3.Zero;
        private Vec3 rotResidual = Vec3.Zero; // 切空间半角向量
        private bool hasRendered;
        private Pose lastRender = Pose.Identity;
        private double lastRenderTime;
        private double latencyEstimate; // 实测 now - 最近观测时间 的 EMA (自适应外推上限)
        private const double ExtrapolationLatencyMultiplier = 1.0; // 外推上限 = 实测延迟 × 此倍数
        private const double MaxExtrapolationHardCapSeconds = 0.3;  // 兜底硬上限

        /// <param name="model">可插拔运动模型。</param>
        /// <param name="decayPerFrame">每帧残差保留比例 (默认 0.9, 即每帧还 10% 的债)。</param>
        public ResidualBlendingPredictor(IMotionModel model, double decayPerFrame = 0.9)
        {
            this.model = model;
            this.decayPerFrame = decayPerFrame;
        }

        public string Label => $"{model.Name}_blend";

        public bool HasEstimate => model.HasEstimate;

        public void Reset()
        {
            model.Reset();
            posResidual = Vec3.Zero;
            rotResidual = Vec3.Zero;
            hasRendered = false;
            lastRender = Pose.Identity;
            lastRenderTime = 0.0;
            latencyEstimate = 0.0;
        }

        public void OnObservation(in Observation observation)
        {
            bool firstEver = !model.HasEstimate;

            // 在更新模型前, 记下"此刻按旧轨迹应渲染到哪" (= 上一帧 render, 因为观测先于本 tick 的渲染)
            // 用于让新轨迹从这里无缝接上。
            Pose renderedNow = hasRendered ? lastRender : observation.Pose;

            model.OnObservation(observation);

            if (firstEver || !hasRendered)
            {
                // 第一帧: 没有历史轨迹可接, 残差归零, 直接落在模型上
                posResidual = Vec3.Zero;
                rotResidual = Vec3.Zero;
                return;
            }

            // 历史纠偏: 残差 = 旧渲染 pose ⊖ 新模型在"上一帧渲染时刻"的预测
            // (用 lastRenderTime 而非 now: 此刻 now 尚未渲染, renderedNow 对应的就是 lastRenderTime)
            Pose modelAtRenderTime = model.PredictAt(ClampPredictTime(lastRenderTime));
            posResidual = renderedNow.Position - modelAtRenderTime.Position;

            // 旋转残差: 在新模型姿态参考系下, 旧渲染姿态相对新模型预测姿态的切空间偏移
            Quat rendAligned = Quat.AlignHemisphere(modelAtRenderTime.Rotation, renderedNow.Rotation);
            rotResidual = Quat.Log(modelAtRenderTime.Rotation.Inverse() * rendAligned);
        }

        public Pose PredictAt(double renderTimeSeconds)
        {
            if (!model.HasEstimate)
            {
                return Pose.Identity;
            }

            // 更新实测采集-渲染延迟 (now - 最近观测时间), 自适应跟踪当前帧率/推理速度
            double observedLatency = Math.Max(renderTimeSeconds - model.LastObservationTime, 0.0);
            double follow = observedLatency > latencyEstimate ? 0.5 : 0.05;
            latencyEstimate += follow * (observedLatency - latencyEstimate);

            // 1) 外推 (限幅: 最多外推到"补偿当前实测延迟", 防止飞出去/急停冲过头)
            Pose basePose = model.PredictAt(ClampPredictTime(renderTimeSeconds));

            // 2) 叠加当前残差 (还没还完的债)
            Vec3 pos = basePose.Position + posResidual;
            Quat rot = (basePose.Rotation * Quat.Exp(rotResidual)).Normalized();
            Pose render = new Pose(pos, rot);

            // 3) 残差衰减 (还债)。按实际帧间隔归一到"每 60fps 帧" 的衰减, 保证不同 render-hz 行为一致。
            if (hasRendered)
            {
                double dt = renderTimeSeconds - lastRenderTime;
                double frames = dt * 60.0; // 以 60fps 为基准帧
                double decay = Math.Pow(decayPerFrame, Math.Max(frames, 0.0));
                posResidual *= decay;
                rotResidual *= decay;
            }

            hasRendered = true;
            lastRender = render;
            lastRenderTime = renderTimeSeconds;
            return render;
        }

        /// <summary>
        /// 把预测时刻钳到 "最近观测时间 + 外推上限"。外推上限 = 实测延迟 × 倍数, 与硬上限取小。
        /// 自适应: 延迟越小 (高 fps) 上限越小, 永远只外推刚好补偿延迟那么多。
        /// </summary>
        private double ClampPredictTime(double requestedTime)
        {
            double horizon = Math.Min(latencyEstimate * ExtrapolationLatencyMultiplier, MaxExtrapolationHardCapSeconds);
            double horizonTime = model.LastObservationTime + horizon;
            return requestedTime > horizonTime ? horizonTime : requestedTime;
        }
    }
}

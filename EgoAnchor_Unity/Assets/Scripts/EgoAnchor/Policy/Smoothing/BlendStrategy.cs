using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// B 路平滑策略：高频外推 + 误差融合 (Error Blending)。零延迟。
    ///
    /// 工业级做法 (Source 引擎 / Oculus ASW 位置部分)：
    ///   - 每渲染帧：render = model.PredictAt(now) ⊕ residual，然后 residual 指数衰减；
    ///   - 新观测到达：residual = (旧渲染 pose) ⊖ (新 model 在该时刻的预测)
    ///       => 下一帧 render ≈ 上一帧 render (C⁰ 连续，不跳)，之后残差衰减到 0，平滑收敛到新轨迹。
    ///
    /// 不在新观测时硬跳 (闪现)，而是把误差当"债"，每帧还一点点。**零延迟 + 零跳变 + 无 overshoot**，
    /// 正是离线仿真里效果最好的方案。位置残差是 Vector3；旋转残差是切空间向量 (配 Exp)。
    /// </summary>
    public sealed class BlendStrategy : SmoothingStrategy
    {
        /// <summary>每帧残差保留比例 (0.9 = 每帧还 10% 的债)。越大越平滑但滞后越久。</summary>
        [Tooltip("每帧残差保留比例 (按 60fps 基准)。0.9 = 每帧还 10% 的债。越大越平滑但纠正越慢/滞后越久；越小越快纠正但接近闪现。默认 0.9 (时间常数约 158ms)。")]
        [Range(0.5f, 0.99f)]
        [SerializeField] private float decayPerFrame = 0.9f;

        /// <summary>
        /// 外推上限倍数 × 实测采集-渲染延迟 = 允许的最大外推时长。**自适应、不绑定 fps**。
        /// 换更快的显卡 → 延迟自动变小 → 外推上限自动跟着变小，永远只外推"刚好补偿延迟"那么多。
        /// 1.0 = 只外推到补偿当前延迟 (推荐)；&gt;1 留余量但可能冲过头；设很大则接近不限制。
        /// </summary>
        [Tooltip("外推上限倍数 × 实测采集-渲染延迟 = 最大外推时长。自适应、不绑 fps：换快显卡后延迟变小，上限自动变小。1.0=只补偿当前延迟 (推荐)。默认 1.0。")]
        [Range(0.5f, 3.0f)]
        [SerializeField] private float extrapolationLatencyMultiplier = 1.0f;

        /// <summary>外推时长绝对上限，单位秒。和自适应值取小，作为延迟异常 (如长时间丢观测) 时的硬保护。</summary>
        [Tooltip("外推时长绝对上限 (秒)，与自适应值取小，作为兜底硬保护 (防丢观测时延迟估计飙升)。默认 0.3。")]
        [Range(0.05f, 1.0f)]
        [SerializeField] private float maxExtrapolationSecondsHardCap = 0.3f;

        private Vector3 posResidual;
        private Vector3 rotResidual; // 切空间向量 (rad)
        private bool hasRendered;
        private Pose lastRender;
        private double lastRenderTimeSeconds;
        private float latencyEstimateSeconds; // 实测 now - 最近观测时间 的 EMA

        public override string StrategyName => "blend";

        public override void ResetStrategy()
        {
            posResidual = Vector3.zero;
            rotResidual = Vector3.zero;
            hasRendered = false;
            lastRender = Pose.identity;
            lastRenderTimeSeconds = 0.0;
            latencyEstimateSeconds = 0.0f;
            OutputTargetTimeSeconds = double.NaN;
        }

        public override void OnObservation(MotionModel model, in AnchorObservation observation)
        {
            // 观测先于本帧渲染到达：此刻"按旧轨迹应渲染到哪" = 上一帧 render。
            // model 已被 host 更新过，这里计算残差让新轨迹从旧渲染位置无缝接上。
            if (!hasRendered || !model.HasState)
            {
                posResidual = Vector3.zero;
                rotResidual = Vector3.zero;
                return;
            }

            Pose modelAtRenderTime = model.PredictAt(ClampPredictTime(model, lastRenderTimeSeconds));
            posResidual = lastRender.position - modelAtRenderTime.position;
            rotResidual = AnchorMath.RelativeRotationLog(modelAtRenderTime.rotation, lastRender.rotation);
        }

        public override Pose Output(MotionModel model, double nowSeconds)
        {
            // 残差融合把旧渲染 pose 与当前预测混合，结果通常没有唯一的语义时刻。
            OutputTargetTimeSeconds = double.NaN;
            // 更新实测采集-渲染延迟 (now - 最近观测时间)，自适应跟踪当前帧率/推理速度 (快升慢降)
            if (model.HasState)
            {
                float observedLatency = Mathf.Max((float)(nowSeconds - model.LastObservationTimeSeconds), 0.0f);
                latencyEstimateSeconds = AnchorMath.UpdateAsymmetricEma(latencyEstimateSeconds, observedLatency);
            }

            // 1) 外推 (限幅：最多外推到"补偿当前实测延迟"，防止飞出去/急停冲过头)
            Pose basePose = model.PredictAt(ClampPredictTime(model, nowSeconds));

            // 2) 叠加当前残差 (还没还完的债)
            Vector3 pos = basePose.position + posResidual;
            Quaternion rot = AnchorMath.Multiply(basePose.rotation, AnchorMath.Exp(rotResidual));
            Pose render = new Pose(pos, rot);

            // 3) 残差衰减 (还债)，按实际帧间隔归一到 60fps 基准帧，保证不同渲染帧率行为一致
            if (hasRendered)
            {
                float dt = (float)(nowSeconds - lastRenderTimeSeconds);
                float frames = Mathf.Max(dt, 0.0f) * 60.0f;
                float decay = Mathf.Pow(Mathf.Clamp(decayPerFrame, 0.5f, 0.99f), frames);
                posResidual *= decay;
                rotResidual *= decay;
            }

            hasRendered = true;
            lastRender = render;
            lastRenderTimeSeconds = nowSeconds;
            return render;
        }

        /// <summary>
        /// 把预测时刻钳到 "最近观测时间 + 外推上限"。外推上限 = 实测延迟 × 倍数，与硬上限取小。
        /// 自适应：延迟越小 (高 fps) 上限越小，永远只外推刚好补偿延迟那么多。
        /// </summary>
        private double ClampPredictTime(MotionModel model, double requestedTime)
        {
            float adaptiveHorizon = latencyEstimateSeconds * Mathf.Max(extrapolationLatencyMultiplier, 0.0f);
            float horizonSeconds = Mathf.Min(adaptiveHorizon, Mathf.Max(maxExtrapolationSecondsHardCap, 0.0f));
            double horizonTime = model.LastObservationTimeSeconds + horizonSeconds;
            return requestedTime > horizonTime ? horizonTime : requestedTime;
        }
    }
}

using System.Collections.Generic;
using EgoAnchor.Tools2.Data;
using EgoAnchor.Tools2.Math;

namespace EgoAnchor.Tools2.Sim
{
    /// <summary>
    /// 流式仿真引擎:严格模拟真实时序,把同一份观测流和 render 流喂给每个算法。
    ///
    /// 核心规则:对每个 render 帧,先提交所有 capture 时间 <= renderTime 的未处理观测,
    /// 再在该 render 时刻预测输出。这与 Unity 的 AcceptPose (测量) -> Advance -> PredictAt (渲染)
    /// 顺序一致,保证 renderTime 总是 >= 最后观测时间,算法必须做真实预测。
    /// </summary>
    public static class Simulator
    {
        /// <summary>
        /// 用指定预测器跑一遍完整 session,返回逐 render 帧的预测轨迹。
        /// </summary>
        /// <param name="predictor">预测算法实例 (调用前会先 Reset)。</param>
        /// <param name="observations">按 capture 时间升序的观测序列。</param>
        /// <param name="renderTicks">按 render 时间升序的 render tick 序列。</param>
        /// <param name="lookaheadSeconds">观测提交的前瞻时间 (秒)。实时预测算法传 0 (render 时刻只提交已到达观测);
        ///   理想插值传正值 (如 0.3) 让它能提前看到下一个"未来"观测,代表零延迟上限。默认 0。</param>
        /// <returns>逐 render 帧的预测样本序列;未收到首个观测前的帧用上一个输出/identity 填充。</returns>
        public static List<PredictSample> Run(
            IAnchorPredictor predictor,
            IReadOnlyList<PoseObservation> observations,
            IReadOnlyList<RenderTick> renderTicks,
            double lookaheadSeconds = 0.0)
        {
            predictor.Reset();

            List<PredictSample> output = new List<PredictSample>(renderTicks.Count);
            int obsIndex = 0;
            // 最近一次有效输出,用于在收到首个观测前填补 (保持 identity)
            Vec3 lastPos = Vec3.Zero;
            QuaternionM lastRot = QuaternionM.Identity;
            double lastObsTime = 0.0;

            foreach (RenderTick tick in renderTicks)
            {
                double renderTime = tick.RenderTimeSeconds;
                // 提交阈值:实时算法用 renderTime;前瞻算法提前看到未来观测
                double submitThreshold = renderTime + lookaheadSeconds;

                // 1. 提交所有 capture 时间 <= submitThreshold 的未处理观测
                while (obsIndex < observations.Count
                    && observations[obsIndex].CaptureTimeSeconds <= submitThreshold)
                {
                    predictor.SubmitObservation(observations[obsIndex]);
                    lastObsTime = observations[obsIndex].CaptureTimeSeconds;
                    obsIndex++;
                }

                // 2. 在当前 render 时刻预测输出
                if (predictor.HasEstimate)
                {
                    (Vec3 pos, QuaternionM rot) = predictor.PredictAt(renderTime);
                    lastPos = pos;
                    lastRot = rot;
                }

                // ahead = renderTime 相对最后已提交观测 (注意前瞻算法的 lastObsTime 可能 > renderTime)
                float ahead = predictor.HasEstimate
                    ? (float)System.Math.Max(renderTime - lastObsTime, 0.0)
                    : 0f;
                output.Add(new PredictSample(renderTime, lastPos, lastRot, ahead));
            }

            return output;
        }
    }
}

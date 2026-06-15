using EgoAnchor.Tools2.Data;
using EgoAnchor.Tools2.Math;

namespace EgoAnchor.Tools2.Predictors
{
    /// <summary>
    /// EgoAnchor 增强预测器:在 CA Kalman 基础上用可靠性分数调节测量噪声 R。
    ///
    /// 实现逻辑:覆盖 ResolvePosition/RotationMeasurementNoise,按 score 放大测量噪声。
    ///   mult = Lerp(1.0, lowScoreNoiseMultiplier, (1 - score)^2)
    ///   posR = PositionMeasurementNoise * mult
    ///   rotR = RotationMeasurementNoise * mult
    /// 低分 -> R 增大 -> Kalman 增益 K = P/(P+R) 减小 -> 更信任预测、少信任噪声测量。
    /// 这是 reliability-aware anchor 的核心机制之一,与 Unity 侧 egoanchor_estimator 的
    /// ReliabilityNoiseMultiplier 一致,但只保留 score 调 R 一种手段,便于纯净对比增益。
    /// 其余结构与 kalman_ca 完全相同。
    /// </summary>
    public sealed class EgoAnchorScoreRPredictor : KalmanCaPredictor
    {
        /// <summary>低分测量放大噪声的倍数上限。</summary>
        private const float LowScoreNoiseMultiplier = 16.0f;

        /// <summary>算法标签。</summary>
        public override string Label => "egoanchor_scoreR";

        /// <summary>重置时把参数收紧到 EgoAnchor 量级 (噪声更小,让分数调节更敏感)。</summary>
        public override void Reset()
        {
            PositionProcessNoise = 0.16f;
            PositionMeasurementNoise = 0.00035f;
            RotationProcessNoise = 0.35f;
            RotationMeasurementNoise = 0.0020f;
            MaxPredictAheadSeconds = 0.16f;
            base.Reset();
        }

        /// <summary>按 score 放大位置测量噪声。</summary>
        protected override float ResolvePositionMeasurementNoise(in PoseObservation observation)
        {
            return PositionMeasurementNoise * ReliabilityNoiseMultiplier(observation.Score);
        }

        /// <summary>按 score 放大旋转测量噪声。</summary>
        protected override float ResolveRotationMeasurementNoise(in PoseObservation observation)
        {
            return RotationMeasurementNoise * ReliabilityNoiseMultiplier(observation.Score);
        }

        /// <summary>
        /// 噪声放大倍数:score=1 时为 1 (信任测量),score=0 时为 LowScoreNoiseMultiplier (16)。
        /// 用 (1-score)^2 的二次曲线,使中高分时影响小、低分时快速放大。
        /// </summary>
        private static float ReliabilityNoiseMultiplier(float score)
        {
            float inverse = 1.0f - AnchorMath.Clamp01(score);
            return AnchorMath.Lerp(1.0f, AnchorMath.Max(LowScoreNoiseMultiplier, 1.0f), inverse * inverse);
        }
    }
}

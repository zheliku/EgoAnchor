using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// 纯透传 (zero-order hold)平滑策略 —— 真正的 raw baseline。
    ///
    /// 不外推、不插值、不升采样：渲染时永远输出"最近一帧观测的去噪 pose"，直到下一帧观测到达
    /// 才跳变。配 ConstantVelocityModel 时 = 最朴素的"原样保持原始观测帧率"对照通道，
    /// 用来对比：升采样到底带来多少平滑改善 (以及不升采样有多卡)。
    ///
    /// 注意：它取的是 model.LatestControlPoint.Pose (= 最近观测时刻的去噪 pose)，
    /// 而不是 PredictAt(now)，所以严格阶梯保持、零外推。配 CV 即为完全未滤波的原始观测保持。
    /// </summary>
    public sealed class RawPassthroughStrategy : SmoothingStrategy
    {
        private bool hasPose;
        private Pose lastPose;

        public override string StrategyName => "raw_passthrough";

        public override void ResetStrategy()
        {
            hasPose = false;
            lastPose = Pose.identity;
        }

        public override void OnObservation(MotionModel model, in AnchorObservation observation)
        {
            // 直接锁存最近控制点 (去噪后的观测 pose)；CV 模型下即原始观测。
            ControlPoint cp = model.LatestControlPoint;
            if (cp.Valid)
            {
                lastPose = cp.Pose;
                hasPose = true;
            }
            else if (observation.HasAlignedPose)
            {
                lastPose = observation.WorldPose;
                hasPose = true;
            }
        }

        public override Pose Output(MotionModel model, double nowSeconds)
        {
            // 零阶保持：与 now 无关，输出最近一帧，不外推。
            if (hasPose)
            {
                return lastPose;
            }

            ControlPoint cp = model.LatestControlPoint;
            return cp.Valid ? cp.Pose : model.PredictAt(model.LastObservationTimeSeconds);
        }
    }
}

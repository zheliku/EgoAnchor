using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// 零阶保持输出策略，用于 RQ2 的 ZOH 系统配置。
    ///
    /// 不外推、不插值、不升采样：渲染时持续输出最近一帧观测 pose，直到下一帧观测到达。
    /// 配合 ConstantVelocityModel 时形成最朴素的零阶保持参照，用于比较完整运行时的
    /// 平滑性与响应代价。它是渲染端系统配置，不等同于日志中的 aligned raw 感知诊断。
    ///
    /// 它读取 model.LatestControlPoint.Pose，而不是 PredictAt(now)，因此保持严格阶梯输出且不外推。
    /// </summary>
    public sealed class RawPassthroughStrategy : SmoothingStrategy
    {
        private bool hasPose;
        private Pose lastPose;
        private double lastPoseTimeSeconds;

        public override string StrategyName => "raw_passthrough";

        public override void ResetStrategy()
        {
            hasPose = false;
            lastPose = Pose.identity;
            lastPoseTimeSeconds = double.NaN;
            OutputTargetTimeSeconds = double.NaN;
        }

        public override void OnObservation(MotionModel model, in AnchorObservation observation)
        {
            // 直接锁存最近控制点 (去噪后的观测 pose)；CV 模型下即原始观测。
            ControlPoint cp = model.LatestControlPoint;
            if (cp.Valid)
            {
                lastPose = cp.Pose;
                lastPoseTimeSeconds = cp.TimeSeconds;
                hasPose = true;
            }
            else if (observation.HasAlignedPose)
            {
                lastPose = observation.WorldPose;
                lastPoseTimeSeconds = observation.MeasurementTimeSeconds;
                hasPose = true;
            }
        }

        public override Pose Output(MotionModel model, double nowSeconds)
        {
            // 零阶保持：与 now 无关，输出最近一帧，不外推。
            if (hasPose)
            {
                OutputTargetTimeSeconds = lastPoseTimeSeconds;
                return lastPose;
            }

            ControlPoint cp = model.LatestControlPoint;
            OutputTargetTimeSeconds = cp.Valid ? cp.TimeSeconds : model.LastObservationTimeSeconds;
            return cp.Valid ? cp.Pose : model.PredictAt(model.LastObservationTimeSeconds);
        }
    }
}

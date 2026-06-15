using EgoAnchor.Tools3.Core;
using EgoAnchor.Tools3.Data;
using EgoAnchor.Tools3.Sim;

namespace EgoAnchor.Tools3.Predictors
{
    /// <summary>
    /// Raw / Zero-Order Hold —— "什么都不处理"基线。
    ///
    /// 逻辑: 收到一帧观测就原样存下;渲染时无论 t 是多少, 都输出最近一帧观测的 pose,
    /// 直到下一帧观测到达才跳变。
    ///
    /// 效果: 渲染轨迹是阶梯状 (staircase), 每 ~200ms 一次硬跳变, 完全不平滑,
    /// 正好作为对照, 显示"不升采样"长什么样。位置和旋转都一样处理。
    /// </summary>
    public sealed class RawZohPredictor : IPredictor
    {
        private Pose lastPose = Pose.Identity;
        private bool hasPose;

        public string Label => "raw_zoh";

        public bool HasEstimate => hasPose;

        public void Reset()
        {
            lastPose = Pose.Identity;
            hasPose = false;
        }

        public void OnObservation(in Observation observation)
        {
            lastPose = observation.Pose;
            hasPose = true;
        }

        public Pose PredictAt(double renderTimeSeconds)
        {
            // 零阶保持: 与时间无关, 永远是最近一帧
            return lastPose;
        }
    }
}

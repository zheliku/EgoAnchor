using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// 不依赖速度切线的自适应历史缓冲策略。
    ///
    /// 目标时刻与 EgoAnchor 的延迟插值一致，均取 render time 减去自适应缓冲延迟；
    /// 对运动模型输出的相邻控制点只做位置线性插值和旋转 SLERP，不使用模型导数，
    /// 因而不会引入速度切线假设或相应的起停过冲参数。
    /// </summary>
    public sealed class LinearSlerpStrategy : HistoricalInterpolationStrategy
    {
        /// <summary>写入评估日志的稳定策略名。</summary>
        public override string StrategyName => "linear_slerp";

        /// <summary>在相邻控制点之间执行位置 Linear 与旋转最短弧 SLERP。</summary>
        protected override Pose Interpolate(
            in ControlPoint first,
            in ControlPoint second,
            float amount,
            float spanSeconds)
        {
            Quaternion alignedSecond = AnchorMath.AlignHemisphere(first.Pose.rotation, second.Pose.rotation);
            return new Pose(
                Vector3.LerpUnclamped(first.Pose.position, second.Pose.position, amount),
                Quaternion.SlerpUnclamped(first.Pose.rotation, alignedSecond, amount));
        }
    }
}

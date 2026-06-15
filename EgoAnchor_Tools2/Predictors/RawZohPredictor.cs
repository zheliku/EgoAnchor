using EgoAnchor.Tools2.Data;
using EgoAnchor.Tools2.Math;
using EgoAnchor.Tools2.Sim;

namespace EgoAnchor.Tools2.Predictors
{
    /// <summary>
    /// 零阶保持 (Zero-Order Hold) 预测器:baseline 下限。
    ///
    /// 实现逻辑:每次收到观测就保存最近一帧 pose,PredictAt 直接返回该 pose,不做任何前推或平滑。
    /// 这相当于"完全不处理",输出是阶梯状,用于对比其他算法的平滑/预测收益。
    /// 对应 Unity 侧 raw_zoh。
    /// </summary>
    public sealed class RawZohPredictor : IAnchorPredictor
    {
        private Vec3 latestPos = Vec3.Zero;
        private QuaternionM latestRot = QuaternionM.Identity;
        private bool hasEstimate;

        /// <summary>算法标签。</summary>
        public string Label => "raw_zoh";

        /// <summary>是否已收到首个观测。</summary>
        public bool HasEstimate => hasEstimate;

        /// <summary>清空状态。</summary>
        public void Reset()
        {
            latestPos = Vec3.Zero;
            latestRot = QuaternionM.Identity;
            hasEstimate = false;
        }

        /// <summary>保存最近观测 pose。</summary>
        public void SubmitObservation(in PoseObservation observation)
        {
            latestPos = observation.Position;
            latestRot = observation.Rotation;
            hasEstimate = true;
        }

        /// <summary>返回最近 pose,不做前推。</summary>
        public (Vec3 position, QuaternionM rotation) PredictAt(double renderTimeSeconds)
        {
            return (latestPos, latestRot);
        }
    }
}

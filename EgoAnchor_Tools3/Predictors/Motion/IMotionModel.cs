using EgoAnchor.Tools3.Core;
using EgoAnchor.Tools3.Data;

namespace EgoAnchor.Tools3.Predictors.Motion
{
    /// <summary>
    /// 运动模型: 从 ~5fps 观测里估计"当前运动状态"(位置/速度, 姿态/角速度), 并能外推到任意时刻。
    ///
    /// 这是「外推 + 残差淡化」管线里可插拔的第一段。它只负责"估计 + 外推", 不负责消跳变——
    /// 消跳变由 ResidualBlendingPredictor 统一处理。三种实现:
    ///   - ConstVelocityMotionModel: 最朴素, 用相邻观测差分估速度;
    ///   - KalmanMotionModel:        常速度 Kalman, 去噪 + 最优速度估计;
    ///   - OneEuroMotionModel:       自适应低通, 去噪 + 平滑速度。
    ///
    /// PredictAt 必须是"纯函数式外推": 给定已吸收的观测, 对任意时刻 t (含过去) 返回模型当时/未来
    /// 会给出的 pose。残差管线要用它查"200ms 前我预测的位置", 所以过去时刻也要能算。
    /// </summary>
    public interface IMotionModel
    {
        string Name { get; }

        void Reset();

        /// <summary>是否已可输出 (至少一帧观测)。</summary>
        bool HasEstimate { get; }

        /// <summary>最近一次吸收的观测时间 (秒)。</summary>
        double LastObservationTime { get; }

        /// <summary>吸收一帧新观测 (~5fps)。</summary>
        void OnObservation(in Observation observation);

        /// <summary>把当前运动状态外推到时刻 t (秒), 返回 pose。t 可在过去或未来。</summary>
        Pose PredictAt(double timeSeconds);
    }
}

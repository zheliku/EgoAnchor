using EgoAnchor.Tools2.Data;
using EgoAnchor.Tools2.Math;

namespace EgoAnchor.Tools2.Sim
{
    /// <summary>
    /// 所有预测算法的统一接口。
    ///
    /// 设计与 Unity 侧 AnchorEstimatorModule 对齐:SubmitObservation 提交低频测量,
    /// PredictAt 在每个高频 render 帧输出预测位姿。两者使用不同时间轴,
    /// 测量用 capture 时间,渲染用 render 时间,从而模拟真实系统的预测延迟隐藏。
    /// </summary>
    public interface IAnchorPredictor
    {
        /// <summary>算法标签,用于日志和画图 (如 raw_zoh、kalman_ca)。</summary>
        string Label { get; }

        /// <summary>是否已积累至少一个观测,可以输出预测。</summary>
        bool HasEstimate { get; }

        /// <summary>重置内部状态,用于同一 session 复跑多个算法。</summary>
        void Reset();

        /// <summary>
        /// 提交一个低频观测 (5fps)。算法在此做测量更新 (滤波校正或状态记录)。
        /// </summary>
        void SubmitObservation(in PoseObservation observation);

        /// <summary>
        /// 在指定 render 时刻输出高频预测位姿 (60fps)。
        /// renderTime 通常 >= 最后一次观测的 capture 时间,因此本质是预测 (predict-ahead)。
        /// </summary>
        (Vec3 position, QuaternionM rotation) PredictAt(double renderTimeSeconds);
    }
}

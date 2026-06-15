using EgoAnchor.Tools3.Core;
using EgoAnchor.Tools3.Data;

namespace EgoAnchor.Tools3.Sim
{
    /// <summary>
    /// 实时预测器接口。这是整个仿真的核心契约, 精确表达需求:
    ///
    ///   - OnObservation: 当一帧新的 ~5fps 观测 pose 到达时调用, 预测器更新内部状态。
    ///   - PredictAt(t): 每个 ~60fps 渲染时刻调用, 返回"在时刻 t 的最佳 pose 估计",
    ///                   只能使用 t 之前已经到达的观测。这是 **实时外推/预测**,
    ///                   绝不是对未来观测点的插值。
    ///
    /// 同一个观测时刻之后、下一个观测到达之前的这 ~200ms 内, PredictAt 会被调用约 12 次,
    /// 每次 t 递增, 输出一条连续平滑的外推曲线;新观测到达后曲线无缝衔接 (各算法自己保证)。
    /// </summary>
    public interface IPredictor
    {
        /// <summary>日志/图例用的算法名。</summary>
        string Label { get; }

        /// <summary>清空状态, 复用同一实例前调用。</summary>
        void Reset();

        /// <summary>新观测到达 (~5fps)。</summary>
        void OnObservation(in Observation observation);

        /// <summary>是否已经可以输出 (至少收到过一帧观测)。</summary>
        bool HasEstimate { get; }

        /// <summary>预测/外推到渲染时刻 t (秒), 只用已到达的观测。</summary>
        Pose PredictAt(double renderTimeSeconds);
    }
}

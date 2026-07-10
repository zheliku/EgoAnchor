using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// 模块 B：平滑策略。每渲染帧调用运动模型，产出最终高频平滑 pose。
    ///
    /// 两个子类是两条不同的设计哲学：
    ///   - BlendStrategy (B 路)：零延迟。调 model.PredictAt(now) 外推 + 残差融合消跳变。
    ///   - DelayedInterpStrategy (C 路)：牺牲 ~一周期延迟。缓冲 model 的控制点，输出 now-Δ 处的插值。
    ///
    /// 继承 MonoBehaviour 的抽象基类，Inspector 只能挂它的子类，与 MotionModel 自由组合 (3×2)。
    /// 策略不持有运动模型——每帧由 host 把当前 model 传进来 (OnObservation / Output)，实现解耦。
    /// </summary>
    public abstract class SmoothingStrategy : MonoBehaviour
    {
        /// <summary>日志/eval 用的策略名。</summary>
        public abstract string StrategyName { get; }

        /// <summary>本策略引入的固有延迟，单位秒 (B 路=0，C 路≈一个观测周期)，仅供诊断。</summary>
        public virtual float NominalLatencySeconds => 0.0f;

        /// <summary>
        /// 最近一次 <see cref="Output"/> 结果对应的观测语义时刻，单位为 Unity 单调时钟秒。
        /// 它描述输出 pose 位于哪一个时间点，不等同于当前渲染时刻或消息到达时刻。
        /// </summary>
        public double OutputTargetTimeSeconds { get; protected set; } = double.NaN;

        /// <summary>清空策略内部状态。</summary>
        public abstract void ResetStrategy();

        /// <summary>
        /// 新观测到达时调用 (已被 host 接受并喂给 model 之后)。策略可在此更新自己的缓冲/残差。
        /// </summary>
        public abstract void OnObservation(MotionModel model, in AnchorObservation observation);

        /// <summary>
        /// 每渲染帧调用，产出最终平滑 pose。model 已有状态时才会被调用。
        /// </summary>
        public abstract Pose Output(MotionModel model, double nowSeconds);
    }
}

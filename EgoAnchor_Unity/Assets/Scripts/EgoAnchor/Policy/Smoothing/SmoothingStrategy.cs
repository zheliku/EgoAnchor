using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>输出策略最近一帧的独立诊断，不复用观测年龄或旧 output residual 字段。</summary>
    public readonly struct SmoothingDiagnostics
    {
        /// <summary>有限因果预测实际使用的预测时域，单位毫秒。</summary>
        public readonly float PredictionHorizonMilliseconds;

        /// <summary>当前帧实际施加的位置校正残差，单位米。</summary>
        public readonly float CorrectionPositionResidualMeters;

        /// <summary>当前帧实际施加的旋转校正残差，单位度。</summary>
        public readonly float CorrectionRotationResidualDegrees;

        /// <summary>因非有限值或渲染时钟回拨而清空连续性状态的累计次数。</summary>
        public readonly long ContinuityResetCount;

        /// <summary>构造一帧输出策略诊断。</summary>
        public SmoothingDiagnostics(
            float predictionHorizonMilliseconds,
            float correctionPositionResidualMeters,
            float correctionRotationResidualDegrees,
            long continuityResetCount)
        {
            PredictionHorizonMilliseconds = predictionHorizonMilliseconds;
            CorrectionPositionResidualMeters = correctionPositionResidualMeters;
            CorrectionRotationResidualDegrees = correctionRotationResidualDegrees;
            ContinuityResetCount = continuityResetCount;
        }

        /// <summary>不提供专用诊断的策略使用的空值。</summary>
        public static SmoothingDiagnostics Empty => new SmoothingDiagnostics(
            float.NaN,
            float.NaN,
            float.NaN,
            0L);
    }

    /// <summary>
    /// 模块 B：平滑策略。每渲染帧调用运动模型，产出最终高频平滑 pose。
    ///
    /// 当前实现包含四条输出路线，全部进入正式 v4 矩阵：
    ///   - HoldStrategy：零阶保持，作为异步候选的原始基线；
    ///   - PredictToNowStrategy：逐渲染帧直接调用运动模型预测；
    ///   - CausalPredictionStrategy：有限时域外推 + 校正残差融合；
    ///   - LinearSlerpStrategy：缓冲控制点，在 now-Δ 做 Linear/SLERP。
    ///
    /// 继承 MonoBehaviour 的抽象基类，Inspector 只能挂它的子类，并与 MotionModel 解耦组合。
    /// 策略不持有运动模型——每帧由 host 把当前 model 传进来 (OnObservation / Output)，实现解耦。
    /// </summary>
    public abstract class SmoothingStrategy : MonoBehaviour
    {
        /// <summary>日志/eval 用的策略名。</summary>
        public abstract string StrategyName { get; }

        /// <summary>写入正式配置哈希的策略参数指纹；无数值参数的策略返回空字符串。</summary>
        public virtual string ConfigurationFingerprint => string.Empty;

        /// <summary>本策略引入的固有延迟，单位秒 (B 路=0，C 路≈一个观测周期)，仅供诊断。</summary>
        public virtual float NominalLatencySeconds => 0.0f;

        /// <summary>最近一帧独立输出策略诊断。</summary>
        public virtual SmoothingDiagnostics Diagnostics => SmoothingDiagnostics.Empty;

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

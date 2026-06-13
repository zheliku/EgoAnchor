using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// Estimator component 基类。
    /// 每个 anchor runtime 只引用一个 estimator module，它负责滤波、升采样和预测。
    /// </summary>
    public abstract class AnchorEstimatorModule : MonoBehaviour
    {
        /// <summary>日志和 eval 使用的模块名。</summary>
        public abstract string ModuleName { get; }

        /// <summary>是否已有可输出估计状态。</summary>
        public abstract bool HasEstimate { get; }

        /// <summary>当前估计线速度，单位米/秒。</summary>
        public virtual Vector3 LinearVelocity => Vector3.zero;

        /// <summary>当前估计角速度，单位 rad/s。</summary>
        public virtual Vector3 AngularVelocityRad => Vector3.zero;

        /// <summary>最近一次接受的可靠性分数。</summary>
        public virtual float LastReliabilityScore => 1.0f;

        /// <summary>
        /// 重定位、首次接受或强校正时直接吸附到测量。
        /// </summary>
        public abstract void Snap(in AnchorObservation observation);

        /// <summary>
        /// 用一帧通过门控的测量更新估计状态。
        /// </summary>
        public abstract void UpdateEstimate(in AnchorObservation observation);

        /// <summary>
        /// 把估计状态预测到指定渲染时间。
        /// </summary>
        public abstract AnchorEstimate PredictAt(double renderTimeSeconds);

        /// <summary>
        /// 清空估计器内部状态。headless 回放会先调用本方法再使用模块。
        /// </summary>
        public abstract void ResetModule();
    }
}

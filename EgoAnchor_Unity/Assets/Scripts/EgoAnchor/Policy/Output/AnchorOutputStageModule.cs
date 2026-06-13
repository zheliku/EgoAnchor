using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// OutputStage component 基类。
    /// 该模块只整形显示输出，不修改 estimator 内部状态。
    /// </summary>
    public abstract class AnchorOutputStageModule : MonoBehaviour
    {
        /// <summary>日志和 eval 使用的模块名。</summary>
        public abstract string ModuleName { get; }

        /// <summary>最近一次输出整形前后的平移残差，单位米。</summary>
        public virtual float LastResidualMeters => 0.0f;

        /// <summary>最近一次输出整形前后的旋转残差，单位度。</summary>
        public virtual float LastResidualDegrees => 0.0f;

        /// <summary>最近一次输出是否被静止锁定。</summary>
        public virtual bool IsStaticLocked => false;

        /// <summary>
        /// 对 estimator 输出做最后显示整形，例如静止锁、限速或直接透传。
        /// </summary>
        public abstract Pose Condition(in AnchorEstimate estimate, double renderTimeSeconds, in OutputContext context);

        /// <summary>
        /// 清空输出模块内部状态。headless 回放会先调用本方法再使用模块。
        /// </summary>
        public abstract void ResetModule();
    }
}

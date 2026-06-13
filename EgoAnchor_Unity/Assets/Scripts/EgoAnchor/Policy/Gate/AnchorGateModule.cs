using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// Gate component 基类。
    /// 该组件直接实现测量门控逻辑；参数写在具体子类 Inspector 字段中。
    /// </summary>
    public abstract class AnchorGateModule : MonoBehaviour
    {
        /// <summary>日志和 eval 使用的模块名。</summary>
        public abstract string ModuleName { get; }

        /// <summary>
        /// 根据当前观测和预测状态决定测量如何进入 estimator。
        /// </summary>
        public abstract GateDecision Evaluate(in AnchorObservation observation, in AnchorEstimate predicted, bool hasEstimate);

        /// <summary>
        /// 清空门控模块内部状态。headless 回放会先调用本方法再使用模块。
        /// </summary>
        public abstract void ResetModule();
    }
}

using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// 直接透传 estimator 输出的 output stage。
    /// </summary>
    public sealed class PassThroughOutputModule : AnchorOutputStageModule
    {
        /// <summary>日志和 eval 使用的模块名。</summary>
        public override string ModuleName => "pass_through";

        /// <summary>不修改 estimator 输出。</summary>
        public override Pose Condition(in AnchorEstimate estimate, double renderTimeSeconds, in OutputContext context)
        {
            return estimate.Pose;
        }

        /// <summary>本模块无内部状态。</summary>
        public override void ResetModule()
        {
        }
    }
}

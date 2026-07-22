using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// 直接使用运动模型预测的逐渲染帧输出策略。
    ///
    /// 每个渲染帧调用 MotionModel.PredictAt(nowSeconds)，不做残差融合、插值或额外
    /// 限幅。该策略用于直接预测机制消融，可与任意 MotionModel 组合，不是零阶保持基线。
    /// </summary>
    public sealed class PredictToNowStrategy : SmoothingStrategy
    {
        /// <summary>日志和评估配置使用的策略名。</summary>
        public override string StrategyName => "predict_to_now";

        /// <summary>清空策略输出时间状态。</summary>
        public override void ResetStrategy()
        {
            OutputTargetTimeSeconds = double.NaN;
        }

        /// <summary>预测策略不需要额外缓存观测。</summary>
        public override void OnObservation(MotionModel model, in AnchorObservation observation)
        {
        }

        /// <summary>在当前渲染时刻直接请求运动模型预测。</summary>
        public override Pose Output(MotionModel model, double nowSeconds)
        {
            if (model == null || !model.HasState)
            {
                OutputTargetTimeSeconds = double.NaN;
                return Pose.identity;
            }

            OutputTargetTimeSeconds = nowSeconds;
            return model.PredictAt(nowSeconds);
        }
    }
}

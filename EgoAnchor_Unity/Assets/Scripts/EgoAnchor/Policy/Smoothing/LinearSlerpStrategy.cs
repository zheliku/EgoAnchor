using System.Collections.Generic;
using System.Globalization;
using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// 不依赖速度切线的自适应历史缓冲策略。
    ///
    /// 目标时刻与 EgoAnchor 的延迟插值一致，均取 render time 减去自适应缓冲延迟；
    /// 对运动模型输出的相邻控制点只做位置线性插值和旋转 SLERP，不使用模型导数，
    /// 因而不会额外引入 Hermite 切线假设或起停过冲参数。
    /// </summary>
    public sealed class LinearSlerpStrategy : SmoothingStrategy
    {
        /// <summary>实测采集到渲染延迟的安全系数，与完整系统保持一致。</summary>
        [Tooltip("自适应历史缓冲的延迟安全系数；与 EgoAnchor 的 HermiteStrategy 保持一致。默认 1.15。")]
        [Range(1.0f, 2.0f)]
        [SerializeField] private float latencySafetyMargin = 1.15f;

        /// <summary>自适应估计稳定前使用的历史缓冲下限，单位秒。</summary>
        [Tooltip("历史缓冲延迟下限，单位秒；与 EgoAnchor 的 HermiteStrategy 保持一致。默认 0.25。")]
        [Range(0.0f, 0.6f)]
        [SerializeField] private float minDelaySeconds = 0.25f;

        private readonly List<ControlPoint> points = new List<ControlPoint>(64);
        private float delaySeconds = 0.25f;
        private float latencyEstimateSeconds;
        private double lastOutputTimeSeconds;

        /// <summary>延迟每秒最多改变 50 ms，避免目标时刻跳变。</summary>
        private const float MaxDelayChangePerSecond = 0.05f;

        /// <summary>写入评估日志的稳定策略名。</summary>
        public override string StrategyName => "linear_slerp";

        /// <summary>参与正式配置哈希的全部缓冲参数。</summary>
        public override string ConfigurationFingerprint => string.Format(
            CultureInfo.InvariantCulture,
            "margin:{0:R}|min:{1:R}",
            latencySafetyMargin,
            minDelaySeconds);

        /// <summary>当前自适应历史缓冲延迟，单位秒。</summary>
        public override float NominalLatencySeconds => delaySeconds;

        /// <summary>清空控制点、延迟估计和输出语义时刻。</summary>
        public override void ResetStrategy()
        {
            points.Clear();
            delaySeconds = Mathf.Max(minDelaySeconds, 0.05f);
            latencyEstimateSeconds = 0.0f;
            lastOutputTimeSeconds = 0.0;
            OutputTargetTimeSeconds = double.NaN;
        }

        /// <summary>缓存 One-Euro 最新滤波控制点，最多保留 64 个。</summary>
        public override void OnObservation(MotionModel model, in AnchorObservation observation)
        {
            ControlPoint point = model.LatestControlPoint;
            if (!point.Valid)
            {
                return;
            }

            points.Add(point);
            if (points.Count > 64)
            {
                points.RemoveRange(0, points.Count - 64);
            }
        }

        /// <summary>在自适应历史目标时刻执行位置 Linear 与旋转 SLERP。</summary>
        public override Pose Output(MotionModel model, double nowSeconds)
        {
            double previousOutputTime = lastOutputTimeSeconds;
            lastOutputTimeSeconds = nowSeconds;
            if (points.Count == 0)
            {
                OutputTargetTimeSeconds = double.NaN;
                return model != null && model.HasState ? model.LatestControlPoint.Pose : Pose.identity;
            }

            if (points.Count == 1)
            {
                OutputTargetTimeSeconds = points[0].TimeSeconds;
                return points[0].Pose;
            }

            float observedLatency = Mathf.Max((float)(nowSeconds - points[points.Count - 1].TimeSeconds), 0.0f);
            latencyEstimateSeconds = AnchorMath.UpdateAsymmetricEma(latencyEstimateSeconds, observedLatency);
            float targetDelay = Mathf.Max(
                latencyEstimateSeconds * Mathf.Clamp(latencySafetyMargin, 1.0f, 2.0f),
                minDelaySeconds);
            float maxDelta = MaxDelayChangePerSecond * Mathf.Max((float)(nowSeconds - previousOutputTime), 0.0f);
            delaySeconds = Mathf.MoveTowards(delaySeconds, targetDelay, maxDelta);
            double target = nowSeconds - delaySeconds;

            if (target <= points[0].TimeSeconds)
            {
                OutputTargetTimeSeconds = points[0].TimeSeconds;
                return points[0].Pose;
            }

            ControlPoint latest = points[points.Count - 1];
            if (target >= latest.TimeSeconds)
            {
                OutputTargetTimeSeconds = latest.TimeSeconds;
                return latest.Pose;
            }

            int index = FindBracket(target);
            ControlPoint first = points[index];
            ControlPoint second = points[index + 1];
            float span = Mathf.Max((float)(second.TimeSeconds - first.TimeSeconds), 1e-6f);
            float amount = Mathf.Clamp01((float)(target - first.TimeSeconds) / span);
            Quaternion alignedSecond = AnchorMath.AlignHemisphere(first.Pose.rotation, second.Pose.rotation);
            OutputTargetTimeSeconds = target;
            return new Pose(
                Vector3.LerpUnclamped(first.Pose.position, second.Pose.position, amount),
                Quaternion.SlerpUnclamped(first.Pose.rotation, alignedSecond, amount));
        }

        /// <summary>从后向前查找包含目标时刻的相邻控制点。</summary>
        private int FindBracket(double target)
        {
            for (int index = points.Count - 2; index >= 0; index--)
            {
                if (points[index].TimeSeconds <= target)
                {
                    return index;
                }
            }

            return 0;
        }
    }
}

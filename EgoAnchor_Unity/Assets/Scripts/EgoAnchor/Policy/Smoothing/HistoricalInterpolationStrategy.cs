using System.Collections.Generic;
using System.Globalization;
using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// 历史缓冲插值策略的公共时间轴实现。
    ///
    /// 子类只定义相邻控制点之间的插值方式；控制点缓存、自适应延迟、目标时刻和
    /// 边界行为由本类统一维护，确保 Linear/SLERP 与 Hermite 使用同一时间线。
    /// </summary>
    public abstract class HistoricalInterpolationStrategy : SmoothingStrategy
    {
        /// <summary>实测采集到渲染延迟的安全系数。</summary>
        [Tooltip("自适应历史缓冲的延迟安全系数。默认 1.15。")]
        [Range(1.0f, 2.0f)]
        [SerializeField] private float latencySafetyMargin = 1.15f;

        /// <summary>自适应估计稳定前使用的历史缓冲下限，单位秒。</summary>
        [Tooltip("历史缓冲延迟下限，单位秒。默认 0.25。")]
        [Range(0.0f, 0.6f)]
        [SerializeField] private float minDelaySeconds = 0.25f;

        /// <summary>最多缓存的控制点数量。</summary>
        private const int MaxControlPoints = 64;

        /// <summary>延迟每秒最多改变 50 ms，避免目标时刻跳变。</summary>
        private const float MaxDelayChangePerSecond = 0.05f;

        private readonly List<ControlPoint> points = new List<ControlPoint>(MaxControlPoints);
        private float delaySeconds = 0.25f;
        private float latencyEstimateSeconds;
        private double lastOutputTimeSeconds;

        /// <summary>参与正式配置哈希的公共缓冲参数。</summary>
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

        /// <summary>缓存运动模型最新控制点，最多保留 64 个。</summary>
        public override void OnObservation(MotionModel model, in AnchorObservation observation)
        {
            if (model == null)
            {
                return;
            }

            ControlPoint point = model.LatestControlPoint;
            if (!point.Valid)
            {
                return;
            }

            points.Add(point);
            if (points.Count > MaxControlPoints)
            {
                points.RemoveRange(0, points.Count - MaxControlPoints);
            }
        }

        /// <summary>在自适应历史目标时刻调用子类的相邻控制点插值。</summary>
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

            ControlPoint latest = points[points.Count - 1];
            float observedLatency = Mathf.Max((float)(nowSeconds - latest.TimeSeconds), 0.0f);
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

            // 缓冲不足时保持最新控制点，不恢复旧 Hermite 的末段外推。
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
            OutputTargetTimeSeconds = target;
            return Interpolate(first, second, amount, span);
        }

        /// <summary>由子类实现相邻控制点之间的 6DoF 插值。</summary>
        protected abstract Pose Interpolate(in ControlPoint first, in ControlPoint second, float amount, float spanSeconds);

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

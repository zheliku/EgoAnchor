using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// 原始 ZOH estimator。
    /// 每次接受测量后保持最近一帧 pose，PredictAt 不做任何前推。
    /// </summary>
    public sealed class RawEstimatorModule : AnchorEstimatorModule
    {
        private Pose latestPose = Pose.identity;
        private double latestTimeSeconds;
        private float latestScore = 1.0f;
        private bool hasEstimate;

        /// <summary>日志和 eval 使用的模块名。</summary>
        public override string ModuleName => "raw_zoh";

        /// <summary>是否已有可输出估计状态。</summary>
        public override bool HasEstimate => hasEstimate;

        /// <summary>最近一次接受的可靠性分数。</summary>
        public override float LastReliabilityScore => latestScore;

        /// <summary>直接贴合到测量。</summary>
        public override void Snap(in AnchorObservation observation)
        {
            Store(observation);
        }

        /// <summary>保存最近测量，不使用 reliability score 改变输出。</summary>
        public override void UpdateEstimate(in AnchorObservation observation)
        {
            Store(observation);
        }

        /// <summary>返回最近测量 pose。</summary>
        public override AnchorEstimate PredictAt(double renderTimeSeconds)
        {
            return new AnchorEstimate(latestPose, Vector3.zero, Vector3.zero, latestTimeSeconds, 1.0f, latestScore);
        }

        /// <summary>清空最近测量。</summary>
        public override void ResetModule()
        {
            latestPose = Pose.identity;
            latestTimeSeconds = 0.0;
            latestScore = 1.0f;
            hasEstimate = false;
        }

        private void Store(in AnchorObservation observation)
        {
            latestPose = observation.WorldPose;
            latestTimeSeconds = MeasurementTime(observation);
            latestScore = observation.ReliabilityScore;
            hasEstimate = true;
        }

        private static double MeasurementTime(in AnchorObservation observation)
        {
            return observation.HasCaptureTime ? observation.CaptureTimeSeconds : observation.SampleTimeSeconds;
        }
    }
}

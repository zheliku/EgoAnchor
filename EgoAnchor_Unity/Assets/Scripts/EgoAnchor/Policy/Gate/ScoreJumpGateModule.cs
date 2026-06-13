using System;
using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// 使用可靠性分数和绝对跳变阈值的门控模块。
    /// 规则直接写在组件中，不委托旧 gate core 或独立 config 对象。
    /// </summary>
    public sealed class ScoreJumpGateModule : AnchorGateModule
    {
        private const int DefaultsVersion = 1;

        /// <summary>首次接受测量需要达到的最低可靠性分数。</summary>
        [Tooltip("首次接受测量需要达到的最低可靠性分数。")]
        [SerializeField] private float startScoreMin = 0.35f;

        /// <summary>已有稳定状态后正常更新需要达到的可靠性分数。</summary>
        [Tooltip("已有稳定状态后正常更新需要达到的可靠性分数。")]
        [SerializeField] private float trackScoreMin = 0.20f;

        /// <summary>低于该分数时拒绝测量，避免低质量 pose 拉动 anchor。</summary>
        [Tooltip("低于该分数时拒绝测量，避免低质量 pose 拉动 anchor。")]
        [SerializeField] private float holdScoreMin = 0.12f;

        /// <summary>重定位测量需要达到的最低可靠性分数。</summary>
        [Tooltip("重定位测量需要达到的最低可靠性分数。")]
        [SerializeField] private float relocalizeScoreMin = 0.12f;

        /// <summary>单帧允许的最大平移跳变，单位米。</summary>
        [Tooltip("单帧允许的最大平移跳变，单位米。")]
        [SerializeField] private float maxJumpMeters = 0.80f;

        /// <summary>单帧允许的最大旋转跳变，单位度。</summary>
        [Tooltip("单帧允许的最大旋转跳变，单位度。")]
        [SerializeField] private float maxJumpDegrees = 120.0f;

        /// <summary>测量到达时间相对采集时间的最大允许年龄，单位秒。</summary>
        [Tooltip("测量到达时间相对采集时间的最大允许年龄，单位秒；超过后拒绝，避免旧 pose 回灌。")]
        [SerializeField] private float maxMeasurementAgeSeconds = 1.0f;

        private int defaultsInitializedVersion = DefaultsVersion;

        /// <summary>日志和 eval 使用的模块名。</summary>
        public override string ModuleName => "score_jump_gate";

        /// <summary>
        /// 根据可靠性分数、硬拒绝 flag 和绝对跳变阈值做门控。
        /// </summary>
        public override GateDecision Evaluate(in AnchorObservation observation, in AnchorEstimate predicted, bool hasEstimate)
        {
            EnsureDefaults();
            if (HasInvalidPoseFlag(observation))
            {
                return GateDecision.Reject("invalid_pose");
            }

            if (!observation.HasAlignedPose && !observation.HasServerPose)
            {
                return GateDecision.Hold("no_pose");
            }

            if (!observation.HasAlignedPose && observation.HasServerPose)
            {
                return GateDecision.Hold("align_failed");
            }

            if (observation.HasCaptureTime
                && observation.SampleTimeSeconds - observation.CaptureTimeSeconds > maxMeasurementAgeSeconds)
            {
                return GateDecision.Reject("stale_measurement");
            }

            float score = Mathf.Clamp01(observation.ReliabilityScore);
            if (observation.IsRelocalization && score >= relocalizeScoreMin)
            {
                return GateDecision.Snap("relocalize_accept");
            }

            if (!hasEstimate)
            {
                return score >= startScoreMin
                    ? GateDecision.Snap("first_accept")
                    : GateDecision.Reject("score_hold");
            }

            if (score < holdScoreMin)
            {
                return GateDecision.Reject("score_hold");
            }

            if (score < trackScoreMin)
            {
                return GateDecision.Hold("score_hold");
            }

            float translation = Vector3.Distance(observation.WorldPose.position, predicted.Pose.position);
            float rotation = AnchorMath.AngleDegrees(predicted.Pose.rotation, observation.WorldPose.rotation);
            if (translation > maxJumpMeters || rotation > maxJumpDegrees)
            {
                return GateDecision.Reject("jump_reject");
            }

            return GateDecision.Accept("score_accept");
        }

        /// <summary>清空内部状态并修复 headless 默认参数。</summary>
        public override void ResetModule()
        {
            EnsureDefaults();
        }

        private static bool HasInvalidPoseFlag(in AnchorObservation observation)
        {
            string[] flags = observation.ReliabilityFlags;
            if (flags == null)
            {
                return false;
            }

            for (int i = 0; i < flags.Length; i++)
            {
                string flag = flags[i] ?? string.Empty;
                if (flag.IndexOf("invalid_pose", StringComparison.OrdinalIgnoreCase) >= 0
                    || flag.IndexOf("no_pose", StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    return true;
                }
            }

            return false;
        }

        private void EnsureDefaults()
        {
            if (defaultsInitializedVersion == DefaultsVersion)
            {
                return;
            }

            startScoreMin = 0.35f;
            trackScoreMin = 0.20f;
            holdScoreMin = 0.12f;
            relocalizeScoreMin = 0.12f;
            maxJumpMeters = 0.80f;
            maxJumpDegrees = 120.0f;
            maxMeasurementAgeSeconds = 1.0f;
            defaultsInitializedVersion = DefaultsVersion;
        }
    }
}

using System;
using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// 测量门控动作。
    /// </summary>
    public enum AnchorGateAction
    {
        /// <summary>接受：测量进入滤波器正常校正。</summary>
        Accept,

        /// <summary>贴合接受：滤波器硬重置到测量位姿（首测量、重定位、瞬移恢复）。</summary>
        AcceptSnap,

        /// <summary>保持：分数处于中间带，本帧不更新滤波器，输出冻结。</summary>
        Hold,

        /// <summary>拒绝：分数过低或跳变超阈，本帧测量被丢弃。</summary>
        Reject,
    }

    /// <summary>
    /// 一次门控判定结果。
    /// </summary>
    public readonly struct AnchorGateResult
    {
        /// <summary>门控动作。</summary>
        public readonly AnchorGateAction Action;

        /// <summary>判定原因。</summary>
        public readonly string Reason;

        /// <summary>本帧位置测量有效噪声（已含可靠性/静止放大），单位 m^2。</summary>
        public readonly float REffPos;

        /// <summary>本帧旋转测量有效噪声（已含可靠性/静止放大），单位 rad^2。</summary>
        public readonly float REffRot;

        /// <summary>本帧 innovation 统计；未走到 innovation 判定时为全零。</summary>
        public readonly InnovationStats Innovation;

        /// <summary>构造门控结果。</summary>
        public AnchorGateResult(AnchorGateAction action, string reason, float rEffPos, float rEffRot, InnovationStats innovation)
        {
            Action = action;
            Reason = reason ?? string.Empty;
            REffPos = rEffPos;
            REffRot = rEffRot;
            Innovation = innovation;
        }
    }

    /// <summary>
    /// 统一测量门控：决定一帧 pose 测量是接受、贴合接受、保持还是拒绝。
    ///
    /// 判定顺序：硬拒绝 flag -> 重定位旁路 -> 首测量 -> 分数滞回 ->
    /// 马氏 innovation（相对滤波器预测位姿与协方差，位置/旋转分别判定，外加绝对兜底）->
    /// 瞬移恢复（连续高分且互相一致的被拒测量达到次数后强制贴合）。
    /// 同时计算按可靠性分与静止状态放大后的有效测量噪声，供滤波器使用。
    /// </summary>
    public sealed class AnchorMeasurementGate
    {
        /// <summary>当前参数包。</summary>
        private AnchorPolicyConfig config;

        /// <summary>是否处于分数接受带内（滞回状态）。</summary>
        private bool inAcceptBand;

        /// <summary>连续一致的高分被拒计数，用于瞬移恢复。</summary>
        private int stuckCount;

        /// <summary>最近一次被跳变门拒绝的 pose。</summary>
        private Pose lastRejectedPose;

        /// <summary>是否已有被拒 pose 记录。</summary>
        private bool hasLastRejected;

        /// <summary>
        /// 构造测量门控。
        /// </summary>
        /// <param name="config">参数包；为空时使用默认参数。</param>
        public AnchorMeasurementGate(AnchorPolicyConfig config = null)
        {
            this.config = config ?? new AnchorPolicyConfig();
        }

        /// <summary>
        /// 热更参数包，不清空滞回与瞬移恢复状态。
        /// </summary>
        /// <param name="newConfig">新的参数包。</param>
        public void ApplyConfig(AnchorPolicyConfig newConfig)
        {
            if (newConfig != null)
            {
                config = newConfig;
            }
        }

        /// <summary>
        /// 清空滞回与瞬移恢复状态。
        /// </summary>
        public void Reset()
        {
            inAcceptBand = false;
            stuckCount = 0;
            hasLastRejected = false;
            lastRejectedPose = Pose.identity;
        }

        /// <summary>
        /// 判定一帧已对齐的 pose 测量。
        /// </summary>
        /// <param name="observation">已完成 frame alignment 的观测。</param>
        /// <param name="filter">当前滤波器，用于读取预测位姿与协方差。</param>
        /// <param name="staticMode">当前是否处于静止模式，影响有效测量噪声。</param>
        /// <param name="measurementTime">测量的 capture 时间，单位秒。</param>
        /// <returns>门控结果。</returns>
        public AnchorGateResult Evaluate(
            in AnchorObservation observation,
            AnchorPoseFilter filter,
            bool staticMode,
            double measurementTime)
        {
            float score = Mathf.Clamp01(observation.ReliabilityScore);
            float trust = Mathf.Clamp(score, config.scoreNoiseFloor, 1f);
            float noiseScale = (staticMode ? config.staticMeasurementNoiseScale : 1f) / (trust * trust);
            float rEffPos = config.positionMeasurementNoise * noiseScale;
            float rEffRot = config.rotationMeasurementNoise * noiseScale;
            InnovationStats none = default;

            if (HasHardRejectFlag(observation))
            {
                return new AnchorGateResult(AnchorGateAction.Reject, "flag_reject", rEffPos, rEffRot, none);
            }

            if (observation.IsRelocalization && score >= config.relocalizeMinScore)
            {
                MarkAccepted();
                return new AnchorGateResult(AnchorGateAction.AcceptSnap, "relocalize_accept", rEffPos, rEffRot, none);
            }

            if (filter == null || !filter.HasState)
            {
                if (score >= config.acceptScoreEnter)
                {
                    MarkAccepted();
                    return new AnchorGateResult(AnchorGateAction.AcceptSnap, "first_accept", rEffPos, rEffRot, none);
                }

                inAcceptBand = false;
                return new AnchorGateResult(AnchorGateAction.Reject, "score_reject", rEffPos, rEffRot, none);
            }

            if (score < config.holdScoreMin)
            {
                inAcceptBand = false;
                return new AnchorGateResult(AnchorGateAction.Reject, "score_reject", rEffPos, rEffRot, none);
            }

            float scoreThreshold = inAcceptBand ? config.acceptScoreStay : config.acceptScoreEnter;
            if (score < scoreThreshold)
            {
                inAcceptBand = false;
                return new AnchorGateResult(AnchorGateAction.Hold, "score_hold", rEffPos, rEffRot, none);
            }

            InnovationStats innovation = filter.EvaluateInnovation(observation.WorldPose, measurementTime, rEffPos, rEffRot);
            string jumpReason = ClassifyJump(in innovation);
            if (jumpReason != null)
            {
                if (score >= config.acceptScoreEnter && TryRecoverFromTeleport(observation.WorldPose))
                {
                    MarkAccepted();
                    return new AnchorGateResult(AnchorGateAction.AcceptSnap, "teleport_recovery", rEffPos, rEffRot, innovation);
                }

                return new AnchorGateResult(AnchorGateAction.Reject, jumpReason, rEffPos, rEffRot, innovation);
            }

            MarkAccepted();
            return new AnchorGateResult(AnchorGateAction.Accept, "score_accept", rEffPos, rEffRot, innovation);
        }

        /// <summary>
        /// 判定 innovation 是否构成跳变；返回拒绝原因，未超阈时返回 null。
        /// </summary>
        private string ClassifyJump(in InnovationStats innovation)
        {
            if (innovation.TranslationMeters > config.maxTranslationJumpMeters)
            {
                return $"translation_jump_{innovation.TranslationMeters:F3}m";
            }

            if (innovation.RotationDegrees > config.maxRotationJumpDegrees)
            {
                return $"rotation_jump_{innovation.RotationDegrees:F1}deg";
            }

            if (innovation.PosD2 > config.innovationPosChi2Gate)
            {
                return $"translation_innovation_d2_{innovation.PosD2:F1}";
            }

            if (innovation.RotD2 > config.innovationRotChi2Gate)
            {
                return $"rotation_innovation_d2_{innovation.RotD2:F1}";
            }

            return null;
        }

        /// <summary>
        /// 瞬移恢复记账：高分被拒测量与最近一次被拒互相一致则累加，
        /// 达到次数即判定"物体真实瞬移并停在新位置"。
        /// </summary>
        /// <param name="candidate">本帧被跳变门拦截的 pose。</param>
        /// <returns>是否触发瞬移恢复。</returns>
        private bool TryRecoverFromTeleport(Pose candidate)
        {
            bool consistent = hasLastRejected
                && Vector3.Distance(candidate.position, lastRejectedPose.position) <= config.stuckConsistencyMeters
                && Quaternion.Angle(candidate.rotation, lastRejectedPose.rotation) <= config.stuckConsistencyDegrees;

            stuckCount = consistent ? stuckCount + 1 : 1;
            lastRejectedPose = candidate;
            hasLastRejected = true;

            if (stuckCount >= config.stuckRecoveryCount)
            {
                stuckCount = 0;
                hasLastRejected = false;
                return true;
            }

            return false;
        }

        /// <summary>
        /// 任意接受后复位滞回与瞬移恢复记账。
        /// </summary>
        private void MarkAccepted()
        {
            inAcceptBand = true;
            stuckCount = 0;
            hasLastRejected = false;
        }

        /// <summary>
        /// 检查观测 flags 是否包含硬拒绝标记（no_pose / invalid_pose），大小写不敏感。
        /// </summary>
        /// <param name="observation">待检查的观测。</param>
        /// <returns>是否命中硬拒绝。</returns>
        public static bool HasHardRejectFlag(in AnchorObservation observation)
        {
            return ContainsFlag(observation.ReliabilityFlags, "no_pose")
                || ContainsFlag(observation.ReliabilityFlags, "invalid_pose");
        }

        /// <summary>
        /// 检查 flags 中是否包含指定片段。
        /// </summary>
        private static bool ContainsFlag(string[] flags, string token)
        {
            if (flags == null || string.IsNullOrEmpty(token))
            {
                return false;
            }

            foreach (string flag in flags)
            {
                if (!string.IsNullOrEmpty(flag) && flag.IndexOf(token, StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    return true;
                }
            }

            return false;
        }
    }
}

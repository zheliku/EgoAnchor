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

        /// <summary>是否要求控制器在校正前退出静止模式。</summary>
        public readonly bool ForceMoving;

        /// <summary>构造门控结果。</summary>
        public AnchorGateResult(
            AnchorGateAction action,
            string reason,
            float rEffPos,
            float rEffRot,
            InnovationStats innovation,
            bool forceMoving = false)
        {
            Action = action;
            Reason = reason ?? string.Empty;
            REffPos = rEffPos;
            REffRot = rEffRot;
            Innovation = innovation;
            ForceMoving = forceMoving;
        }
    }

    /// <summary>
    /// 统一测量门控：决定一帧 pose 测量是接受、贴合接受、保持还是拒绝。
    ///
    /// 判定顺序：硬拒绝 flag -> 重定位旁路 -> 首测量 -> 分数滞回 ->
    /// 静止退出探测 -> 马氏 innovation（相对滤波器预测位姿与协方差，位置/旋转分别判定，
    /// 外加绝对兜底）-> 硬平移瞬移恢复或中等平移/大旋转软恢复。
    /// 同时计算按可靠性分与静止状态放大后的有效测量噪声，供滤波器使用。
    /// </summary>
    public sealed class AnchorMeasurementGate
    {
        /// <summary>当前参数包。</summary>
        private AnchorPolicyConfig config;

        /// <summary>是否处于分数接受带内（滞回状态）。</summary>
        private bool inAcceptBand;

        /// <summary>连续一致的大平移被拒计数，用于瞬移硬恢复。</summary>
        private int teleportRecoveryCount;

        /// <summary>最近一次被平移跳变门拒绝的 pose。</summary>
        private Pose lastTeleportPose;

        /// <summary>是否已有平移跳变被拒 pose 记录。</summary>
        private bool hasLastTeleportPose;

        /// <summary>连续一致的中等跳变被拒计数，用于软恢复。</summary>
        private int softRecoveryCount;

        /// <summary>最近一次被软恢复候选记录的 pose。</summary>
        private Pose lastSoftRecoveryPose;

        /// <summary>是否已有软恢复候选 pose 记录。</summary>
        private bool hasLastSoftRecoveryPose;

        /// <summary>
        /// 构造测量门控。
        /// </summary>
        /// <param name="config">参数包；为空时使用默认参数。</param>
        public AnchorMeasurementGate(AnchorPolicyConfig config = null)
        {
            this.config = config ?? new AnchorPolicyConfig();
        }

        /// <summary>
        /// 热更参数包，不清空滞回与恢复状态。
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
        /// 清空滞回与恢复状态。
        /// </summary>
        public void Reset()
        {
            inAcceptBand = false;
            ResetTeleportRecovery();
            ResetSoftRecovery();
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
            ComputeMeasurementNoise(score, staticMode, out float rEffPos, out float rEffRot);
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
            bool forceMoving = staticMode && ShouldExitStatic(in innovation);
            if (forceMoving)
            {
                ComputeMeasurementNoise(score, staticMode: false, out rEffPos, out rEffRot);
                innovation = filter.EvaluateInnovation(observation.WorldPose, measurementTime, rEffPos, rEffRot);
            }

            JumpClassification jump = ClassifyJump(in innovation);
            if (jump.HasJump)
            {
                if (score >= config.acceptScoreEnter)
                {
                    if (!jump.HasHardJump && IsTrustedMotion(in innovation))
                    {
                        MarkAccepted();
                        string reason = forceMoving ? "motion_start" : "trusted_motion";
                        return new AnchorGateResult(AnchorGateAction.Accept, reason, rEffPos, rEffRot, innovation, forceMoving: true);
                    }

                    if (jump.HardTranslation)
                    {
                        ResetSoftRecovery();
                        if (TryRecoverFromTeleport(observation.WorldPose))
                        {
                            MarkAccepted();
                            return new AnchorGateResult(AnchorGateAction.AcceptSnap, "teleport_recovery", rEffPos, rEffRot, innovation, forceMoving: true);
                        }
                    }
                    else
                    {
                        ResetTeleportRecovery();
                        if (TryRecoverFromSoftMotion(observation.WorldPose))
                        {
                            MarkAccepted();
                            float recoveryRotNoise = jump.HasRotation
                                ? rEffRot * config.softRecoveryRotationNoiseScale
                                : rEffRot;
                            string recoveryReason = jump.HasRotation ? "rotation_recovery" : "motion_recovery";
                            return new AnchorGateResult(AnchorGateAction.Accept, recoveryReason, rEffPos, recoveryRotNoise, innovation, forceMoving: true);
                        }
                    }
                }
                else
                {
                    ResetTeleportRecovery();
                    ResetSoftRecovery();
                }

                return new AnchorGateResult(AnchorGateAction.Reject, jump.Reason, rEffPos, rEffRot, innovation);
            }

            MarkAccepted();
            return new AnchorGateResult(
                AnchorGateAction.Accept,
                forceMoving ? "motion_start" : "score_accept",
                rEffPos,
                rEffRot,
                innovation,
                forceMoving);
        }

        /// <summary>
        /// 按可靠性分与静止状态计算本帧有效测量噪声。
        /// </summary>
        private void ComputeMeasurementNoise(float score, bool staticMode, out float rEffPos, out float rEffRot)
        {
            float trust = Mathf.Clamp(score, config.scoreNoiseFloor, 1f);
            float noiseScale = (staticMode ? config.staticMeasurementNoiseScale : 1f) / (trust * trust);
            rEffPos = config.positionMeasurementNoise * noiseScale;
            rEffRot = config.rotationMeasurementNoise * noiseScale;
        }

        /// <summary>
        /// 静止模式下是否出现足以立即恢复运动跟随的证据。
        /// </summary>
        private bool ShouldExitStatic(in InnovationStats innovation)
        {
            return innovation.PosD2 > config.motionSpikeD2
                || innovation.TranslationMeters > config.staticExitDisplacement
                || innovation.RotationDegrees > config.staticExitRotationDeg;
        }

        /// <summary>
        /// 高分测量若只超过统计门、但绝对变化仍在可信手动运动范围内，直接视为真实运动。
        /// </summary>
        private bool IsTrustedMotion(in InnovationStats innovation)
        {
            return innovation.TranslationMeters <= config.trustedMotionTranslationMeters
                && innovation.RotationDegrees <= config.trustedMotionRotationDegrees;
        }

        /// <summary>
        /// 判定 innovation 是否构成跳变。
        /// </summary>
        private JumpClassification ClassifyJump(in InnovationStats innovation)
        {
            bool hardTranslation = innovation.TranslationMeters > config.maxTranslationJumpMeters;
            bool hardRotation = innovation.RotationDegrees > config.maxRotationJumpDegrees;
            bool translationInnovation = innovation.PosD2 > config.innovationPosChi2Gate;
            bool rotationInnovation = innovation.RotD2 > config.innovationRotChi2Gate;

            if (hardTranslation)
            {
                return new JumpClassification(
                    $"translation_jump_{innovation.TranslationMeters:F3}m",
                    hardTranslation,
                    hardRotation,
                    translationInnovation,
                    rotationInnovation);
            }

            if (hardRotation)
            {
                return new JumpClassification(
                    $"rotation_jump_{innovation.RotationDegrees:F1}deg",
                    hardTranslation,
                    hardRotation,
                    translationInnovation,
                    rotationInnovation);
            }

            if (translationInnovation)
            {
                return new JumpClassification(
                    $"translation_innovation_d2_{innovation.PosD2:F1}",
                    hardTranslation,
                    hardRotation,
                    translationInnovation,
                    rotationInnovation);
            }

            if (rotationInnovation)
            {
                return new JumpClassification(
                    $"rotation_innovation_d2_{innovation.RotD2:F1}",
                    hardTranslation,
                    hardRotation,
                    translationInnovation,
                    rotationInnovation);
            }

            return JumpClassification.None;
        }

        /// <summary>
        /// 跳变分类结果。Reason 只负责诊断文本，控制逻辑使用布尔字段，避免依赖字符串前缀。
        /// </summary>
        private readonly struct JumpClassification
        {
            /// <summary>无跳变结果。</summary>
            public static readonly JumpClassification None = new JumpClassification(string.Empty, false, false, false, false);

            /// <summary>诊断原因。</summary>
            public readonly string Reason;

            /// <summary>是否超过平移绝对跳变阈值。</summary>
            public readonly bool HardTranslation;

            /// <summary>是否超过旋转绝对跳变阈值。</summary>
            public readonly bool HardRotation;

            /// <summary>是否超过平移马氏距离阈值。</summary>
            public readonly bool TranslationInnovation;

            /// <summary>是否超过旋转马氏距离阈值。</summary>
            public readonly bool RotationInnovation;

            /// <summary>是否存在任一跳变。</summary>
            public bool HasJump => HardTranslation || HardRotation || TranslationInnovation || RotationInnovation;

            /// <summary>是否包含任一绝对硬跳变。</summary>
            public bool HasHardJump => HardTranslation || HardRotation;

            /// <summary>是否包含旋转异常。</summary>
            public bool HasRotation => HardRotation || RotationInnovation;

            /// <summary>构造跳变分类。</summary>
            public JumpClassification(
                string reason,
                bool hardTranslation,
                bool hardRotation,
                bool translationInnovation,
                bool rotationInnovation)
            {
                Reason = reason ?? string.Empty;
                HardTranslation = hardTranslation;
                HardRotation = hardRotation;
                TranslationInnovation = translationInnovation;
                RotationInnovation = rotationInnovation;
            }
        }

        /// <summary>
        /// 瞬移恢复记账：高分被拒测量与最近一次被拒互相一致则累加，
        /// 达到次数即判定"物体真实瞬移并停在新位置"。
        /// </summary>
        /// <param name="candidate">本帧被跳变门拦截的 pose。</param>
        /// <returns>是否触发瞬移恢复。</returns>
        private bool TryRecoverFromTeleport(Pose candidate)
        {
            bool consistent = hasLastTeleportPose
                && Vector3.Distance(candidate.position, lastTeleportPose.position) <= config.stuckConsistencyMeters
                && Quaternion.Angle(candidate.rotation, lastTeleportPose.rotation) <= config.stuckConsistencyDegrees;

            teleportRecoveryCount = consistent ? teleportRecoveryCount + 1 : 1;
            lastTeleportPose = candidate;
            hasLastTeleportPose = true;

            if (teleportRecoveryCount >= config.stuckRecoveryCount)
            {
                ResetTeleportRecovery();
                return true;
            }

            return false;
        }

        /// <summary>
        /// 软恢复记账：连续一致的中等平移或大旋转测量达到次数后，不 hard snap，
        /// 而是交给滤波器逐步恢复。
        /// </summary>
        private bool TryRecoverFromSoftMotion(Pose candidate)
        {
            bool consistent = hasLastSoftRecoveryPose
                && Vector3.Distance(candidate.position, lastSoftRecoveryPose.position) <= config.softRecoveryConsistencyMeters
                && Quaternion.Angle(candidate.rotation, lastSoftRecoveryPose.rotation) <= config.softRecoveryConsistencyDegrees;

            softRecoveryCount = consistent ? softRecoveryCount + 1 : 1;
            lastSoftRecoveryPose = candidate;
            hasLastSoftRecoveryPose = true;

            if (softRecoveryCount >= config.softRecoveryCount)
            {
                ResetSoftRecovery();
                return true;
            }

            return false;
        }

        /// <summary>
        /// 清空瞬移恢复记账，避免不同类型外点互相累计。
        /// </summary>
        private void ResetTeleportRecovery()
        {
            teleportRecoveryCount = 0;
            hasLastTeleportPose = false;
            lastTeleportPose = Pose.identity;
        }

        /// <summary>
        /// 清空软恢复记账，避免不同类型外点互相累计。
        /// </summary>
        private void ResetSoftRecovery()
        {
            softRecoveryCount = 0;
            hasLastSoftRecoveryPose = false;
            lastSoftRecoveryPose = Pose.identity;
        }

        /// <summary>
        /// 任意接受后复位滞回、硬瞬移与软恢复记账。
        /// </summary>
        private void MarkAccepted()
        {
            inAcceptBand = true;
            ResetTeleportRecovery();
            ResetSoftRecovery();
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

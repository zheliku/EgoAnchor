using System;
using EgoAnchor.Alignment;
using EgoAnchor.Runtime;
using UnityEngine;

namespace EgoAnchor.Eval
{
    /// <summary>一条 candidate × runtime variant 的 schema-v2 接纳快照。</summary>
    public readonly struct EvalAdmissionSnapshot
    {
        /// <summary>共享 session 标识。</summary>
        public readonly string SessionId;

        /// <summary>Python candidate 稳定标识。</summary>
        public readonly string CandidateId;

        /// <summary>源图像帧号。</summary>
        public readonly long FrameId;

        /// <summary>runtime 变体稳定标识。</summary>
        public readonly string VariantId;

        /// <summary>runtime 变体显示标签。</summary>
        public readonly string VariantLabel;

        /// <summary>处理该 candidate 的 Unity 单调时刻。</summary>
        public readonly double PoseHandleMonoMs;

        /// <summary>处理该 candidate 时的 Unity frame。</summary>
        public readonly int UnityFrame;

        /// <summary>使用的 world alignment 模式。</summary>
        public readonly WorldAlignmentMode AlignmentMode;

        /// <summary>是否使用采集时刻对齐。</summary>
        public readonly bool UsesCaptureTimeAlignment;

        /// <summary>source frame 在 FramePoseHistory 中的 image-time proxy 单调时刻。</summary>
        public readonly double SourceCaptureMonoMs;

        /// <summary>source frame 在 FramePoseHistory 中的 Unity frame。</summary>
        public readonly int SourceCaptureUnityFrame;

        /// <summary>是否得到对齐后的 raw pose。</summary>
        public readonly bool HasAlignedRaw;

        /// <summary>对齐后的 raw pose。</summary>
        public readonly Pose AlignedRawPose;

        /// <summary>是否得到 arrival-time raw 诊断 pose。</summary>
        public readonly bool HasArrivalTimeRaw;

        /// <summary>arrival-time raw 诊断 pose。</summary>
        public readonly Pose ArrivalTimeRawPose;

        /// <summary>arrival-time raw 诊断对应的 Unity 单调时刻。</summary>
        public readonly double ArrivalTimeRawMonoMs;

        /// <summary>是否启用 VCD admission。</summary>
        public readonly bool UsesVcdAdmission;

        /// <summary>连续可靠性分数。</summary>
        public readonly float VcdScore;

        /// <summary>本次输入的 admission 结果，不等同于后续 policy action。</summary>
        public readonly string AdmissionDecision;

        /// <summary>runtime 当前 policy action。</summary>
        public readonly string PolicyAction;

        /// <summary>策略动作原因。</summary>
        public readonly string PolicyReason;

        /// <summary>anchor 状态。</summary>
        public readonly string AnchorState;

        /// <summary>质量门控模式。</summary>
        public readonly string QualityGate;

        /// <summary>当前 motion model 名称。</summary>
        public readonly string MotionModel;

        /// <summary>当前 smoothing strategy 名称。</summary>
        public readonly string SmoothingStrategy;

        /// <summary>是否启用连续时序合成。</summary>
        public readonly bool UsesTemporalSynthesis;

        /// <summary>是否启用显式静止锚定。</summary>
        public readonly bool UsesStaticLock;

        /// <summary>配置摘要 hash。</summary>
        public readonly string ConfigHash;

        /// <summary>实验上下文：实验标识。</summary>
        public readonly string ExperimentId;

        /// <summary>实验上下文：场景标识。</summary>
        public readonly string ScenarioId;

        /// <summary>实验上下文：trial 标识。</summary>
        public readonly string TrialId;

        /// <summary>实验上下文：事件标识。</summary>
        public readonly string EventId;

        /// <summary>实验上下文：条件标识。</summary>
        public readonly string ConditionId;

        /// <summary>构造一条 admission 快照。</summary>
        public EvalAdmissionSnapshot(
            string sessionId,
            string candidateId,
            long frameId,
            string variantId,
            string variantLabel,
            double poseHandleMonoMs,
            int unityFrame,
            WorldAlignmentMode alignmentMode,
            bool usesCaptureTimeAlignment,
            double sourceCaptureMonoMs,
            int sourceCaptureUnityFrame,
            bool hasAlignedRaw,
            Pose alignedRawPose,
            bool hasArrivalTimeRaw,
            Pose arrivalTimeRawPose,
            double arrivalTimeRawMonoMs,
            bool usesVcdAdmission,
            float vcdScore,
            string admissionDecision,
            string policyAction,
            string policyReason,
            string anchorState,
            string qualityGate,
            string motionModel,
            string smoothingStrategy,
            bool usesTemporalSynthesis,
            bool usesStaticLock,
            string configHash,
            string experimentId = "",
            string scenarioId = "",
            string trialId = "",
            string eventId = "",
            string conditionId = "")
        {
            SessionId = sessionId ?? string.Empty;
            CandidateId = candidateId ?? string.Empty;
            FrameId = frameId;
            VariantId = variantId ?? string.Empty;
            VariantLabel = variantLabel ?? string.Empty;
            PoseHandleMonoMs = poseHandleMonoMs;
            UnityFrame = unityFrame;
            AlignmentMode = alignmentMode;
            UsesCaptureTimeAlignment = usesCaptureTimeAlignment;
            SourceCaptureMonoMs = sourceCaptureMonoMs;
            SourceCaptureUnityFrame = sourceCaptureUnityFrame;
            HasAlignedRaw = hasAlignedRaw;
            AlignedRawPose = alignedRawPose;
            HasArrivalTimeRaw = hasArrivalTimeRaw;
            ArrivalTimeRawPose = arrivalTimeRawPose;
            ArrivalTimeRawMonoMs = arrivalTimeRawMonoMs;
            UsesVcdAdmission = usesVcdAdmission;
            VcdScore = vcdScore;
            AdmissionDecision = admissionDecision ?? string.Empty;
            PolicyAction = policyAction ?? string.Empty;
            PolicyReason = policyReason ?? string.Empty;
            AnchorState = anchorState ?? string.Empty;
            QualityGate = qualityGate ?? string.Empty;
            MotionModel = motionModel ?? string.Empty;
            SmoothingStrategy = smoothingStrategy ?? string.Empty;
            UsesTemporalSynthesis = usesTemporalSynthesis;
            UsesStaticLock = usesStaticLock;
            ConfigHash = configHash ?? string.Empty;
            ExperimentId = experimentId ?? string.Empty;
            ScenarioId = scenarioId ?? string.Empty;
            TrialId = trialId ?? string.Empty;
            EventId = eventId ?? string.Empty;
            ConditionId = conditionId ?? string.Empty;
        }
    }
}

using System;
using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// Unity anchor policy 使用的单帧观测。
    ///
    /// 它是 PoseResult 解码和 frame alignment 之后的应用层输入：若 HasAlignedPose=true，
    /// WorldPose 已经是按 frame_id 回查 capture-time camera pose 得到的 Unity world pose；
    /// 若为 false，则表示本帧没有可用于更新 anchor 的 pose，但状态机仍应看到该事件。
    /// CaptureTimeSeconds 是该 frame_id 在 Unity 侧的采集单调时间，用作滤波器的测量时间戳，
    /// 使测量在时间轴上也对齐到 capture 时刻而不是消息到达时刻。
    /// </summary>
    public readonly struct AnchorObservation
    {
        /// <summary>观测对应的 Quest stereo frame_id。</summary>
        public readonly long FrameId;

        /// <summary>观测到达 Unity anchor runtime 的单调时间，单位秒。</summary>
        public readonly double SampleTimeSeconds;

        /// <summary>该 frame_id 的 Unity 采集单调时间，单位秒；小于 0 表示未知。</summary>
        public readonly double CaptureTimeSeconds;

        /// <summary>是否包含成功 frame-aligned 的 Unity world pose。</summary>
        public readonly bool HasAlignedPose;

        /// <summary>frame-aligned Unity world pose；HasAlignedPose=false 时为 Pose.identity。</summary>
        public readonly Pose WorldPose;

        /// <summary>Python 是否报告原始 PoseResult.has_pose=true。</summary>
        public readonly bool HasServerPose;

        /// <summary>Python 感知侧可靠性评分，范围 0..1。</summary>
        public readonly float ReliabilityScore;

        /// <summary>Python 感知侧可靠性 flags。</summary>
        public readonly string[] ReliabilityFlags;

        /// <summary>Python pipeline phase，例如 TRACK、REGISTER、WAIT_DETECT。</summary>
        public readonly string Phase;

        /// <summary>pose 来源，例如 TRACK、REGISTER、RE_REGISTER 或 NONE。</summary>
        public readonly string PoseSource;

        /// <summary>当前观测是否来自 register/re-register 路径。</summary>
        public readonly bool IsRelocalization;

        /// <summary>缺失、拒绝或对齐失败原因。</summary>
        public readonly string FailureReason;

        /// <summary>是否携带有效的采集时间。</summary>
        public bool HasCaptureTime => CaptureTimeSeconds >= 0.0;

        /// <summary>
        /// 构造 anchor policy 观测。
        /// </summary>
        private AnchorObservation(
            long frameId,
            double sampleTimeSeconds,
            double captureTimeSeconds,
            bool hasAlignedPose,
            Pose worldPose,
            bool hasServerPose,
            float reliabilityScore,
            string[] reliabilityFlags,
            string phase,
            string poseSource,
            bool isRelocalization,
            string failureReason)
        {
            FrameId = frameId;
            SampleTimeSeconds = sampleTimeSeconds;
            CaptureTimeSeconds = captureTimeSeconds;
            HasAlignedPose = hasAlignedPose;
            WorldPose = worldPose;
            HasServerPose = hasServerPose;
            ReliabilityScore = Mathf.Clamp01(reliabilityScore);
            ReliabilityFlags = reliabilityFlags ?? Array.Empty<string>();
            Phase = phase ?? string.Empty;
            PoseSource = poseSource ?? string.Empty;
            IsRelocalization = isRelocalization;
            FailureReason = failureReason ?? string.Empty;
        }

        /// <summary>
        /// 从成功对齐的 world pose 构造观测。
        /// </summary>
        /// <param name="frameId">Quest stereo frame_id。</param>
        /// <param name="worldPose">frame-aligned Unity world pose。</param>
        /// <param name="sampleTimeSeconds">观测到达 Unity 的单调时间，单位秒。</param>
        /// <param name="reliabilityScore">Python 感知侧可靠性评分。</param>
        /// <param name="reliabilityFlags">Python 感知侧可靠性 flags。</param>
        /// <param name="phase">Python pipeline phase。</param>
        /// <param name="poseSource">pose 来源。</param>
        /// <param name="captureTimeSeconds">该 frame_id 的 Unity 采集单调时间，单位秒；小于 0 表示未知，将退化用到达时间。</param>
        /// <returns>可交给 AnchorPolicyHost 的观测。</returns>
        public static AnchorObservation FromAlignedPose(
            long frameId,
            Pose worldPose,
            double sampleTimeSeconds,
            float reliabilityScore = 1.0f,
            string[] reliabilityFlags = null,
            string phase = "",
            string poseSource = "",
            double captureTimeSeconds = -1.0)
        {
            return new AnchorObservation(
                frameId,
                sampleTimeSeconds,
                captureTimeSeconds,
                hasAlignedPose: true,
                worldPose,
                hasServerPose: true,
                reliabilityScore,
                reliabilityFlags ?? Array.Empty<string>(),
                phase,
                poseSource,
                IsRegisterLike(phase) || IsRegisterLike(poseSource),
                failureReason: string.Empty
            );
        }

        /// <summary>
        /// 构造 Python 返回 has_pose=false 的观测。
        /// </summary>
        /// <param name="frameId">Quest stereo frame_id。</param>
        /// <param name="sampleTimeSeconds">观测到达 Unity 的单调时间，单位秒。</param>
        /// <param name="failureReason">无 pose 原因。</param>
        /// <param name="phase">Python pipeline phase。</param>
        /// <returns>缺失 pose 观测。</returns>
        public static AnchorObservation MissingPose(long frameId, double sampleTimeSeconds, string failureReason, string phase = "")
        {
            return new AnchorObservation(
                frameId,
                sampleTimeSeconds,
                captureTimeSeconds: -1.0,
                hasAlignedPose: false,
                Pose.identity,
                hasServerPose: false,
                reliabilityScore: 0.0f,
                Array.Empty<string>(),
                phase,
                poseSource: "NONE",
                isRelocalization: false,
                failureReason: failureReason
            );
        }

        /// <summary>
        /// 构造 Unity frame alignment 或协议解析失败的观测。
        /// </summary>
        /// <param name="frameId">Quest stereo frame_id。</param>
        /// <param name="sampleTimeSeconds">观测到达 Unity 的单调时间，单位秒。</param>
        /// <param name="failureReason">对齐或解析失败原因。</param>
        /// <param name="phase">Python pipeline phase。</param>
        /// <returns>无法对齐的 pose 观测。</returns>
        public static AnchorObservation AlignFailed(long frameId, double sampleTimeSeconds, string failureReason, string phase = "")
        {
            return new AnchorObservation(
                frameId,
                sampleTimeSeconds,
                captureTimeSeconds: -1.0,
                hasAlignedPose: false,
                Pose.identity,
                hasServerPose: true,
                reliabilityScore: 0.0f,
                Array.Empty<string>(),
                phase,
                poseSource: "ALIGN_FAILED",
                isRelocalization: false,
                failureReason: failureReason
            );
        }

        /// <summary>
        /// 判断 Python phase/source 文本是否表示 register 或 re-register。
        /// </summary>
        /// <param name="value">Python 侧 phase 或 pose_source。</param>
        /// <returns>是否属于重定位观测。</returns>
        private static bool IsRegisterLike(string value)
        {
            return !string.IsNullOrEmpty(value)
                && value.IndexOf("REGISTER", StringComparison.OrdinalIgnoreCase) >= 0;
        }
    }
}

using System;
using UnityEngine;

namespace EgoAnchor.Anchor
{
    /// <summary>
    /// Unity anchor policy 使用的单帧观测。
    ///
    /// 它是 PoseResult 解码和 frame alignment 之后的应用层输入：若 HasAlignedPose=true，
    /// WorldPose 已经是按 frame_id 回查 capture-time camera pose 得到的 Unity world pose；
    /// 若为 false，则表示本帧没有可用于更新 anchor 的 pose，但状态机仍应看到该事件。
    /// </summary>
    public readonly struct AnchorObservation
    {
        /// <summary>观测对应的 Quest stereo frame_id。</summary>
        public readonly long FrameId;

        /// <summary>观测到达 Unity anchor runtime 的单调时间，单位秒。</summary>
        public readonly double SampleTimeSeconds;

        /// <summary>是否包含成功 frame-aligned 的 Unity world pose。</summary>
        public readonly bool HasAlignedPose;

        /// <summary>frame-aligned Unity world pose；HasAlignedPose=false 时为 Pose.identity。</summary>
        public readonly Pose WorldPose;

        /// <summary>Python 是否报告原始 PoseResult.has_pose=true。</summary>
        public readonly bool HasServerPose;

        /// <summary>Python 感知侧可靠性评分，范围 0..1；旧协议或缺省时为 1。</summary>
        public readonly float ReliabilityScore;

        /// <summary>Python 感知侧可靠性 flags。</summary>
        public readonly string[] ReliabilityFlags;

        /// <summary>Python pipeline phase，例如 TRACK、REGISTER、WAIT_DETECT。</summary>
        public readonly string Phase;

        /// <summary>pose 来源，例如 TRACK、REGISTER、RE_REGISTER 或 NONE。</summary>
        public readonly string PoseSource;

        /// <summary>缺失、拒绝或对齐失败原因。</summary>
        public readonly string FailureReason;

        /// <summary>
        /// 构造 anchor policy 观测。
        /// </summary>
        private AnchorObservation(
            long frameId,
            double sampleTimeSeconds,
            bool hasAlignedPose,
            Pose worldPose,
            bool hasServerPose,
            float reliabilityScore,
            string[] reliabilityFlags,
            string phase,
            string poseSource,
            string failureReason)
        {
            FrameId = frameId;
            SampleTimeSeconds = sampleTimeSeconds;
            HasAlignedPose = hasAlignedPose;
            WorldPose = worldPose;
            HasServerPose = hasServerPose;
            ReliabilityScore = Mathf.Clamp01(reliabilityScore);
            ReliabilityFlags = reliabilityFlags ?? Array.Empty<string>();
            Phase = phase ?? string.Empty;
            PoseSource = poseSource ?? string.Empty;
            FailureReason = failureReason ?? string.Empty;
        }

        /// <summary>
        /// 从成功对齐的 world pose 构造观测。
        /// </summary>
        /// <param name="frameId">Quest stereo frame_id。</param>
        /// <param name="worldPose">frame-aligned Unity world pose。</param>
        /// <param name="sampleTimeSeconds">Unity 单调时间，单位秒。</param>
        /// <param name="reliabilityScore">Python 感知侧可靠性评分。</param>
        /// <param name="reliabilityFlags">Python 感知侧可靠性 flags。</param>
        /// <param name="phase">Python pipeline phase。</param>
        /// <param name="poseSource">pose 来源。</param>
        /// <returns>可交给 AnchorPolicyHost/PolicyController 的观测。</returns>
        public static AnchorObservation FromAlignedPose(
            long frameId,
            Pose worldPose,
            double sampleTimeSeconds,
            float reliabilityScore = 1.0f,
            string[] reliabilityFlags = null,
            string phase = "",
            string poseSource = "")
        {
            return new AnchorObservation(
                frameId,
                sampleTimeSeconds,
                hasAlignedPose: true,
                worldPose,
                hasServerPose: true,
                reliabilityScore,
                reliabilityFlags ?? Array.Empty<string>(),
                phase,
                poseSource,
                failureReason: string.Empty
            );
        }

        /// <summary>
        /// 构造 Python 返回 has_pose=false 的观测。
        /// </summary>
        /// <param name="frameId">Quest stereo frame_id。</param>
        /// <param name="sampleTimeSeconds">Unity 单调时间，单位秒。</param>
        /// <param name="failureReason">无 pose 原因。</param>
        /// <param name="phase">Python pipeline phase。</param>
        /// <returns>缺失 pose 观测。</returns>
        public static AnchorObservation MissingPose(long frameId, double sampleTimeSeconds, string failureReason, string phase = "")
        {
            return new AnchorObservation(
                frameId,
                sampleTimeSeconds,
                hasAlignedPose: false,
                Pose.identity,
                hasServerPose: false,
                reliabilityScore: 0.0f,
                Array.Empty<string>(),
                phase,
                poseSource: "NONE",
                failureReason: failureReason
            );
        }

        /// <summary>
        /// 构造 Unity frame alignment 或协议解析失败的观测。
        /// </summary>
        /// <param name="frameId">Quest stereo frame_id。</param>
        /// <param name="sampleTimeSeconds">Unity 单调时间，单位秒。</param>
        /// <param name="failureReason">对齐或解析失败原因。</param>
        /// <param name="phase">Python pipeline phase。</param>
        /// <returns>无法对齐的 pose 观测。</returns>
        public static AnchorObservation AlignFailed(long frameId, double sampleTimeSeconds, string failureReason, string phase = "")
        {
            return new AnchorObservation(
                frameId,
                sampleTimeSeconds,
                hasAlignedPose: false,
                Pose.identity,
                hasServerPose: true,
                reliabilityScore: 0.0f,
                Array.Empty<string>(),
                phase,
                poseSource: "ALIGN_FAILED",
                failureReason: failureReason
            );
        }
    }
}

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

        /// <summary>深度对齐子分 0..1 (geometry)；用于区分坏 pose vs 真实快动。&lt;0 表示无信号。</summary>
        public readonly float ScoreDepth;

        /// <summary>颜色重投影子分 0..1 (geometry)；用于区分坏 pose vs 真实快动。&lt;0 表示无信号。</summary>
        public readonly float ScoreReprojection;

        /// <summary>连续高质量 pose warmup 置信子分 0..1；刚注册时低。&lt;0 表示无信号。</summary>
        public readonly float ScoreConfidence;

        /// <summary>是否携带有效几何子分 (depth/reprojection)。false 时几何仲裁退化为只看总分。</summary>
        public readonly bool HasSubscores;

        /// <summary>Python 感知侧可靠性 flags。</summary>
        public readonly string[] ReliabilityFlags;

        /// <summary>
        /// 几何证据是否不可信：depth 与 reprojection 子分都 valid 且都低于阈值。
        /// 用于区分"坏 pose / track 丢"(几何差 → 该重 register) vs "真实快动 / 遮挡"(几何仍好 → 别重)。
        /// 无有效子分时返回 false (不武断判坏)。
        /// </summary>
        public bool HasGeometryConcern(float geometryFloor)
        {
            if (!HasSubscores)
            {
                return false;
            }

            bool depthBad = ScoreDepth >= 0f && ScoreDepth < geometryFloor;
            bool reprojBad = ScoreReprojection >= 0f && ScoreReprojection < geometryFloor;
            // 两路几何证据都在且都低，才判几何不可信 (单路低可能只是该路无信号/退化)。
            return depthBad && reprojBad;
        }

        /// <summary>Python pipeline phase，例如 TRACK、REGISTER、WAIT_DETECT。</summary>
        public readonly string Phase;

        /// <summary>pose 来源，例如 TRACK、REGISTER、RE_REGISTER 或 NONE。</summary>
        public readonly string PoseSource;

        /// <summary>当前观测是否来自 register/re-register 路径。</summary>
        public readonly bool IsRelocalization;

        /// <summary>缺失、拒绝或对齐失败原因。</summary>
        public readonly string FailureReason;

        /// <summary>是否携带采集时刻头部 (center camera) world pose，用于头动感知 static。</summary>
        public readonly bool HasHeadPose;

        /// <summary>采集时刻头部 (center camera) world pose；HasHeadPose=false 时为 Pose.identity。
        /// 复用 FramePoseHistory 按 frame_id 记录的 CenterCameraPose，与帧对齐同一份缓存，不重复绑定 CenterEyeAnchor。</summary>
        public readonly Pose HeadPose;

        /// <summary>是否携带有效的采集时间。</summary>
        public bool HasCaptureTime => CaptureTimeSeconds >= 0.0;

        /// <summary>
        /// 该观测在时间轴上的归属时刻，单位秒：优先用 capture 时间 (使测量对齐到采集时刻而非到达时刻)，
        /// 无 capture 时间时退化为到达时间。所有运动模型/平滑策略/host 都应以它作为测量时间戳，
        /// 避免各处重复实现同一段 capture-or-sample 选择逻辑。
        /// </summary>
        public double MeasurementTimeSeconds => HasCaptureTime ? CaptureTimeSeconds : SampleTimeSeconds;

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
            string failureReason,
            bool hasHeadPose = false,
            Pose headPose = default,
            float scoreDepth = -1f,
            float scoreReprojection = -1f,
            float scoreConfidence = -1f,
            bool hasSubscores = false)
        {
            FrameId = frameId;
            SampleTimeSeconds = sampleTimeSeconds;
            CaptureTimeSeconds = captureTimeSeconds;
            HasAlignedPose = hasAlignedPose;
            WorldPose = worldPose;
            HasServerPose = hasServerPose;
            ReliabilityScore = Mathf.Clamp01(reliabilityScore);
            ScoreDepth = scoreDepth;
            ScoreReprojection = scoreReprojection;
            ScoreConfidence = scoreConfidence;
            HasSubscores = hasSubscores;
            ReliabilityFlags = reliabilityFlags ?? Array.Empty<string>();
            Phase = phase ?? string.Empty;
            PoseSource = poseSource ?? string.Empty;
            IsRelocalization = isRelocalization;
            FailureReason = failureReason ?? string.Empty;
            HasHeadPose = hasHeadPose;
            HeadPose = hasHeadPose ? headPose : Pose.identity;
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
            double captureTimeSeconds = -1.0,
            bool hasHeadPose = false,
            Pose headPose = default,
            float scoreDepth = -1f,
            float scoreReprojection = -1f,
            float scoreConfidence = -1f,
            bool hasSubscores = false)
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
                failureReason: string.Empty,
                hasHeadPose,
                headPose,
                scoreDepth,
                scoreReprojection,
                scoreConfidence,
                hasSubscores
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

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

        /// <summary>深度对齐子分 0..1 (D)；用于区分坏 pose vs 真实快动。&lt;0 表示无信号。</summary>
        public readonly float ScoreDepth;

        /// <summary>颜色投影子分 0..1 (C)；用于区分坏 pose vs 真实快动。&lt;0 表示无信号。</summary>
        public readonly float ScoreReprojection;

        /// <summary>depth 子分是否携带有效几何证据 (Python 侧 mask 内深度覆盖足够且有渲染深度信号)。
        /// false 时该路被排除出几何仲裁，而不是当作低分惩罚。</summary>
        public readonly bool DepthValid;

        /// <summary>reprojection 子分是否携带有效几何证据 (Python 侧有颜色重投影信号)。
        /// false 时该路被排除出几何仲裁 (例如纯色/无纹理物体)。</summary>
        public readonly bool ReprojValid;

        /// <summary>是否携带有效几何子分 (depth/reprojection)。false 时几何仲裁退化为只看总分。</summary>
        public readonly bool HasSubscores;

        /// <summary>Python 感知侧可靠性 flags。</summary>
        public readonly string[] ReliabilityFlags;

        /// <summary>
        /// 几何证据是否不可信，用于区分"坏 pose / track 丢"(几何差 → 该重 register)
        /// vs "真实快动 / 遮挡 / 低 confidence"(几何仍好 → 别重 register)。
        ///
        /// 沿用 Python <c>_geometry_core</c> 的加权对数几何平均 (reliability/pose_quality.py)：
        /// 只对 valid 的子分计权 (无信号的一路被排除而非当 0 分)，几何平均分低于 floor 即判不可信。
        /// 这修正了旧的 "depth 与 reproj 都低于 floor 才判" 的缺陷——单路几何彻底失效
        /// (如 depth≈0 而 reproj 尚可) 时，几何平均会被显著拉低，从而正确判定 track 丢。
        /// 两路都无 valid 信号时返回 false (不武断判坏)。
        /// </summary>
        /// <param name="geometryFloor">几何平均分阈值：低于它判几何不可信。</param>
        /// <param name="reprojWeight">reprojection 子分在几何核里的权重，默认 0.2 (同 Python defaults.toml)。</param>
        /// <param name="depthWeight">depth 子分在几何核里的权重，默认 0.8 (同 Python defaults.toml)。</param>
        /// <returns>几何证据是否不可信。</returns>
        public bool HasGeometryConcern(float geometryFloor, float reprojWeight = 0.2f, float depthWeight = 0.8f)
        {
            if (!HasSubscores)
            {
                return false;
            }

            return GeometryScore(reprojWeight, depthWeight, out bool hasEvidence) < geometryFloor && hasEvidence;
        }

        /// <summary>
        /// 按 Python <c>_geometry_core</c> 的加权对数几何平均合成几何质量分 0..1。
        /// 只对 valid 的子分计权；无任何有效几何证据时 hasEvidence=false 且返回 1 (保持当前信任)。
        /// </summary>
        /// <param name="reprojWeight">reprojection 权重。</param>
        /// <param name="depthWeight">depth 权重。</param>
        /// <param name="hasEvidence">是否至少有一路有效几何证据。</param>
        /// <returns>几何质量分 0..1。</returns>
        public float GeometryScore(float reprojWeight, float depthWeight, out bool hasEvidence)
        {
            // 与 Python PoseScoreConfig.geo_floor 一致：避免有效低分在对数几何平均里塌成硬零。
            const float GeoFloor = 0.05f;
            double weightedLogSum = 0.0;
            double weightSum = 0.0;

            if (ReprojValid && ScoreReprojection >= 0f && reprojWeight > 0f)
            {
                float value = Mathf.Max(Mathf.Clamp01(ScoreReprojection), GeoFloor);
                weightedLogSum += reprojWeight * Mathf.Log(value);
                weightSum += reprojWeight;
            }

            if (DepthValid && ScoreDepth >= 0f && depthWeight > 0f)
            {
                float value = Mathf.Max(Mathf.Clamp01(ScoreDepth), GeoFloor);
                weightedLogSum += depthWeight * Mathf.Log(value);
                weightSum += depthWeight;
            }

            if (weightSum <= 0.0)
            {
                hasEvidence = false;
                return 1.0f;
            }

            hasEvidence = true;
            return Mathf.Clamp01((float)System.Math.Exp(weightedLogSum / weightSum));
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
        /// 该观测在运动估计时间轴上的归属时刻，单位秒：优先用 capture 时间
        /// (使测量对齐到采集时刻而非到达时刻)，无 capture 时间时退化为到达时间。
        /// 运动模型、平滑策略和静止锁应使用它计算速度、插值和头动证据。
        /// </summary>
        public double MeasurementTimeSeconds => HasCaptureTime ? CaptureTimeSeconds : SampleTimeSeconds;

        /// <summary>
        /// 该观测在 Unity 本地生命周期时间轴上的到达时刻，单位秒。
        /// 生命周期 stale/lost 与低分持续时间必须使用它，不能用 capture 时间；
        /// 否则 register 推理耗时较长时，高分 pose 一到达就会被误判为陈旧。
        /// </summary>
        public double LifecycleTimeSeconds => SampleTimeSeconds;

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
            bool hasSubscores = false,
            bool depthValid = false,
            bool reprojValid = false)
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
            HasSubscores = hasSubscores;
            DepthValid = depthValid;
            ReprojValid = reprojValid;
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
            bool hasSubscores = false,
            bool depthValid = false,
            bool reprojValid = false)
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
                hasSubscores,
                depthValid,
                reprojValid
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

using System.Collections.Generic;
using EgoAnchor.Protocol.Generated;
using EgoAnchor.Quest;
using UnityEngine;

namespace EgoAnchor.Anchor
{
    /// <summary>
    /// Pose-to-Anchor runtime。
    ///
    /// 这是 Unity Anchor Runtime 的核心组合点：它接收 Python 返回的 camera-space PoseResult，
    /// 调用 CameraPoseFrameAligner 得到 frame-aligned raw world pose，再按处理器链得到 stable pose。
    /// 对齐策略、参考相机选择和实验性固定偏移都集中在这里，避免 DynamicObjectAnchor 或网络层分散修改坐标。
    ///
    /// 当前阶段刻意不实现状态机：has_pose=false 或 frame_id 对齐失败时只更新诊断，
    /// 不清空上一帧输出，也不进入 Lost/Reacquire 等状态。
    /// </summary>
    public sealed class PoseToAnchorRuntime : MonoBehaviour
    {
        /// <summary>接收 PoseResult 后的处理结果，供上层统计和调试。</summary>
        public enum AcceptResult
        {
            /// <summary>pose 有效，且成功按 frame_id 对齐到 Unity world。</summary>
            Aligned,

            /// <summary>Python 明确返回 has_pose=false，本帧不应用 Transform。</summary>
            NoPose,

            /// <summary>pose matrix 缺失或非法。</summary>
            InvalidMatrix,

            /// <summary>frame_id 查不到发送帧 camera pose，或坐标转换失败。</summary>
            AlignFailed,
        }

        /// <summary>frame_id -> capture-time 多参考 camera world pose 缓存。</summary>
        [Header("Frame Alignment")]
        [Tooltip("frame_id -> capture-time left/right/center camera world pose 缓存。必须与 StereoFrameSource/QuestStreamPublisher 使用同一个实例。")]
        [SerializeField] private FramePoseHistory framePoseHistory;

        /// <summary>Unity 本地覆盖的对齐参考相机。</summary>
        [Tooltip("Unity 本地选择的对齐参考相机。Left 是当前 Python pose 的语义默认值；Right/Center/None 仅用于本地对照、补偿或诊断，不需要服务器知道。")]
        [SerializeField] private AnchorPoseReference alignmentReference = AnchorPoseReference.Left;

        /// <summary>camera-local 轴翻转和 frame-aligned 后固定偏移的统一配置。</summary>
        [Tooltip("camera-local 轴翻转和 frame-aligned 后固定偏移的统一配置。测试鼠标模型时可直接关闭 Flip Y，而不需要修改代码。")]
        [SerializeField] private AnchorPoseTransform poseTransform = AnchorPoseTransform.OpenCvToUnityDefault;

        /// <summary>是否启用 stable pose 处理器链。</summary>
        [Header("Anchor Processors")]
        [Tooltip("是否启用 stable pose 处理器链。关闭时 stable 输出直接等于 raw，便于最小链路调试。")]
        [SerializeField] private bool enableProcessors = true;

        /// <summary>按顺序处理 raw world pose 的处理器列表。</summary>
        [Tooltip("按顺序处理 frame-aligned raw world pose 的处理器列表。例如只放 Kalman，或 Kalman 后接轻量 LowPass。为空时 stable 直接等于 raw。")]
        [SerializeField] private List<AnchorPoseProcessor> processors = new List<AnchorPoseProcessor>();

        /// <summary>是否保留 Inspector 诊断。</summary>
        [Header("Debug")]
        [Tooltip("是否在 Inspector 中暴露最近一次处理诊断。")]
        [SerializeField] private bool keepDiagnostics = true;

        /// <summary>最近成功对齐的 frame_id。</summary>
        [Tooltip("最近成功对齐的 frame_id。只用于 Inspector/日志诊断。")]
        [SerializeField] private long latestAlignedFrameId = -1;

        /// <summary>最近一次 PoseResult phase。</summary>
        [Tooltip("最近一次 PoseResult phase。只用于 Inspector/日志诊断。")]
        [SerializeField] private string latestPhase = "";

        /// <summary>最近一次失败原因。</summary>
        [Tooltip("最近一次失败原因。空字符串表示最近一次处理没有失败。")]
        [SerializeField] private string latestFailure = "";

        /// <summary>最近一次实际使用的对齐参考相机。</summary>
        [Tooltip("最近一次实际使用的对齐参考相机。用于确认当前是 Left/Right/Center/None 哪一种对齐。")]
        [SerializeField] private AnchorPoseReference latestUsedReference = AnchorPoseReference.Left;

        /// <summary>frame-aligned 坐标转换器。</summary>
        private CameraPoseFrameAligner aligner;

        /// <summary>最近一次成功对齐的 raw world pose。</summary>
        private Pose rawPose;

        /// <summary>最近一次处理器链输出的 stable world pose。</summary>
        private Pose stablePose;

        /// <summary>是否已有 raw pose。</summary>
        private bool hasRawPose;

        /// <summary>是否已有 stable pose。</summary>
        private bool hasStablePose;

        /// <summary>最近成功对齐的 frame_id。</summary>
        public long LatestAlignedFrameId => latestAlignedFrameId;

        /// <summary>最近一次 PoseResult phase。</summary>
        public string LatestPhase => latestPhase;

        /// <summary>最近一次失败原因。</summary>
        public string LatestFailure => latestFailure;

        /// <summary>最近一次实际使用的对齐参考相机。</summary>
        public AnchorPoseReference LatestUsedReference => latestUsedReference;

        /// <summary>
        /// Unity Awake：构造 frame aligner。
        /// </summary>
        private void Awake()
        {
            RebuildAligner();
        }

        /// <summary>
        /// Inspector 修改时确保列表非空。
        /// </summary>
        private void OnValidate()
        {
            if (processors == null)
            {
                processors = new List<AnchorPoseProcessor>();
            }

            RebuildAligner();
        }

        /// <summary>
        /// 接收并处理一条 Python 发布的 camera-space PoseResult。
        /// </summary>
        /// <param name="result">Python 发布的 PoseResult。</param>
        /// <returns>本条结果的处理状态。</returns>
        public AcceptResult AcceptPoseResult(PoseResult result)
        {
            if (result == null || result.Header == null)
            {
                SetFailure("empty_pose_result");
                return AcceptResult.AlignFailed;
            }

            latestPhase = result.Phase ?? string.Empty;
            if (!result.HasPose)
            {
                SetFailure(string.IsNullOrEmpty(result.LastError?.Code) ? "no_pose" : result.LastError.Code);
                return AcceptResult.NoPose;
            }

            if (result.PoseMatrixCvCamera == null || result.PoseMatrixCvCamera.Values == null || result.PoseMatrixCvCamera.Values.Count != 16)
            {
                SetFailure("invalid_matrix");
                return AcceptResult.InvalidMatrix;
            }

            if (aligner == null)
            {
                RebuildAligner();
            }

            if (aligner == null || !aligner.TryAlign(result, out Pose worldPose, out AnchorPoseReference usedReference))
            {
                SetFailure($"align_failed_frame_{result.Header.FrameId}");
                return AcceptResult.AlignFailed;
            }

            latestUsedReference = usedReference;
            AcceptWorldPose(result.Header.FrameId, worldPose);
            latestFailure = string.Empty;
            return AcceptResult.Aligned;
        }

        /// <summary>
        /// 尝试获取当前 raw anchor pose，不经过任何平滑。
        /// </summary>
        /// <param name="pose">当前 raw world pose。</param>
        /// <returns>是否已有 raw pose。</returns>
        public bool TryGetRawPose(out Pose pose)
        {
            pose = rawPose;
            return hasRawPose;
        }

        /// <summary>
        /// 尝试获取当前稳定 anchor pose。
        /// 当前 stable 等于 processor chain 输出；若关闭处理器链，则 stable 直接等于 raw。
        /// </summary>
        /// <param name="pose">当前 stable world pose。</param>
        /// <returns>是否已有 stable/raw pose。</returns>
        public bool TryGetStablePose(out Pose pose)
        {
            if (enableProcessors)
            {
                pose = stablePose;
                return hasStablePose;
            }

            return TryGetRawPose(out pose);
        }

        /// <summary>
        /// 外部测试可直接注入 world pose，绕过 NATS/Protobuf/frame history。
        /// </summary>
        /// <param name="frameId">该 world pose 对应的 frame_id。</param>
        /// <param name="worldPose">Unity world 坐标 pose。</param>
        public void AcceptWorldPose(long frameId, Pose worldPose)
        {
            rawPose = worldPose;
            hasRawPose = true;
            latestAlignedFrameId = frameId;

            double now = Time.realtimeSinceStartupAsDouble;
            stablePose = RunProcessors(worldPose, frameId, now);
            hasStablePose = true;
        }

        /// <summary>
        /// 重置所有 anchor pose processor 的内部状态。
        /// </summary>
        public void ResetProcessors()
        {
            if (processors == null)
            {
                return;
            }

            foreach (AnchorPoseProcessor processor in processors)
            {
                if (processor != null)
                {
                    processor.ResetProcessor();
                }
            }
            hasStablePose = false;
        }

        /// <summary>
        /// 清空当前 raw/stable anchor pose 状态。
        ///
        /// 该方法用于 Unity 收到 Python reset command accepted 后，按需清理本地可视化状态。
        /// Python reset 只会重置外部 pose 估计 pipeline；Unity 侧上一帧 raw/stable pose 和滤波器需要由本方法显式清理。
        /// </summary>
        /// <param name="clearProcessors">是否同时重置处理器内部状态。</param>
        public void ClearPoseState(bool clearProcessors = true)
        {
            hasRawPose = false;
            hasStablePose = false;
            latestAlignedFrameId = -1;
            latestPhase = string.Empty;
            latestFailure = "cleared_by_command";

            if (clearProcessors)
            {
                ResetProcessors();
            }
        }

        /// <summary>
        /// 按配置顺序运行处理器链。
        /// </summary>
        private Pose RunProcessors(Pose inputPose, long frameId, double sampleTime)
        {
            if (!enableProcessors || processors == null || processors.Count == 0)
            {
                return inputPose;
            }

            Pose current = inputPose;
            foreach (AnchorPoseProcessor processor in processors)
            {
                if (processor == null)
                {
                    continue;
                }

                current = processor.Process(current, frameId, sampleTime);
            }
            return current;
        }

        /// <summary>
        /// 重新构造 frame aligner。
        /// </summary>
        private void RebuildAligner()
        {
            aligner = framePoseHistory != null || alignmentReference == AnchorPoseReference.None
                ? new CameraPoseFrameAligner(framePoseHistory, alignmentReference, poseTransform)
                : null;
            if (aligner == null && keepDiagnostics)
            {
                latestFailure = "missing_frame_pose_history";
            }
        }

        /// <summary>
        /// 写入最近失败原因。
        /// </summary>
        private void SetFailure(string reason)
        {
            if (keepDiagnostics)
            {
                latestFailure = reason;
            }
        }
    }

}



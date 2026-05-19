using EgoAnchor.Protocol.V1;
using EgoAnchor.V2.Quest;
using System.Collections.Generic;
using UnityEngine;

namespace EgoAnchor.V2.Anchor
{
    /// <summary>
    /// v2 Pose-to-Anchor runtime。
    ///
    /// 这是 Unity v2 Anchor Runtime 的核心组合点：它接收 Python 返回的相机坐标系 pose observation，
    /// 调用 frame aligner 得到 raw world pose，再进入 reliability gate / filter / state machine，
    /// 最终输出可应用到 Transform 的稳定 world anchor pose。
    ///
    /// 注意：本类不负责网络订阅、不解码 Protobuf、不直接读 Quest camera；这些输入应由 Client/Quest 层提供。
    ///
    /// 当前职责：
    /// - 接收 PoseResult observation。
    /// - 调用 CameraPoseFrameAligner 得到 raw world anchor pose。
    /// - 同时维护 raw pose 和 processor chain 输出的 stable pose，便于论文 baseline 对照。
    ///
    /// 本阶段刻意不实现状态机：has_pose=false 或 frame_id 对齐失败时只更新诊断，
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

        [Header("Frame Alignment")]
        [Tooltip("frame_id -> capture-time left camera world pose 缓存。必须与 StereoFrameSource/QuestStreamPublisher 使用同一个实例。")]
        [SerializeField] private FramePoseHistory framePoseHistory;

        [Header("Anchor Processors")]
        [Tooltip("是否启用 stable pose 处理器链。关闭时 stable 输出直接等于 raw，便于最小链路调试。")]
        [SerializeField] private bool enableProcessors = true;

        [Tooltip("按顺序处理 frame-aligned raw world pose 的处理器列表。例如只放 Kalman，或 Kalman 后接轻量 LowPass。为空时 stable 直接等于 raw。")]
        [SerializeField] private List<AnchorPoseProcessor> processors = new List<AnchorPoseProcessor>();

        [Header("Debug")]
        [Tooltip("是否在 Inspector 中暴露最近一次处理诊断。")]
        [SerializeField] private bool keepDiagnostics = true;

        [Tooltip("最近成功对齐的 frame_id。只用于 Inspector/日志诊断。")]
        [SerializeField] private long latestAlignedFrameId = -1;

        [Tooltip("最近一次 PoseResult phase。只用于 Inspector/日志诊断。")]
        [SerializeField] private string latestPhase = "";

        [Tooltip("最近一次失败原因。空字符串表示最近一次处理没有失败。")]
        [SerializeField] private string latestFailure = "";

        private CameraPoseFrameAligner _aligner;
        private Pose _rawPose;
        private Pose _stablePose;
        private bool _hasRawPose;
        private bool _hasStablePose;

        /// <summary>最近成功对齐的 frame_id。</summary>
        public long LatestAlignedFrameId => latestAlignedFrameId;

        /// <summary>最近一次 PoseResult phase。</summary>
        public string LatestPhase => latestPhase;

        /// <summary>最近一次失败原因。</summary>
        public string LatestFailure => latestFailure;

        private void Awake()
        {
            RebuildAligner();
        }

        private void OnValidate()
        {
            if (processors == null)
            {
                processors = new List<AnchorPoseProcessor>();
            }
        }

        /// <summary>
        /// 接收并处理一条 Python 发布的 camera-space PoseResult。
        /// </summary>
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

            if (_aligner == null)
            {
                RebuildAligner();
            }

            if (_aligner == null || !_aligner.TryAlign(result, out Pose worldPose))
            {
                SetFailure($"align_failed_frame_{result.Header.FrameId}");
                return AcceptResult.AlignFailed;
            }

            AcceptWorldPose(result.Header.FrameId, worldPose);
            latestFailure = string.Empty;
            return AcceptResult.Aligned;
        }

        /// <summary>
        /// 尝试获取当前 raw anchor pose，不经过任何平滑。
        /// </summary>
        public bool TryGetRawPose(out Pose pose)
        {
            pose = _rawPose;
            return _hasRawPose;
        }

        /// <summary>
        /// 尝试获取当前稳定 anchor pose。
        /// 当前 stable 等于 processor chain 输出；若关闭处理器链，则 stable 直接等于 raw。
        /// </summary>
        public bool TryGetStablePose(out Pose pose)
        {
            if (enableProcessors)
            {
                pose = _stablePose;
                return _hasStablePose;
            }

            return TryGetRawPose(out pose);
        }

        /// <summary>
        /// 外部测试可直接注入 world pose，绕过 NATS/Protobuf/frame history。
        /// </summary>
        public void AcceptWorldPose(long frameId, Pose worldPose)
        {
            _rawPose = worldPose;
            _hasRawPose = true;
            latestAlignedFrameId = frameId;

            double now = Time.realtimeSinceStartupAsDouble;
            _stablePose = RunProcessors(worldPose, frameId, now);
            _hasStablePose = true;
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
            _hasStablePose = false;
        }

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

        private void RebuildAligner()
        {
            _aligner = framePoseHistory != null ? new CameraPoseFrameAligner(framePoseHistory) : null;
            if (_aligner == null && keepDiagnostics)
            {
                latestFailure = "missing_frame_pose_history";
            }
        }

        private void SetFailure(string reason)
        {
            if (keepDiagnostics)
            {
                latestFailure = reason;
            }
        }
    }
}

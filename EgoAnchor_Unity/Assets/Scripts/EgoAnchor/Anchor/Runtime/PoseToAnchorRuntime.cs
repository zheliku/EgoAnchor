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
    /// reliability-aware policy 可把低可靠 pose、跳变和短时缺失转化为 Hold/Coast/Lost 等
    /// anchor 行为；关闭 policy 时仍保留 raw + processor chain baseline，便于论文对照。
    /// </summary>
    public sealed partial class PoseToAnchorRuntime : MonoBehaviour
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
        [SerializeField] private CameraReference alignmentReference = CameraReference.Left;

        /// <summary>camera-local 轴翻转和 frame-aligned 后固定偏移的统一配置。</summary>
        [Tooltip("camera-local 轴翻转和 frame-aligned 后固定偏移的统一配置。测试鼠标模型时可直接关闭 Flip Y，而不需要修改代码。")]
        [SerializeField] private AnchorPoseTransform poseTransform = AnchorPoseTransform.OpenCvToUnityDefault;

        [Header("Anchor Processors")]
        /// <summary>按顺序处理 raw world pose 的处理器列表。</summary>
        [Tooltip("按顺序处理 frame-aligned raw world pose 的处理器列表。例如只放 Kalman，或 Kalman 后接轻量 LowPass。为空时 stable 直接等于 raw。")]
        [SerializeField] private List<AnchorPoseProcessor> processors = new List<AnchorPoseProcessor>();

        [Header("Reliability Policy")]
        /// <summary>可选 reliability-aware anchor policy 宿主。</summary>
        [Tooltip("可选 reliability-aware anchor policy 宿主。绑定后低分 pose、跳变和短时缺失会进入 Reject/Hold/Coast/Lost；为空时保持 raw + processor baseline。")]
        [SerializeField] private AnchorPolicyHostBase policyHost;

        [Header("Debug")]
        [Tooltip("PoseToAnchorRuntime 最近一次处理诊断。")]
        [SerializeField] private RuntimeDiagnostics diagnostics = new RuntimeDiagnostics();

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
        public long LatestAlignedFrameId => diagnostics.latestAlignedFrameId;

        /// <summary>最近一次 PoseResult phase。</summary>
        public string LatestPhase => diagnostics.latestPhase;

        /// <summary>最近一次失败原因。</summary>
        public string LatestFailure => diagnostics.latestFailure;

        /// <summary>最近一次实际使用的对齐参考相机。</summary>
        public CameraReference LatestUsedReference => diagnostics.latestUsedReference;

        /// <summary>当前 Unity anchor 生命周期状态。</summary>
        public AnchorState CurrentAnchorState => diagnostics.currentAnchorState;

        /// <summary>最近一次 anchor policy 动作。</summary>
        public string LatestPolicyAction => diagnostics.latestPolicyAction;

        /// <summary>最近一次 anchor policy 原因。</summary>
        public string LatestPolicyReason => diagnostics.latestPolicyReason;

        /// <summary>最近一次 reliability score。</summary>
        public float LatestReliabilityScore => diagnostics.latestReliabilityScore;

        /// <summary>最近一次 Python AnchorStatusEvent.state。</summary>
        public string LatestServerState => diagnostics.latestServerState;

        /// <summary>最近一次 Python AnchorStatusEvent.event。</summary>
        public string LatestServerEvent => diagnostics.latestServerEvent;

        /// <summary>最近一次 ServerHeartbeat.input_ready。</summary>
        public bool LatestHeartbeatInputReady => diagnostics.latestHeartbeatInputReady;

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

            diagnostics.latestPhase = result.Phase ?? string.Empty;
            diagnostics.latestReliabilityScore = ReadReliabilityScore(result);
            double now = Time.realtimeSinceStartupAsDouble;
            if (!result.HasPose)
            {
                string reason = string.IsNullOrEmpty(result.LastError?.Code) ? "no_pose" : result.LastError.Code;
                SetFailure(reason);
                NotifyMissingPose(result.Header.FrameId, now, reason, diagnostics.latestPhase);
                return AcceptResult.NoPose;
            }

            if (result.PoseMatrixCvCamera == null || result.PoseMatrixCvCamera.Values == null || result.PoseMatrixCvCamera.Values.Count != 16)
            {
                SetFailure("invalid_matrix");
                NotifyAlignFailure(result.Header.FrameId, now, "invalid_matrix", diagnostics.latestPhase);
                return AcceptResult.InvalidMatrix;
            }

            if (aligner == null)
            {
                RebuildAligner();
            }

            if (aligner == null || !aligner.TryAlign(result, out Pose worldPose, out CameraReference usedReference))
            {
                string reason = $"align_failed_frame_{result.Header.FrameId}";
                SetFailure(reason);
                NotifyAlignFailure(result.Header.FrameId, now, reason, diagnostics.latestPhase);
                return AcceptResult.AlignFailed;
            }

            diagnostics.latestUsedReference = usedReference;
            AcceptWorldPose(result.Header.FrameId, worldPose, result, now);
            diagnostics.latestFailure = string.Empty;
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
            pose = stablePose;
            return hasStablePose;
        }

        /// <summary>
        /// 外部测试可直接注入 world pose，绕过 NATS/Protobuf/frame history。
        /// </summary>
        /// <param name="frameId">该 world pose 对应的 frame_id。</param>
        /// <param name="worldPose">Unity world 坐标 pose。</param>
        public void AcceptWorldPose(long frameId, Pose worldPose)
        {
            AcceptWorldPose(frameId, worldPose, null, Time.realtimeSinceStartupAsDouble);
        }

        /// <summary>
        /// 接收已完成 frame alignment 的 world pose，并按配置运行 baseline 或 reliability-aware policy。
        /// </summary>
        /// <param name="frameId">该 world pose 对应的 frame_id。</param>
        /// <param name="worldPose">Unity world 坐标 pose。</param>
        /// <param name="sourceResult">源 PoseResult；测试直接注入时可为空。</param>
        /// <param name="sampleTime">当前 Unity 单调时间，单位秒。</param>
        private void AcceptWorldPose(long frameId, Pose worldPose, PoseResult sourceResult, double sampleTime)
        {
            rawPose = worldPose;
            hasRawPose = true;
            diagnostics.latestAlignedFrameId = frameId;

            if (policyHost != null)
            {
                AnchorObservation observation = AnchorObservation.FromAlignedPose(
                    frameId,
                    worldPose,
                    sampleTime,
                    ReadReliabilityScore(sourceResult),
                    ReadReliabilityFlags(sourceResult),
                    sourceResult?.Phase ?? diagnostics.latestPhase,
                    sourceResult?.PoseSource ?? string.Empty
                );
                AnchorPolicyDecision decision = policyHost.AcceptPose(observation);
                ApplyPolicyDecision(decision, frameId);
            }
            else
            {
                stablePose = RunProcessors(worldPose, frameId, sampleTime);
                hasStablePose = true;
                diagnostics.currentAnchorState = AnchorState.Tracking;
                diagnostics.latestPolicyAction = "baseline_accept";
                diagnostics.latestPolicyReason = "policy_disabled";
            }
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
        /// 按配置顺序运行处理器链。
        /// </summary>
        private Pose RunProcessors(Pose inputPose, long frameId, double sampleTime)
        {
            if (processors == null || processors.Count == 0)
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
            aligner = framePoseHistory != null || alignmentReference == CameraReference.None
                ? new CameraPoseFrameAligner(framePoseHistory, alignmentReference, poseTransform)
                : null;
            if (aligner == null)
            {
                diagnostics.latestFailure = "missing_frame_pose_history";
            }
        }

        /// <summary>
        /// 写入最近失败原因。
        /// </summary>
        private void SetFailure(string reason)
        {
            diagnostics.latestFailure = reason;
        }
    }

}

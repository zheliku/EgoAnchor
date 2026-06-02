using System;
using System.Collections.Generic;
using System.Linq;
using EgoAnchor.Alignment;
using EgoAnchor.Policy;
using EgoAnchor.Processors;
using EgoAnchor.Protocol.Generated;
using UnityEngine;

namespace EgoAnchor.Runtime
{
    /// <summary>
    /// Pose-to-Anchor runtime。
    ///
    /// 这是 Unity Anchor Runtime 的核心组合点：它接收 Python 返回的 camera-space PoseResult，
    /// 调用 CameraPoseFrameAligner 得到 frame-aligned raw world pose，再按处理器链得到 stable pose。
    /// 对齐策略、参考相机选择和三路 pose 补偿都集中在这里，避免 DynamicObjectAnchor 或网络层分散修改坐标。
    ///
    /// reliability-aware policy 可把低可靠 pose、跳变和短时缺失转化为 Hold/Coast/Lost 等
    /// anchor 行为；关闭 policy 时仍保留 raw + processor chain baseline，便于论文对照。
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
        [SerializeField] private CameraReference alignmentReference = CameraReference.Left;

        /// <summary>camera-local 轴翻转和 camera/anchor/world 三路 pose 补偿的统一配置。</summary>
        [Tooltip("camera-local 轴翻转和 camera/anchor/world 三路 pose 补偿的统一配置。测试鼠标模型时可直接关闭 Flip Y，或在 Position/Rotation Offsets 中叠加三种补偿。")]
        [SerializeField] private AnchorPoseTransform poseTransform = AnchorPoseTransform.OpenCvToUnityDefault;

        [Header("Anchor Processors")]
        /// <summary>按顺序处理 raw world pose 的处理器列表。</summary>
        [Tooltip("按顺序处理 frame-aligned raw world pose 的处理器列表。例如只放 Kalman，或 Kalman 后接轻量 LowPass。为空时 stable 直接等于 raw。")]
        [SerializeField] private List<AnchorPoseProcessor> processors = new List<AnchorPoseProcessor>();

        [Header("Reliability Policy")]
        /// <summary>可选 reliability-aware anchor policy 宿主。</summary>
        [Tooltip("可选 reliability-aware anchor policy 宿主。绑定后低分 pose、跳变和短时缺失会进入 Reject/Hold/Coast/Lost；为空时保持 raw + processor baseline。")]
        [SerializeField] private AnchorPolicyHost policyHost;

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

        #region Pose Failures And Policy Decisions

        /// <summary>
        /// 处理 no-pose 观测，让状态机看到缺失事件。
        /// </summary>
        private void NotifyMissingPose(long frameId, double sampleTime, string reason, string phase)
        {
            if (policyHost == null)
            {
                diagnostics.latestPolicyAction = "no_pose";
                diagnostics.latestPolicyReason = reason;
                if (!hasStablePose && !hasRawPose)
                {
                    diagnostics.currentAnchorState = AnchorState.Searching;
                }
                return;
            }

            AnchorPolicyDecision decision = policyHost.AcceptPose(AnchorObservation.MissingPose(frameId, sampleTime, reason, phase));
            ApplyPolicyDecision(decision, frameId);
        }

        /// <summary>
        /// 处理 frame alignment 或协议解析失败，让状态机看到失败事件。
        /// </summary>
        private void NotifyAlignFailure(long frameId, double sampleTime, string reason, string phase)
        {
            if (policyHost == null)
            {
                diagnostics.latestPolicyAction = "align_failed";
                diagnostics.latestPolicyReason = reason;
                return;
            }

            AnchorPolicyDecision decision = policyHost.AcceptPose(AnchorObservation.AlignFailed(frameId, sampleTime, reason, phase));
            ApplyPolicyDecision(decision, frameId);
        }

        /// <summary>
        /// 应用 anchor policy 决策到 stable pose 和 Inspector 诊断。
        /// </summary>
        private void ApplyPolicyDecision(AnchorPolicyDecision decision, long frameId)
        {
            diagnostics.latestPolicyAction = decision.Action.ToString();
            diagnostics.latestPolicyReason = decision.Reason;
            diagnostics.currentAnchorState = decision.State;
            if (decision.HasOutputPose)
            {
                stablePose = RunProcessors(decision.OutputPose, frameId, Time.realtimeSinceStartupAsDouble);
                hasStablePose = true;
            }
            else
            {
                hasStablePose = false;
            }
        }

        /// <summary>
        /// 从 PoseResult 读取 reliability score；旧协议/缺省字段按 1.0 向后兼容。
        /// </summary>
        private static float ReadReliabilityScore(PoseResult result)
        {
            if (result == null)
            {
                return 1.0f;
            }

            if (result.ReliabilityScore > 0.0f)
            {
                return Mathf.Clamp01(result.ReliabilityScore);
            }

            bool hasNewDiagnostics = (result.ReliabilityFlags != null && result.ReliabilityFlags.Count > 0)
                || result.DepthValidInMask > 0.0f
                || result.MaskAreaRatio > 0.0f
                || !string.IsNullOrEmpty(result.PoseSource);
            return hasNewDiagnostics ? 0.0f : 1.0f;
        }

        /// <summary>
        /// 从 PoseResult 读取 reliability flags。
        /// </summary>
        private static string[] ReadReliabilityFlags(PoseResult result)
        {
            if (result == null || result.ReliabilityFlags == null || result.ReliabilityFlags.Count == 0)
            {
                return Array.Empty<string>();
            }

            return result.ReliabilityFlags.ToArray();
        }

        /// <summary>
        /// 从 policy controller 同步 Inspector 诊断。
        /// </summary>
        private void SyncPolicyDiagnostics()
        {
            if (policyHost != null)
            {
                diagnostics.currentAnchorState = policyHost.State;
            }
        }

        #endregion

        #region Server Notifications

        /// <summary>
        /// 接收 Python AnchorStatusEvent，并映射到 Unity anchor lifecycle。
        /// </summary>
        /// <param name="status">Python 发布的 AnchorStatusEvent。</param>
        public void NotifyStatusEvent(AnchorStatusEvent status)
        {
            if (status == null)
            {
                return;
            }

            diagnostics.latestServerState = status.State ?? string.Empty;
            diagnostics.latestServerEvent = status.Event ?? string.Empty;
            string reason = string.IsNullOrEmpty(status.Message) ? diagnostics.latestServerEvent : status.Message;
            string eventName = (diagnostics.latestServerEvent ?? string.Empty).ToUpperInvariant();
            string serverState = (diagnostics.latestServerState ?? string.Empty).ToUpperInvariant();

            if (eventName.Contains("RESET"))
            {
                NotifyResetAccepted(clearProcessors: true, clearAnchorPose: false, reason);
                return;
            }

            if (eventName.Contains("REACQUIRE"))
            {
                NotifyReacquireAccepted(eventName.Contains("STARTED"), reason);
                return;
            }

            if (eventName.Contains("PAUSE") || serverState == "PAUSED")
            {
                NotifyPauseAccepted(reason);
                return;
            }

            if (eventName.Contains("RESUME"))
            {
                NotifyResumeAccepted(reason);
                return;
            }

            if (serverState == "LOST")
            {
                diagnostics.currentAnchorState = AnchorState.Lost;
                diagnostics.latestPolicyAction = "server_status";
                diagnostics.latestPolicyReason = reason;
                return;
            }

            if (serverState == "ERROR" || status.Error != null && !string.IsNullOrEmpty(status.Error.Code))
            {
                diagnostics.currentAnchorState = AnchorState.Error;
                diagnostics.latestPolicyAction = "server_error";
                diagnostics.latestPolicyReason = string.IsNullOrEmpty(status.Error?.Code) ? reason : status.Error.Code;
                return;
            }

            diagnostics.latestPolicyAction = "server_status";
            diagnostics.latestPolicyReason = reason;
        }

        /// <summary>
        /// 接收 Python ServerHeartbeat，并在输入未就绪或服务错误时更新本地 anchor 状态。
        /// </summary>
        /// <param name="heartbeat">Python 发布的 ServerHeartbeat。</param>
        public void NotifyHeartbeat(ServerHeartbeat heartbeat)
        {
            if (heartbeat == null)
            {
                return;
            }

            diagnostics.latestHeartbeatInputReady = heartbeat.InputReady;
            diagnostics.latestHeartbeatReceiveTime = Time.realtimeSinceStartupAsDouble;
            diagnostics.latestServerState = heartbeat.State ?? diagnostics.latestServerState;
            if (!heartbeat.InputReady && diagnostics.currentAnchorState != AnchorState.Paused)
            {
                diagnostics.currentAnchorState = hasStablePose || hasRawPose ? AnchorState.FrozenUncertain : AnchorState.Searching;
                diagnostics.latestPolicyAction = "heartbeat";
                diagnostics.latestPolicyReason = "input_not_ready";
            }

            if (heartbeat.LastError != null && !string.IsNullOrEmpty(heartbeat.LastError.Code))
            {
                diagnostics.currentAnchorState = AnchorState.Error;
                diagnostics.latestPolicyAction = "heartbeat_error";
                diagnostics.latestPolicyReason = heartbeat.LastError.Code;
            }
        }

        #endregion

        #region Policy Notifications

        /// <summary>
        /// 本地收到 reset accepted 或状态事件时通知 anchor policy。
        /// </summary>
        /// <param name="clearProcessors">是否同时清理 processor 状态。</param>
        /// <param name="clearAnchorPose">是否清空 raw/stable pose。</param>
        /// <param name="reason">reset 原因。</param>
        public void NotifyResetAccepted(bool clearProcessors, bool clearAnchorPose, string reason)
        {
            if (clearProcessors)
            {
                ResetProcessors();
            }

            if (clearAnchorPose)
            {
                hasRawPose = false;
                hasStablePose = false;
                diagnostics.latestAlignedFrameId = -1;
            }

            if (policyHost != null)
            {
                policyHost.NotifyReset(Time.realtimeSinceStartupAsDouble, reason);
                SyncPolicyDiagnostics();
            }
            else
            {
                diagnostics.currentAnchorState = AnchorState.Searching;
            }
            diagnostics.latestFailure = reason ?? "reset";
            diagnostics.latestPolicyAction = "reset";
            diagnostics.latestPolicyReason = reason ?? "reset";
        }

        /// <summary>
        /// 本地收到 reacquire accepted 或状态事件时通知 anchor policy。
        /// </summary>
        /// <param name="clearPose">是否清空当前 raw/stable pose。</param>
        /// <param name="reason">reacquire 原因。</param>
        public void NotifyReacquireAccepted(bool clearPose, string reason)
        {
            ResetProcessors();
            if (clearPose)
            {
                hasRawPose = false;
                hasStablePose = false;
                diagnostics.latestAlignedFrameId = -1;
            }

            if (policyHost != null)
            {
                policyHost.NotifyReacquire(Time.realtimeSinceStartupAsDouble, reason);
                SyncPolicyDiagnostics();
            }
            else
            {
                diagnostics.currentAnchorState = AnchorState.Relocalizing;
            }
            diagnostics.latestFailure = reason ?? "reacquire";
            diagnostics.latestPolicyAction = "reacquire";
            diagnostics.latestPolicyReason = reason ?? "reacquire";
        }

        /// <summary>
        /// 通知本地 anchor policy 暂停更新。
        /// </summary>
        /// <param name="reason">暂停原因。</param>
        public void NotifyPauseAccepted(string reason)
        {
            if (policyHost != null)
            {
                policyHost.NotifyPause(Time.realtimeSinceStartupAsDouble, reason);
                SyncPolicyDiagnostics();
            }
            else
            {
                diagnostics.currentAnchorState = AnchorState.Paused;
            }
            diagnostics.latestPolicyAction = "pause";
            diagnostics.latestPolicyReason = reason ?? "pause";
        }

        /// <summary>
        /// 通知本地 anchor policy 恢复更新。
        /// </summary>
        /// <param name="reason">恢复原因。</param>
        public void NotifyResumeAccepted(string reason)
        {
            if (policyHost != null)
            {
                policyHost.NotifyResume(Time.realtimeSinceStartupAsDouble, reason);
                SyncPolicyDiagnostics();
            }
            else
            {
                diagnostics.currentAnchorState = hasStablePose || hasRawPose ? AnchorState.Tracking : AnchorState.Searching;
            }
            diagnostics.latestPolicyAction = "resume";
            diagnostics.latestPolicyReason = reason ?? "resume";
        }

        /// <summary>
        /// 清空当前 raw/stable anchor pose 状态。
        /// </summary>
        /// <param name="clearProcessors">是否同时重置处理器内部状态。</param>
        public void ClearPoseState(bool clearProcessors = true)
        {
            hasRawPose = false;
            hasStablePose = false;
            diagnostics.latestAlignedFrameId = -1;
            diagnostics.latestPhase = string.Empty;
            diagnostics.latestFailure = "cleared_by_status";
            diagnostics.latestPolicyAction = "clear";
            diagnostics.latestPolicyReason = "cleared_by_status";

            if (clearProcessors)
            {
                ResetProcessors();
            }

            if (policyHost != null)
            {
                policyHost.Clear(Time.realtimeSinceStartupAsDouble, "cleared_by_status");
                SyncPolicyDiagnostics();
            }
        }

        #endregion

        #region Diagnostics

        /// <summary>
        /// PoseToAnchorRuntime 的 Inspector 诊断快照。
        /// </summary>
        [Serializable]
        public sealed class RuntimeDiagnostics
        {
            /// <summary>最近成功对齐的 frame_id。</summary>
            [Tooltip("最近成功对齐的 frame_id。只用于 Inspector/日志诊断。")]
            public long latestAlignedFrameId = -1;

            /// <summary>最近一次 PoseResult phase。</summary>
            [Tooltip("最近一次 PoseResult phase。只用于 Inspector/日志诊断。")]
            public string latestPhase = "";

            /// <summary>最近一次失败原因。</summary>
            [Tooltip("最近一次失败原因。空字符串表示最近一次处理没有失败。")]
            public string latestFailure = "";

            /// <summary>当前 Unity anchor 生命周期状态。</summary>
            [Tooltip("当前 Unity anchor 生命周期状态。该状态属于 Unity anchor runtime，不等同于 Python pipeline phase。")]
            public AnchorState currentAnchorState = AnchorState.Uninitialized;

            /// <summary>最近一次 anchor policy 动作。</summary>
            [Tooltip("最近一次 anchor policy 动作：Accept/Reject/Coast/Hold。关闭 reliability policy 时显示 baseline_accept/no_pose 等诊断文本。")]
            public string latestPolicyAction = "";

            /// <summary>最近一次 anchor policy 原因。</summary>
            [Tooltip("最近一次 anchor policy 原因，例如 score_accept、translation_jump 或 no_pose。")]
            public string latestPolicyReason = "";

            /// <summary>最近一次 reliability score。</summary>
            [Tooltip("最近一次 PoseResult.reliability_score。旧协议或缺省字段会按 1.0 处理。")]
            public float latestReliabilityScore = 1.0f;

            /// <summary>最近一次 Python AnchorStatusEvent 状态。</summary>
            [Tooltip("最近一次 Python AnchorStatusEvent.state。该字段只用于诊断，不等同于 Unity anchor state。")]
            public string latestServerState = "";

            /// <summary>最近一次 Python AnchorStatusEvent 事件名。</summary>
            [Tooltip("最近一次 Python AnchorStatusEvent.event。用于观察 reset/reacquire/lost 等跨端状态闭环。")]
            public string latestServerEvent = "";

            /// <summary>最近一次 ServerHeartbeat 中的 input_ready。</summary>
            [Tooltip("最近一次 ServerHeartbeat.input_ready。false 表示 Python 尚未具备 stereo+camera_info 输入。")]
            public bool latestHeartbeatInputReady;

            /// <summary>最近一次 ServerHeartbeat 的 Unity 接收时间。</summary>
            [Tooltip("最近一次 ServerHeartbeat 被 Unity 主线程处理的时间，单位秒。")]
            public double latestHeartbeatReceiveTime = -1.0;

            /// <summary>最近一次实际使用的对齐参考相机。</summary>
            [Tooltip("最近一次实际使用的对齐参考相机。用于确认当前是 Left/Right/Center/None 哪一种对齐。")]
            public CameraReference latestUsedReference = CameraReference.Left;
        }

        #endregion
    }

}

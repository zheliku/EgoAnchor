using System;
using System.Collections.Generic;
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
        /// 判断 Python status event 是否表示 reacquire 刚开始。
        /// </summary>
        /// <param name="eventName">AnchorStatusEvent.event 原始字符串。</param>
        /// <returns>仅 REACQUIRE_STARTED 这类开始事件返回 true。</returns>
        public static bool IsReacquireStartedStatus(string eventName)
        {
            string normalized = (eventName ?? string.Empty).ToUpperInvariant();
            return normalized == "REACQUIRE_STARTED";
        }

        /// <summary>
        /// 判断 Python status event 是否表示 reset 已经在 runtime 线程执行。
        /// </summary>
        /// <param name="eventName">AnchorStatusEvent.event 原始字符串。</param>
        /// <returns>仅 RESET_APPLIED 返回 true。</returns>
        public static bool IsResetAppliedStatus(string eventName)
        {
            string normalized = (eventName ?? string.Empty).ToUpperInvariant();
            return normalized == "RESET_APPLIED";
        }

        /// <summary>
        /// 判断 Python status event 是否表示 pause 已经在 runtime 线程执行。
        /// </summary>
        /// <param name="eventName">AnchorStatusEvent.event 原始字符串。</param>
        /// <returns>仅 PAUSE_APPLIED 返回 true。</returns>
        public static bool IsPauseAppliedStatus(string eventName)
        {
            string normalized = (eventName ?? string.Empty).ToUpperInvariant();
            return normalized == "PAUSE_APPLIED";
        }

        /// <summary>
        /// 判断 Python status event 是否表示 resume 已经在 runtime 线程执行。
        /// </summary>
        /// <param name="eventName">AnchorStatusEvent.event 原始字符串。</param>
        /// <returns>仅 RESUME_APPLIED 返回 true。</returns>
        public static bool IsResumeAppliedStatus(string eventName)
        {
            string normalized = (eventName ?? string.Empty).ToUpperInvariant();
            return normalized == "RESUME_APPLIED";
        }

        /// <summary>
        /// 判断 ServerHeartbeat 是否表示 Python server 处于错误状态。
        /// </summary>
        /// <param name="heartbeat">Python 发布的 ServerHeartbeat。</param>
        /// <returns>heartbeat.state 为 ERROR，或 last_error.code 非空时返回 true。</returns>
        public static bool IsErrorHeartbeat(ServerHeartbeat heartbeat)
        {
            if (heartbeat == null)
            {
                return false;
            }

            string state = (heartbeat.State ?? string.Empty).ToUpperInvariant();
            return state == "ERROR" || (heartbeat.LastError != null && !string.IsNullOrEmpty(heartbeat.LastError.Code));
        }

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
            CapturePoseDiagnostics(result);
            if (IsPausedLocally())
            {
                SetFailure("paused");
                diagnostics.latestPolicyAction = "paused";
                diagnostics.latestPolicyReason = "pose_ignored_while_paused";
                return AcceptResult.NoPose;
            }

            if (!result.HasPose)
            {
                string reason = string.IsNullOrEmpty(result.LastError?.Code) ? "no_pose" : result.LastError.Code;
                SetFailure(reason);
                NotifyMissingPose(result.Header.FrameId, FailureSampleTime(), reason, diagnostics.latestPhase);
                return AcceptResult.NoPose;
            }

            if (!HasFinitePoseMatrix(result))
            {
                SetFailure("invalid_matrix");
                NotifyAlignFailure(result.Header.FrameId, FailureSampleTime(), "invalid_matrix", diagnostics.latestPhase);
                return AcceptResult.InvalidMatrix;
            }

            double now = Time.realtimeSinceStartupAsDouble;
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
        /// 判断当前本地 anchor runtime 是否处于暂停状态。
        /// </summary>
        private bool IsPausedLocally()
        {
            return diagnostics.currentAnchorState == AnchorState.Paused || (policyHost != null && policyHost.State == AnchorState.Paused);
        }

        /// <summary>
        /// 获取失败观测使用的采样时间；未启用 policy 时失败时间不会进入状态机，可避免无意义读取 Unity Time。
        /// </summary>
        private double FailureSampleTime()
        {
            return policyHost == null ? 0.0 : Time.realtimeSinceStartupAsDouble;
        }

        /// <summary>
        /// 判断 PoseResult 中的 4x4 pose matrix 是否存在且全为有限数。
        /// </summary>
        public static bool HasFinitePoseMatrix(PoseResult result)
        {
            if (result?.PoseMatrixCvCamera == null || result.PoseMatrixCvCamera.Values == null || result.PoseMatrixCvCamera.Values.Count != 16)
            {
                return false;
            }

            foreach (float value in result.PoseMatrixCvCamera.Values)
            {
                if (float.IsNaN(value) || float.IsInfinity(value))
                {
                    return false;
                }
            }

            return true;
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
            if (IsPausedLocally())
            {
                diagnostics.latestPolicyAction = "paused";
                diagnostics.latestPolicyReason = "pose_ignored_while_paused";
                diagnostics.latestFailure = "paused";
                return;
            }

            rawPose = worldPose;
            hasRawPose = true;
            diagnostics.latestAlignedFrameId = frameId;

            if (policyHost != null)
            {
                AnchorObservation observation = PoseResultPolicyMapper.FromAlignedPose(
                    frameId,
                    worldPose,
                    sampleTime,
                    sourceResult,
                    diagnostics.latestPhase
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
                stablePose = ShouldAdvanceProcessors(decision.Action)
                    ? RunProcessors(decision.OutputPose, frameId, Time.realtimeSinceStartupAsDouble)
                    : decision.OutputPose;
                hasStablePose = true;
            }
            else
            {
                hasStablePose = false;
            }
        }

        /// <summary>
        /// 判断本次 policy 输出是否应推进 processor 状态。
        /// </summary>
        private static bool ShouldAdvanceProcessors(AnchorPolicyAction action)
        {
            return action == AnchorPolicyAction.Accept || action == AnchorPolicyAction.Coast;
        }

        /// <summary>
        /// 从 PoseResult 捕获 Python 感知评分细项，供 Unity Inspector 和后续 policy 调参使用。
        /// </summary>
        /// <param name="result">Python 发布的 PoseResult。</param>
        private void CapturePoseDiagnostics(PoseResult result)
        {
            diagnostics.latestReliabilityScore = PoseResultPolicyMapper.ReadReliabilityScore(result);
            diagnostics.latestScorePhase = result.ScorePhase;
            diagnostics.latestScoreReprojection = result.ScoreReprojection;
            diagnostics.latestScoreDepth = result.ScoreDepth;
            diagnostics.latestScoreJump = result.ScoreJump;
            diagnostics.latestScoreMask = result.ScoreMask;
            diagnostics.latestScoreReject = result.ScoreReject;
            diagnostics.latestScoreConfidence = result.ScoreConfidence;
            diagnostics.latestTrackReprojection = result.TrackReprojection;
            diagnostics.latestRenderQualityMaskIou = result.RenderQualityMaskIou;
            diagnostics.latestRenderQualityAreaRatioScore = result.RenderQualityAreaRatioScore;
            diagnostics.latestRenderQualityDepthInlier = result.RenderQualityDepthInlier;
            diagnostics.latestRenderQualityDepthAlignment = result.RenderQualityDepthAlignment;
            diagnostics.latestRenderQualityRenderVisibleRatio = result.RenderQualityRenderVisibleRatio;
            diagnostics.latestRenderQualityObservedVisibleRatio = result.RenderQualityObservedVisibleRatio;
            diagnostics.latestRenderQualityDepthResidualMeters = result.RenderQualityDepthResidualM;
            diagnostics.latestRenderQualityRenderAreaPixels = result.RenderQualityRenderAreaPx;
            diagnostics.latestRenderQualityExpected = result.RenderQualityExpected;
            diagnostics.latestRenderQualityStatus = result.RenderQualityStatus ?? string.Empty;
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

            if (IsResetAppliedStatus(eventName))
            {
                NotifyResetAccepted(clearProcessors: true, clearAnchorPose: false, reason);
                return;
            }

            if (IsReacquireStartedStatus(eventName))
            {
                NotifyReacquireAccepted(clearPose: true, reason);
                return;
            }

            if (IsPauseAppliedStatus(eventName) || serverState == "PAUSED")
            {
                NotifyPauseAccepted(reason);
                return;
            }

            if (IsResumeAppliedStatus(eventName))
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
            if (IsErrorHeartbeat(heartbeat))
            {
                diagnostics.currentAnchorState = AnchorState.Error;
                diagnostics.latestPolicyAction = "heartbeat_error";
                diagnostics.latestPolicyReason = string.IsNullOrEmpty(heartbeat.LastError?.Code) ? "server_error" : heartbeat.LastError.Code;
                return;
            }

            if (!heartbeat.InputReady && diagnostics.currentAnchorState != AnchorState.Paused)
            {
                diagnostics.currentAnchorState = hasStablePose || hasRawPose ? AnchorState.FrozenUncertain : AnchorState.Searching;
                diagnostics.latestPolicyAction = "heartbeat";
                diagnostics.latestPolicyReason = "input_not_ready";
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
            else
            {
                diagnostics.currentAnchorState = AnchorState.Searching;
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
            [Tooltip("最近一次 PoseResult.reliability_score，按协议值直接限制到 0..1。")]
            public float latestReliabilityScore = 1.0f;

            /// <summary>最近一次 phase 子分。</summary>
            [Tooltip("最近一次 PoseResult.score_phase，用于确认最终评分中的 phase 乘性项。")]
            public float latestScorePhase;

            /// <summary>最近一次重投影子分。</summary>
            [Tooltip("最近一次 PoseResult.score_reprojection，语义是投影与 Cutie mask 交集区域内的 RGB/LAB 颜色相似度。")]
            public float latestScoreReprojection;

            /// <summary>最近一次深度对齐子分。</summary>
            [Tooltip("最近一次 PoseResult.score_depth，表示渲染深度与观测深度在 mask 交集内的对齐质量。")]
            public float latestScoreDepth;

            /// <summary>最近一次相邻 pose 跳变子分。</summary>
            [Tooltip("最近一次 PoseResult.score_jump，接近 Python track jump 阈值时会降低。")]
            public float latestScoreJump;

            /// <summary>最近一次 mask 面积子分。</summary>
            [Tooltip("最近一次 PoseResult.score_mask，当前优先来自 Cutie mask 面积 / 渲染投影面积，低值表示可见区域过小或遮挡严重。")]
            public float latestScoreMask;

            /// <summary>最近一次 track reject 子分。</summary>
            [Tooltip("最近一次 PoseResult.score_reject，近期 track reject 越多越低。")]
            public float latestScoreReject;

            /// <summary>最近一次连续高质量跟踪置信子分。</summary>
            [Tooltip("最近一次 PoseResult.score_confidence，表示 Python 端连续高质量 pose warmup 的置信释放程度。")]
            public float latestScoreConfidence;

            /// <summary>最近一次 TRACK 重投影分。</summary>
            [Tooltip("最近一次 PoseResult.track_reprojection，当前语义是 TRACK 阶段重投影分；-1 表示 Python 本帧没有有效重投影信号。")]
            public float latestTrackReprojection = -1.0f;

            /// <summary>最近一次渲染 mask 与观测 mask IoU。</summary>
            [Tooltip("最近一次 PoseResult.render_quality_mask_iou，表示渲染前景与观测 mask 的轮廓重叠。")]
            public float latestRenderQualityMaskIou;

            /// <summary>最近一次 Cutie mask 面积与渲染投影面积比例。</summary>
            [Tooltip("最近一次 PoseResult.render_quality_area_ratio_score，等于 Cutie mask 面积 / 渲染投影面积并限制在 0..1，用于解释 score_mask。")]
            public float latestRenderQualityAreaRatioScore;

            /// <summary>最近一次渲染深度 inlier 比例。</summary>
            [Tooltip("最近一次 PoseResult.render_quality_depth_inlier，表示交集区域内 FFS 深度与渲染表面深度接近的比例。")]
            public float latestRenderQualityDepthInlier;

            /// <summary>最近一次连续深度对齐分。</summary>
            [Tooltip("最近一次 PoseResult.render_quality_depth_alignment，由 depth inlier 和中位残差共同得到。")]
            public float latestRenderQualityDepthAlignment;

            /// <summary>最近一次渲染前景可见覆盖率。</summary>
            [Tooltip("最近一次 PoseResult.render_quality_render_visible_ratio，遮挡或观测 mask 过小时会下降。")]
            public float latestRenderQualityRenderVisibleRatio;

            /// <summary>最近一次观测 mask 被渲染解释的覆盖率。</summary>
            [Tooltip("最近一次 PoseResult.render_quality_observed_visible_ratio，低值表示 pose 没覆盖可见物体区域。")]
            public float latestRenderQualityObservedVisibleRatio;

            /// <summary>最近一次深度中位残差。</summary>
            [Tooltip("最近一次 PoseResult.render_quality_depth_residual_m，单位米。")]
            public float latestRenderQualityDepthResidualMeters;

            /// <summary>最近一次渲染质量检测的渲染前景像素数。</summary>
            [Tooltip("最近一次 PoseResult.render_quality_render_area_px，用于判断渲染质量信号是否过小。")]
            public int latestRenderQualityRenderAreaPixels;

            /// <summary>最近一次 Python 是否预期渲染质量信号有效。</summary>
            [Tooltip("最近一次 PoseResult.render_quality_expected。true 但 track_reprojection=-1 时通常表示渲染失败、warmup 或重投影输入不满足。")]
            public bool latestRenderQualityExpected;

            /// <summary>最近一次渲染质量状态文本。</summary>
            [Tooltip("最近一次 PoseResult.render_quality_status，例如 valid、warmup、no_mask、depth_low 或 render_exception。")]
            public string latestRenderQualityStatus = "";

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

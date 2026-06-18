using System;
using EgoAnchor.Alignment;
using EgoAnchor.Diagnostics;
using EgoAnchor.Policy;
using EgoAnchor.Protocol.Generated;
using UnityEngine;

namespace EgoAnchor.Runtime
{
    /// <summary>
    /// Pose-to-anchor 组合点。
    /// 它只负责把 Python camera-space pose 映射到 Unity world pose，并把 aligned raw pose
    /// 提交给 Unity 侧 AnchorPolicyHost。ZOH、低通、Kalman、OneEuro 和 EgoAnchor 方法
    /// 都通过 MotionModel + SmoothingStrategy 组合表达，不再保留 legacy processor 或旧 policy 兼容路径。
    /// </summary>
    [DefaultExecutionOrder(-50)]
    public sealed class PoseToAnchorRuntime : MonoBehaviour
    {
        private static readonly EgoAnchorLog.Channel Log = EgoAnchorLog.For<PoseToAnchorRuntime>();

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
        [Tooltip("Unity 本地选择的对齐参考相机。Left 是当前 Python pose 的语义默认值；Right/Center/None 仅用于本地对照、补偿或诊断。")]
        [SerializeField] private CameraReference alignmentReference = CameraReference.Left;

        /// <summary>camera-local 轴翻转和 camera/anchor/world 三路 pose 补偿的统一配置。</summary>
        [Tooltip("camera-local 轴翻转和 camera/anchor/world 三路 pose 补偿的统一配置。")]
        [SerializeField] private AnchorPoseTransform poseTransform = AnchorPoseTransform.OpenCvToUnityDefault;

        /// <summary>Unity 侧 anchor policy 宿主。</summary>
        [Header("Anchor Policy")]
        [Tooltip("Unity 侧 anchor policy 宿主。持有 MotionModel + SmoothingStrategy 两个模块（可选内联 score 门控），每渲染帧输出平滑 anchor pose。")]
        [SerializeField] private AnchorPolicyHost policyHost;

        private CameraPoseFrameAligner aligner;
        private Pose rawPose;
        private Pose outputPose;
        private Pose arrivalTimeRawPose;
        private bool hasRawPose;
        private bool hasOutputPose;
        private bool hasArrivalTimeRawPose;

        private long latestAlignedFrameId = -1;
        private string latestPhase = "";
        private string latestFailure = "";
        private string latestPolicyAction = "";
        private string latestPolicyReason = "";
        private float latestReliabilityScore = 1.0f;
        private AnchorState currentAnchorState = AnchorState.Uninitialized;
        private AnchorMotionState currentMotionState = AnchorMotionState.Unknown;
        private double latestPredictAheadMs = double.NaN;
        private string latestServerState = "";
        private bool latestHeartbeatInputReady;
        private double latestArrivalTimeRawMonoMs = double.NaN;
        private int latestArrivalTimeRawUnityFrame = -1;
        private CameraReference latestArrivalTimeCameraReference = CameraReference.Left;

        /// <summary>最近成功对齐的 frame_id。</summary>
        public long LatestAlignedFrameId => latestAlignedFrameId;

        /// <summary>最近一次 PoseResult phase。</summary>
        public string LatestPhase => latestPhase;

        /// <summary>最近一次失败原因。</summary>
        public string LatestFailure => latestFailure;

        /// <summary>当前 Unity anchor 生命周期状态。</summary>
        public AnchorState CurrentAnchorState => policyHost != null ? policyHost.State : currentAnchorState;

        /// <summary>最近一次 anchor policy 动作。</summary>
        public string LatestPolicyAction => latestPolicyAction;

        /// <summary>最近一次 anchor policy 原因。</summary>
        public string LatestPolicyReason => latestPolicyReason;

        /// <summary>最近一次 reliability score。</summary>
        public float LatestReliabilityScore => latestReliabilityScore;

        /// <summary>当前运动状态名。</summary>
        public string CurrentMotionStateName => currentMotionState.ToString();

        /// <summary>最近一次渲染输出的前推时长，单位毫秒。</summary>
        public double LatestPredictAheadMs => latestPredictAheadMs;

        /// <summary>当前 eval 策略 label。</summary>
        public string StrategyLabel => policyHost != null ? policyHost.StrategyLabel : "";

        /// <summary>当前绑定的 Unity policy host，只用于 eval 配置摘要。</summary>
        public AnchorPolicyHost PolicyHost => policyHost;

        /// <summary>当前 gate 名称。</summary>
        public string GateName => policyHost != null ? policyHost.GateName : "";

        /// <summary>当前运动模型名称。</summary>
        public string MotionModelName => policyHost != null ? policyHost.MotionModelName : "";

        /// <summary>当前平滑策略名称。</summary>
        public string SmoothingStrategyName => policyHost != null ? policyHost.SmoothingStrategyName : "";

        /// <summary>最近一次 output stage 平移残差，单位米。</summary>
        public float LatestResidualMeters => policyHost != null ? policyHost.LatestResidualMeters : float.NaN;

        /// <summary>最近一次 output stage 旋转残差，单位度。</summary>
        public float LatestResidualDegrees => policyHost != null ? policyHost.LatestResidualDegrees : float.NaN;

        /// <summary>最近一次被 policy 接受的可靠性分数。</summary>
        public float LatestAcceptedScore => policyHost != null ? policyHost.LatestAcceptedScore : float.NaN;

        /// <summary>最近一次 policy 输出是否静止锁定。</summary>
        public bool LatestStaticLocked => policyHost != null && policyHost.LatestStaticLocked;

        /// <summary>
        /// consume 一次"请求通知 Python 重新 register"标志 (host 持续低分+几何不可信时置位)。
        /// 由 AnchorRuntimeHub 在 fan-in 时统一收集并发一次 NATS reacquire。runtime 自身不持 command client。
        /// </summary>
        public bool ConsumeServerReacquireRequest() => policyHost != null && policyHost.ConsumeServerReacquireRequest();

        /// <summary>最近一次 arrival-time raw 诊断时间，单位毫秒。</summary>
        public double LatestArrivalTimeRawMonoMs => latestArrivalTimeRawMonoMs;

        /// <summary>最近一次 arrival-time raw 诊断对应的 Unity frame。</summary>
        public int LatestArrivalTimeRawUnityFrame => latestArrivalTimeRawUnityFrame;

        /// <summary>最近一次 arrival-time raw 诊断使用的参考相机。</summary>
        public CameraReference LatestArrivalTimeCameraReference => latestArrivalTimeCameraReference;

        /// <summary>最近一次 Python AnchorStatusEvent.state。</summary>
        public string LatestServerState => latestServerState;

        /// <summary>最近一次 ServerHeartbeat.input_ready。</summary>
        public bool LatestHeartbeatInputReady => latestHeartbeatInputReady;

        /// <summary>
        /// 判断 Python status event 是否表示 reacquire 刚开始。
        /// </summary>
        public static bool IsReacquireStartedStatus(string eventName)
        {
            return (eventName ?? string.Empty).ToUpperInvariant() == "REACQUIRE_STARTED";
        }

        /// <summary>
        /// 判断 Python status event 是否表示 reset 已经在 runtime 线程执行。
        /// </summary>
        public static bool IsResetAppliedStatus(string eventName)
        {
            return (eventName ?? string.Empty).ToUpperInvariant() == "RESET_APPLIED";
        }

        /// <summary>
        /// 判断 Python status event 是否表示 pause 已经在 runtime 线程执行。
        /// </summary>
        public static bool IsPauseAppliedStatus(string eventName)
        {
            return (eventName ?? string.Empty).ToUpperInvariant() == "PAUSE_APPLIED";
        }

        /// <summary>
        /// 判断 Python status event 是否表示 resume 已经在 runtime 线程执行。
        /// </summary>
        public static bool IsResumeAppliedStatus(string eventName)
        {
            return (eventName ?? string.Empty).ToUpperInvariant() == "RESUME_APPLIED";
        }

        /// <summary>
        /// 判断 ServerHeartbeat 是否表示 Python server 处于错误状态。
        /// </summary>
        public static bool IsErrorHeartbeat(ServerHeartbeat heartbeat)
        {
            if (heartbeat == null)
            {
                return false;
            }

            string state = (heartbeat.State ?? string.Empty).ToUpperInvariant();
            return state == "ERROR" || heartbeat.LastError != null && !string.IsNullOrEmpty(heartbeat.LastError.Code);
        }

        private void Awake()
        {
            RebuildAligner();
            if (policyHost == null)
            {
                Log.Warning("PoseToAnchorRuntime 未绑定 AnchorPolicyHost；该 runtime 不会输出 anchor pose。", this);
                return;
            }

            policyHost.Bind(this);
            SyncPolicyState();
        }

        private void LateUpdate()
        {
            if (policyHost != null)
            {
                AdvanceAnchorOutput(Time.realtimeSinceStartupAsDouble);
            }
        }

        private void OnValidate()
        {
            RebuildAligner();
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
            latestReliabilityScore = PoseResultPolicyMapper.ReadReliabilityScore(result);
            if (IsPausedLocally())
            {
                SetFailure("paused");
                latestPolicyAction = "paused";
                latestPolicyReason = "pose_ignored_while_paused";
                return AcceptResult.NoPose;
            }

            if (!result.HasPose)
            {
                hasArrivalTimeRawPose = false;
                string reason = string.IsNullOrEmpty(result.LastError?.Code) ? "no_pose" : result.LastError.Code;
                SetFailure(reason);
                NotifyMissingPose(result.Header.FrameId, FailureSampleTime(), reason, latestPhase);
                return AcceptResult.NoPose;
            }

            if (!HasFinitePoseMatrix(result))
            {
                hasArrivalTimeRawPose = false;
                SetFailure("invalid_matrix");
                NotifyAlignFailure(result.Header.FrameId, FailureSampleTime(), "invalid_matrix", latestPhase);
                return AcceptResult.InvalidMatrix;
            }

            double now = Time.realtimeSinceStartupAsDouble;
            if (aligner == null)
            {
                RebuildAligner();
            }

            CaptureArrivalTimeRaw(result, now);
            if (aligner == null || !aligner.TryAlign(result, out Pose worldPose, out _))
            {
                string reason = $"align_failed_frame_{result.Header.FrameId}";
                SetFailure(reason);
                NotifyAlignFailure(result.Header.FrameId, now, reason, latestPhase);
                return AcceptResult.AlignFailed;
            }

            AcceptWorldPose(result.Header.FrameId, worldPose, result, now);
            latestFailure = string.Empty;
            return AcceptResult.Aligned;
        }

        /// <summary>尝试获取当前 raw anchor pose，不经过任何 policy 输出整形。</summary>
        public bool TryGetRawPose(out Pose pose)
        {
            pose = rawPose;
            return hasRawPose;
        }

        /// <summary>尝试获取当前 anchor policy 每帧输出 pose。</summary>
        public bool TryGetOutputPose(out Pose pose)
        {
            pose = outputPose;
            return hasOutputPose;
        }

        /// <summary>尝试获取 arrival-time raw 诊断 pose。</summary>
        public bool TryGetArrivalTimeRawPose(out Pose pose)
        {
            pose = arrivalTimeRawPose;
            return hasArrivalTimeRawPose;
        }

        /// <summary>
        /// 外部测试可直接注入 world pose，绕过 NATS/Protobuf/frame history。
        /// </summary>
        public void AcceptWorldPose(long frameId, Pose worldPose)
        {
            AcceptWorldPose(frameId, worldPose, null, Time.realtimeSinceStartupAsDouble);
        }

        /// <summary>
        /// Unity 录制日志回放专用入口：接收已经是 Unity world 坐标的 aligned raw pose。
        /// </summary>
        public void AcceptAlignedWorldPoseForReplay(
            long frameId,
            Pose worldPose,
            double captureTimeSeconds,
            float reliabilityScore,
            string[] reliabilityFlags,
            string phase,
            string poseSource,
            double sampleTimeSeconds)
        {
            latestPhase = phase ?? string.Empty;
            latestReliabilityScore = Mathf.Clamp01(reliabilityScore);
            bool hasHeadPose = TryResolveHeadPose(frameId, out Pose headPose);
            AnchorObservation observation = AnchorObservation.FromAlignedPose(
                frameId,
                worldPose,
                sampleTimeSeconds,
                reliabilityScore,
                reliabilityFlags ?? Array.Empty<string>(),
                phase ?? string.Empty,
                poseSource ?? string.Empty,
                captureTimeSeconds,
                hasHeadPose,
                headPose);
            AcceptWorldPose(frameId, worldPose, observation);
            latestFailure = string.Empty;
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

        private void AcceptWorldPose(long frameId, Pose worldPose, PoseResult sourceResult, double sampleTime)
        {
            bool hasHeadPose = TryResolveHeadPose(frameId, out Pose headPose);
            AnchorObservation observation = PoseResultPolicyMapper.FromAlignedPose(
                frameId,
                worldPose,
                sampleTime,
                ResolveCaptureTimeSeconds(frameId),
                sourceResult,
                latestPhase,
                hasHeadPose,
                headPose
            );
            AcceptWorldPose(frameId, worldPose, observation);
        }

        /// <summary>取该 frame_id 采集时刻的 center camera (头部) world pose，用于头动感知 static。
        /// 复用 FramePoseHistory 的同一份缓存，不重复绑定 CenterEyeAnchor。</summary>
        private bool TryResolveHeadPose(long frameId, out Pose headPose)
        {
            if (framePoseHistory != null && framePoseHistory.TryGet(frameId, out FramePoseRecord record))
            {
                headPose = record.CenterCameraPose;
                return true;
            }

            headPose = Pose.identity;
            return false;
        }

        private void AcceptWorldPose(long frameId, Pose worldPose, in AnchorObservation observation)
        {
            if (IsPausedLocally())
            {
                latestPolicyAction = "paused";
                latestPolicyReason = "pose_ignored_while_paused";
                latestFailure = "paused";
                return;
            }

            rawPose = worldPose;
            hasRawPose = true;
            latestAlignedFrameId = frameId;

            if (policyHost == null)
            {
                hasOutputPose = false;
                currentAnchorState = AnchorState.Searching;
                latestPolicyAction = "missing_policy_host";
                latestPolicyReason = "policy_host_required";
                return;
            }

            AnchorPolicyDecision decision = policyHost.AcceptPose(observation);
            ApplyPolicyDecision(decision);
            SyncPolicyState();
        }

        private double ResolveCaptureTimeSeconds(long frameId)
        {
            if (framePoseHistory != null && framePoseHistory.TryGet(frameId, out FramePoseRecord record))
            {
                return record.SenderMonoMs / 1000.0;
            }

            return -1.0;
        }

        private bool IsPausedLocally()
        {
            return CurrentAnchorState == AnchorState.Paused;
        }

        private double FailureSampleTime()
        {
            return policyHost == null ? 0.0 : Time.realtimeSinceStartupAsDouble;
        }

        private void RebuildAligner()
        {
            aligner = framePoseHistory != null || alignmentReference == CameraReference.None
                ? new CameraPoseFrameAligner(framePoseHistory, alignmentReference, poseTransform)
                : null;
            if (aligner == null)
            {
                latestFailure = "missing_frame_pose_history";
            }
        }

        private void SetFailure(string reason)
        {
            latestFailure = reason;
        }

        private void NotifyMissingPose(long frameId, double sampleTime, string reason, string phase)
        {
            if (policyHost == null)
            {
                latestPolicyAction = "no_pose";
                latestPolicyReason = reason;
                currentAnchorState = hasOutputPose || hasRawPose ? AnchorState.FrozenUncertain : AnchorState.Searching;
                return;
            }

            AnchorPolicyDecision decision = policyHost.AcceptPose(AnchorObservation.MissingPose(frameId, sampleTime, reason, phase));
            ApplyPolicyDecision(decision);
            SyncPolicyState();
        }

        private void NotifyAlignFailure(long frameId, double sampleTime, string reason, string phase)
        {
            if (policyHost == null)
            {
                latestPolicyAction = "align_failed";
                latestPolicyReason = reason;
                return;
            }

            AnchorPolicyDecision decision = policyHost.AcceptPose(AnchorObservation.AlignFailed(frameId, sampleTime, reason, phase));
            ApplyPolicyDecision(decision);
            SyncPolicyState();
        }

        private void ApplyPolicyDecision(AnchorPolicyDecision decision)
        {
            latestPolicyAction = decision.Action.ToString();
            latestPolicyReason = decision.Reason;
            currentAnchorState = decision.State;
        }

        /// <summary>
        /// 每渲染帧推进 anchor policy 并刷新输出 pose。
        /// </summary>
        public void AdvanceAnchorOutput(double nowSeconds)
        {
            if (policyHost == null)
            {
                return;
            }

            AnchorPolicyOutput output = policyHost.Advance(nowSeconds);
            currentAnchorState = output.State;
            currentMotionState = output.MotionState;
            latestPredictAheadMs = output.PredictAheadSeconds * 1000f;
            if (output.HasPose)
            {
                outputPose = output.Pose;
                hasOutputPose = true;
            }
            else
            {
                hasOutputPose = false;
            }
        }

        private void CaptureArrivalTimeRaw(PoseResult result, double arrivalTimeSeconds)
        {
            hasArrivalTimeRawPose = false;
            latestArrivalTimeRawMonoMs = double.NaN;
            latestArrivalTimeRawUnityFrame = -1;
            latestArrivalTimeCameraReference = alignmentReference;
            if (aligner == null)
            {
                return;
            }

            if (!aligner.TryAlignWithLatestCameraPose(result, out Pose arrivalPose, out CameraReference usedReference, out _))
            {
                return;
            }

            arrivalTimeRawPose = arrivalPose;
            hasArrivalTimeRawPose = true;
            latestArrivalTimeRawMonoMs = arrivalTimeSeconds * 1000.0;
            latestArrivalTimeRawUnityFrame = Time.frameCount;
            latestArrivalTimeCameraReference = usedReference;
        }

        private void SyncPolicyState()
        {
            if (policyHost == null)
            {
                return;
            }

            currentAnchorState = policyHost.State;
            currentMotionState = policyHost.MotionState;
            latestPredictAheadMs = policyHost.PredictAheadSeconds * 1000f;
        }

        /// <summary>
        /// 接收 Python AnchorStatusEvent，并映射到 Unity anchor lifecycle。
        /// </summary>
        public void NotifyStatusEvent(AnchorStatusEvent status)
        {
            if (status == null)
            {
                return;
            }

            latestServerState = status.State ?? string.Empty;
            string serverEvent = status.Event ?? string.Empty;
            string reason = string.IsNullOrEmpty(status.Message) ? serverEvent : status.Message;
            string eventName = serverEvent.ToUpperInvariant();
            string serverState = latestServerState.ToUpperInvariant();

            if (IsResetAppliedStatus(eventName))
            {
                NotifyReset(clearAnchorPose: false, reason);
                return;
            }

            if (IsReacquireStartedStatus(eventName))
            {
                NotifyReacquire(clearPose: true, reason);
                return;
            }

            if (IsPauseAppliedStatus(eventName) || serverState == "PAUSED")
            {
                NotifyPause(reason);
                return;
            }

            if (IsResumeAppliedStatus(eventName))
            {
                NotifyResume(reason);
                return;
            }

            if (serverState == "LOST")
            {
                if (policyHost != null)
                {
                    policyHost.NotifyLost(Time.realtimeSinceStartupAsDouble, reason);
                    SyncPolicyState();
                }
                else
                {
                    currentAnchorState = AnchorState.Lost;
                }
                latestPolicyAction = "server_status";
                latestPolicyReason = reason;
                return;
            }

            if (serverState == "ERROR" || status.Error != null && !string.IsNullOrEmpty(status.Error.Code))
            {
                string errorReason = string.IsNullOrEmpty(status.Error?.Code) ? reason : status.Error.Code;
                NotifyError(errorReason, "server_error");
                return;
            }

            latestPolicyAction = "server_status";
            latestPolicyReason = reason;
        }

        /// <summary>
        /// 接收 Python ServerHeartbeat，并在输入未就绪或服务错误时更新本地 anchor 状态。
        /// </summary>
        public void NotifyHeartbeat(ServerHeartbeat heartbeat)
        {
            if (heartbeat == null)
            {
                return;
            }

            latestHeartbeatInputReady = heartbeat.InputReady;
            latestServerState = heartbeat.State ?? latestServerState;
            if (IsErrorHeartbeat(heartbeat))
            {
                string errorReason = string.IsNullOrEmpty(heartbeat.LastError?.Code) ? "server_error" : heartbeat.LastError.Code;
                NotifyError(errorReason, "heartbeat_error");
                return;
            }

            if (!heartbeat.InputReady && CurrentAnchorState != AnchorState.Paused)
            {
                currentAnchorState = hasOutputPose || hasRawPose ? AnchorState.FrozenUncertain : AnchorState.Searching;
                latestPolicyAction = "heartbeat";
                latestPolicyReason = "input_not_ready";
            }
        }

        private void NotifyReset(bool clearAnchorPose, string reason)
        {
            if (clearAnchorPose)
            {
                ClearLocalPoses();
            }

            if (policyHost != null)
            {
                policyHost.NotifyReset(Time.realtimeSinceStartupAsDouble, reason);
                SyncPolicyState();
            }
            else
            {
                currentAnchorState = AnchorState.Searching;
            }
            latestFailure = reason ?? "reset";
            latestPolicyAction = "reset";
            latestPolicyReason = reason ?? "reset";
        }

        private void NotifyReacquire(bool clearPose, string reason)
        {
            if (clearPose)
            {
                ClearLocalPoses();
            }

            if (policyHost != null)
            {
                policyHost.NotifyReacquire(Time.realtimeSinceStartupAsDouble, reason);
                SyncPolicyState();
            }
            else
            {
                currentAnchorState = AnchorState.Relocalizing;
            }
            latestFailure = reason ?? "reacquire";
            latestPolicyAction = "reacquire";
            latestPolicyReason = reason ?? "reacquire";
        }

        private void NotifyPause(string reason)
        {
            if (policyHost != null)
            {
                policyHost.NotifyPause(Time.realtimeSinceStartupAsDouble, reason);
                SyncPolicyState();
            }
            else
            {
                currentAnchorState = AnchorState.Paused;
            }
            latestPolicyAction = "pause";
            latestPolicyReason = reason ?? "pause";
        }

        private void NotifyResume(string reason)
        {
            if (policyHost != null)
            {
                policyHost.NotifyResume(Time.realtimeSinceStartupAsDouble, reason);
                SyncPolicyState();
            }
            else
            {
                currentAnchorState = hasOutputPose || hasRawPose ? AnchorState.Tracking : AnchorState.Searching;
            }
            latestPolicyAction = "resume";
            latestPolicyReason = reason ?? "resume";
        }

        private void NotifyError(string reason, string action)
        {
            if (policyHost != null)
            {
                policyHost.NotifyError(Time.realtimeSinceStartupAsDouble, reason);
                SyncPolicyState();
            }
            else
            {
                currentAnchorState = AnchorState.Error;
            }
            latestPolicyAction = action;
            latestPolicyReason = reason;
        }

        private void ClearLocalPoses()
        {
            hasRawPose = false;
            hasOutputPose = false;
            hasArrivalTimeRawPose = false;
            latestAlignedFrameId = -1;
        }
    }
}

using System;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using System.Text;
using EgoAnchor.Alignment;
using EgoAnchor.Client;
using EgoAnchor.Eval.RQ1;
using EgoAnchor.Eval.RQ2;
using EgoAnchor.Policy;
using EgoAnchor.Quest;
using EgoAnchor.Runtime;
using UnityEngine;

namespace EgoAnchor.Eval
{
    /// <summary>
    /// 评估记录变体描述——Inspector 中配置要录制的 runtime 列表。
    /// </summary>
    [Serializable]
    public struct EvalVariant
    {
        /// <summary>输出日志中的变体标签，例如 primary、baseline。</summary>
        [Tooltip("输出日志中的变体标签，例如 primary 或 baseline。")]
        public string label;

        /// <summary>对应的 PoseToAnchorRuntime，用于读取 policy/reliability/raw pose。</summary>
        [Tooltip("对应的 PoseToAnchorRuntime。")]
        public PoseToAnchorRuntime runtime;

        /// <summary>实际用于显示和评估的 Anchor Transform。</summary>
        [Tooltip("实际用于显示/评估的 Anchor Transform；日志直接记录其 world pose。")]
        public Transform anchorTransform;

        /// <summary>控制实际显示与 hold-last 行为的组件，用于区分 runtime 输出和用户可见 pose。</summary>
        [Tooltip("控制该 Transform 显示行为的 DynamicObjectAnchor；用于记录 hold-last 或隐藏状态。")]
        public DynamicObjectAnchor anchorPresenter;

        /// <summary>是否为主变体；主变体额外记录 aligned raw / arrival-time raw / reliability。</summary>
        [Tooltip("是否为主变体；主变体额外记录 aligned raw 和 reliability score。")]
        public bool isPrimary;
    }

    /// <summary>
    /// EgoAnchor 评估数据记录器。
    /// <para>
    /// - 接收发布器的发送尝试通知，在采集帧时写 unity_capture 行；<br/>
    /// - 在 <c>LateUpdate</c> 每渲染 tick 写 unity_output 行（含各变体输出和 GT 速度）。
    /// </para>
    /// </summary>
    [DefaultExecutionOrder(50)]
    public sealed class EvalRecorder : MonoBehaviour
    {
        // ── References ──

        /// <summary>Ground Truth Transform，通常绑定 OVRControllerPrefab 根节点。</summary>
        [Header("Ground Truth")]
        [Tooltip("作为 GT 的场景 Transform，通常绑定 OVRControllerPrefab 根节点。")]
        [SerializeField] private Transform groundTruth;

        /// <summary>头部中心参考 Transform，通常为 CenterEyeAnchor。</summary>
        [Tooltip("头部中心参考 Transform，通常为 CenterEyeAnchor。")]
        [SerializeField] private Transform headAnchor;

        /// <summary>frame alignment 参考相机，与主 runtime 保持一致（默认 Left）。</summary>
        [Header("Frame Alignment")]
        [Tooltip("frame alignment 参考相机；与主 runtime 保持一致，默认 Left。")]
        [SerializeField] private CameraReference alignmentRef = CameraReference.Left;

        /// <summary>Quest stereo 采集源，frame_id 从这里来。</summary>
        [Tooltip("Quest stereo 采集源；必须与运行时发送图像的 StereoFrameSource 是同一个实例。")]
        [SerializeField] private StereoFrameSource stereoSource;

        /// <summary>Quest stereo 发布入口；提供紧邻 ZMQ TrySend 的发布尝试时刻。</summary>
        [Tooltip("Quest stereo 发布入口；用于记录 ZMQ 发布尝试时刻和成功标志。")]
        [SerializeField] private QuestStreamPublisher streamPublisher;

        /// <summary>frame_id → 图像时刻 pose/timing 缓存，用于 source_capture_mono_ms。</summary>
        [Tooltip("frame_id → image-time proxy pose 缓存；必须与 StereoFrameSource / PoseToAnchorRuntime 共用同一实例。")]
        [SerializeField] private FramePoseHistory framePoseHistory;

        /// <summary>
        /// 可选：用于检测 GT 手柄跟踪是否有效的 OVR 控制器类型。
        /// 设为 None 时不做有效性过滤（总是信任 groundTruth 的 Transform）。
        /// 设为 RTouch / LTouch 后，手柄休眠或 OVR 跟踪丢失时 gt_pose_valid 自动标为 false。
        /// </summary>
        [Header("GT Validity")]
        [Tooltip("可选：OVR 手柄类型，用于检测手柄跟踪是否有效。设为 None 则不过滤。")]
        [SerializeField] private OVRInput.Controller gtController = OVRInput.Controller.RTouch;

        /// <summary>要录制的 runtime 变体列表；主变体（isPrimary=true）额外记录 aligned raw。</summary>
        [Header("Variants")]
        [Tooltip("要录制的 runtime 变体列表。")]
        [SerializeField] private List<EvalVariant> variants = new List<EvalVariant>();

        /// <summary>可选：RQ1 指标选择器，持有用户当前标记的指标类型。</summary>
        [Header("RQ1 Metrics (Optional)")]
        [Tooltip("可选：RQ1 指标选择器；若绑定，则在 output 行中记录当前指标。")]
        [SerializeField] private RQ1MetricSelector rq1Selector;

        /// <summary>可选：RQ2 试次选择器，提供当前场景、编号和目标速度。</summary>
        [Header("RQ2 Trial (Optional)")]
        [Tooltip("可选：RQ2 试次选择器；若绑定，则在 output 行中记录当前试次上下文。")]
        [SerializeField] private RQ2TrialSelector rq2Selector;

        // ── State ──

        private EvalLog _captureLog;
        private EvalLog _outputLog;
        private bool _recording;

        /// <summary>上一帧 GT pose，用于计算 GT 速度。</summary>
        private Pose _lastGtPose;
        private double _lastGtMonoMs;
        private bool _hasLastGt;

        /// <summary>
        /// OVR 手柄 sleep 后的 GT keep-alive 窗口（毫秒）。
        /// 静止放置时手柄会进入 sleep，OVR 报 tracked=false，
        /// 但位姿本身仍然有效，keep-alive 内继续复用上次有效 pose。
        /// </summary>
        private const double GtKeepAliveMs = 30_000.0;

        /// <summary>上次 OVR 明确跟踪到的 GT pose（用于 keep-alive）。</summary>
        private Pose _lastTrackedGtPose;
        private double _lastTrackedGtMonoMs = -1.0;

        /// <summary>当前渲染 tick 复用的系统变体快照缓冲。</summary>
        private readonly List<EvalVariantSnapshot> _snapshots = new List<EvalVariantSnapshot>();

        /// <summary>录制期间按标签缓存的配置 hash，避免逐帧反射读取组件参数。</summary>
        private readonly Dictionary<string, string> _configHashCache = new Dictionary<string, string>(StringComparer.Ordinal);

        /// <summary>会话开始时固定的变体标签，供停止后写 manifest。</summary>
        private readonly List<string> _manifestVariantLabels = new List<string>();

        /// <summary>会话开始时固定的变体配置，避免 runtime 销毁后摘要退化为空值。</summary>
        private readonly List<EvalVariantConfig> _manifestVariantConfigs = new List<EvalVariantConfig>();

        /// <summary>当前是否已经保存可供 manifest 使用的会话配置快照。</summary>
        private bool _hasManifestMetadataSnapshot;

        // ── Public API ──

        /// <summary>GT Transform 名称，写入 manifest。</summary>
        public string GtTransformName => groundTruth != null ? groundTruth.name : string.Empty;

        /// <summary>GT 来源标识，写入 manifest。</summary>
        public string GtSource => groundTruth != null ? "transform" : "transform_missing";

        // ── 实时遥测访问器（供 EvalLiveStats 读取，不写文件、不改状态） ──

        /// <summary>
        /// 主变体 runtime：isPrimary=true 的第一个；都没有则取列表首个。
        /// 供实时遥测读取时延/分数/锚定状态，与录制的主变体保持一致。
        /// </summary>
        public PoseToAnchorRuntime PrimaryRuntime
        {
            get
            {
                EvalVariant primary = ResolvePrimaryVariant();
                return primary.runtime;
            }
        }

        /// <summary>
        /// 主变体实际显示用 anchor Transform。实时误差按它与 GT 比较，
        /// 与录制的 output_pos 完全同源（录制也是读这个 Transform）。
        /// </summary>
        public Transform PrimaryAnchorTransform
        {
            get
            {
                EvalVariant primary = ResolvePrimaryVariant();
                return primary.anchorTransform;
            }
        }

        /// <summary>frame_id → 图像时间代理 pose/时间缓存，用于反查 ImageMonoMs 算观测年龄。</summary>
        public FramePoseHistory FrameHistory => framePoseHistory;

        /// <summary>
        /// GT Transform 原始 pose，不经 OVR tracked 门控和 keep-alive。
        /// 实时面板用它算误差：只要手柄 Transform 在动就更新，不被 OVR 把 tracked 报成
        /// false 卡住（Link/editor 下常见）。录制路径仍走 <see cref="TryGetCurrentGtPose"/>
        /// 的门控逻辑标 gt_pose_valid，两者互不影响。
        /// </summary>
        /// <param name="pose">GT Transform 绑定时输出其当前 world pose。</param>
        /// <returns>是否绑定了 GT Transform。</returns>
        public bool TryGetLiveGtPose(out Pose pose)
        {
            if (groundTruth == null)
            {
                pose = Pose.identity;
                return false;
            }
            pose = new Pose(groundTruth.position, groundTruth.rotation);
            return true;
        }

        /// <summary>
        /// 解析当前 GT pose（含手柄 sleep keep-alive），与录制逻辑同一入口。
        /// </summary>
        /// <param name="pose">有效时输出当前 GT world pose。</param>
        /// <returns>GT 当前是否有效。</returns>
        public bool TryGetCurrentGtPose(out Pose pose)
        {
            double nowMs = UnityEngine.Time.realtimeSinceStartupAsDouble * 1000.0;
            (bool valid, Pose resolved) = ResolveGtPose(nowMs);
            pose = resolved;
            return valid;
        }

        /// <summary>取主变体：优先 isPrimary，回退列表首个；空列表返回 default。</summary>
        private EvalVariant ResolvePrimaryVariant()
        {
            for (int i = 0; i < variants.Count; i++)
            {
                if (variants[i].isPrimary) return variants[i];
            }
            return variants.Count > 0 ? variants[0] : default;
        }

        /// <summary>收集当前变体标签列表，写入 manifest。</summary>
        public void CollectVariantLabels(List<string> labels)
        {
            if (labels == null) return;
            labels.Clear();
            if (_hasManifestMetadataSnapshot)
            {
                labels.AddRange(_manifestVariantLabels);
                return;
            }

            for (int i = 0; i < variants.Count; i++)
                labels.Add(ResolveLabel(variants[i], i));
        }

        /// <summary>收集当前变体配置摘要，写入 manifest。</summary>
        public void CollectVariantConfigs(List<EvalVariantConfig> configs)
        {
            if (configs == null) return;
            configs.Clear();
            if (_hasManifestMetadataSnapshot)
            {
                configs.AddRange(_manifestVariantConfigs);
                return;
            }

            for (int i = 0; i < variants.Count; i++)
            {
                EvalVariant v = variants[i];
                string label = ResolveLabel(v, i);
                configs.Add(BuildVariantConfig(v, label));
            }
        }

        /// <summary>开始写入评估日志。</summary>
        public void BeginRecording(string capturePath, string outputPath)
        {
            StopRecording();
            _captureLog = new EvalLog(capturePath);
            _outputLog  = new EvalLog(outputPath);
            RefreshConfigHashCache();
            CaptureManifestMetadata();
            _hasLastGt = false;
            _lastTrackedGtMonoMs = -1.0;
            _recording = true;
        }

        /// <summary>停止录制并关闭文件句柄。</summary>
        public void StopRecording()
        {
            _recording = false;
            _captureLog?.Dispose(); _captureLog = null;
            _outputLog?.Dispose();  _outputLog  = null;
            _snapshots.Clear();
            _configHashCache.Clear();
            _hasLastGt = false;
            _lastTrackedGtMonoMs = -1.0;
        }

        // ── Unity 生命周期 ──

        private void OnEnable()
        {
            if (streamPublisher != null)
                streamPublisher.StereoPublishAttempted += RecordCapturePublishAttempt;
        }

        private void OnDisable()
        {
            if (streamPublisher != null)
                streamPublisher.StereoPublishAttempted -= RecordCapturePublishAttempt;
        }

        private void OnDestroy() => StopRecording();

        private void OnValidate()
        {
            if (variants == null) variants = new List<EvalVariant>();
        }

        // ── 采集事件：写 capture 行 ──

        /// <param name="timing">本帧图像时间代理与 payload-ready 时间。</param>
        public void RecordCapturePublishAttempt(
            FrameCaptureTiming timing,
            double publishAttemptMonoMs,
            bool publishSucceeded)
        {
            if (!_recording || _captureLog == null) return;

            FramePoseRecord fr = default;
            bool hasFrameRecord = framePoseHistory != null && framePoseHistory.TryGet(timing.FrameId, out fr);
            Pose cameraPose = Pose.identity;
            bool cameraValid = hasFrameRecord && fr.TryGetCameraPose(alignmentRef, out cameraPose);

            double unixMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            double gtSampleMonoMs = UnityEngine.Time.realtimeSinceStartupAsDouble * 1000.0;
            (bool gtValid, Pose gtPose) = ResolveGtPose(gtSampleMonoMs);
            Pose headPose = headAnchor != null ? new Pose(headAnchor.position, headAnchor.rotation) : Pose.identity;

            _captureLog.Write(EvalJson.BuildCaptureLine(
                timing.FrameId,
                hasFrameRecord ? fr.ImageMonoMs : timing.ImageMonoMs,
                unixMs,
                hasFrameRecord ? fr.ImageUnityFrame : timing.ImageUnityFrame,
                hasFrameRecord ? fr.SenderMonoMs : timing.SenderMonoMs,
                hasFrameRecord ? fr.SenderUnityFrame : timing.SenderUnityFrame,
                gtSampleMonoMs,
                timing.ImageTimeOffsetFrames,
                publishAttemptMonoMs,
                publishSucceeded,
                headPose, cameraValid, cameraPose,
                gtValid, gtPose,
                alignmentRef.ToString()));
        }

        // ── 渲染 tick：写 output 行 ──

        private void LateUpdate()
        {
            if (!_recording || _outputLog == null) return;

            double monoMs = UnityEngine.Time.realtimeSinceStartupAsDouble * 1000.0;
            double unixMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            (bool gtValid, Pose gtPose) = ResolveGtPose(monoMs);
            Pose headPose = headAnchor != null ? new Pose(headAnchor.position, headAnchor.rotation) : Pose.identity;

            // 计算 GT 速度（线速度 m/s，角速度 deg/s）
            float gtLinear = 0f, gtAngular = 0f;
            if (_hasLastGt && gtValid)
            {
                float dt = (float)((monoMs - _lastGtMonoMs) / 1000.0);
                if (dt > 1e-6f)
                {
                    gtLinear = (gtPose.position - _lastGtPose.position).magnitude / dt;
                    float dot = Mathf.Clamp01(Mathf.Abs(Quaternion.Dot(_lastGtPose.rotation, gtPose.rotation)));
                    gtAngular = 2f * Mathf.Acos(dot) * Mathf.Rad2Deg / dt;
                }
            }
            if (gtValid) { _lastGtPose = gtPose; _lastGtMonoMs = monoMs; _hasLastGt = true; }

            // 获取 RQ1 指标标记（如果有）；未绑定或未按键时为 none。
            string rq1Metric = "none";
            double rq1MetricDuration = 0.0;
            if (rq1Selector != null)
            {
                rq1Metric = rq1Selector.CurrentMetric.ToLogString();
                rq1MetricDuration = rq1Selector.CurrentMetricDuration;
            }

            // 获取 RQ2 试次上下文（如果有）；未绑定或未开始试次时使用显式空闲值。
            string rq2Condition = "none";
            int rq2TrialId = -1;
            float rq2TargetLinearSpeed = float.NaN;
            float rq2TargetAngularSpeed = float.NaN;
            if (rq2Selector != null)
            {
                rq2Condition = rq2Selector.CurrentCondition.ToLogString();
                rq2TrialId = rq2Selector.CurrentTrialId;
                rq2TargetLinearSpeed = rq2Selector.TargetLinearSpeedMs;
                rq2TargetAngularSpeed = rq2Selector.TargetAngularSpeedDegS;
            }

            long sourceFrameId = BuildSnapshots();
            _outputLog.Write(EvalJson.BuildOutputLine(
                monoMs, unixMs, UnityEngine.Time.frameCount, sourceFrameId,
                headPose, gtValid, gtPose,
                gtLinear, gtAngular, _snapshots,
                rq1Metric, rq1MetricDuration,
                rq2Condition, rq2TrialId,
                rq2TargetLinearSpeed, rq2TargetAngularSpeed));
        }

        // ── 内部辅助 ──

        private long BuildSnapshots()
        {
            _snapshots.Clear();
            long primary = -1;
            bool hasPrimary = false;

            for (int i = 0; i < variants.Count; i++)
            {
                EvalVariant ev = variants[i];
                PoseToAnchorRuntime rt = ev.runtime;
                string label = ResolveLabel(ev, i);

                bool hasRuntimeOutput = rt != null && rt.TryGetOutputPose(out _);
                DynamicObjectAnchor presenter = ev.anchorPresenter != null
                    ? ev.anchorPresenter
                    : rt != null ? rt.GetComponent<DynamicObjectAnchor>() : null;
                Pose displayPose = Pose.identity;
                bool hasDisplayPose = presenter != null
                    ? presenter.TryGetDisplayPose(out displayPose)
                    : hasRuntimeOutput && ev.anchorTransform != null;
                if (presenter == null)
                {
                    displayPose = hasDisplayPose
                        ? new Pose(ev.anchorTransform.position, ev.anchorTransform.rotation)
                        : Pose.identity;
                }
                string poseSource = hasDisplayPose
                    ? (hasRuntimeOutput ? "transform" : "hold_last")
                    : "none";

                bool hasRaw = false;
                Pose rawPose = Pose.identity;
                if (rt != null) hasRaw = rt.TryGetRawPose(out rawPose);
                bool hasArrival = false;
                Pose arrivalPose = Pose.identity;
                if (rt != null && ev.isPrimary) hasArrival = rt.TryGetArrivalTimeRawPose(out arrivalPose);

                long srcFrame = rt != null ? rt.LatestAlignedFrameId : -1;
                FramePoseRecord fr = default;
                bool hasTiming = framePoseHistory != null && framePoseHistory.TryGet(srcFrame, out fr);

                if (ev.isPrimary && !hasPrimary) { primary = srcFrame; hasPrimary = true; }

                _snapshots.Add(new EvalVariantSnapshot(
                    label, ev.isPrimary, srcFrame,
                    hasRuntimeOutput, hasDisplayPose, displayPose, poseSource,
                    hasTiming, hasTiming ? fr.ImageMonoMs : double.NaN,
                    hasTiming ? fr.ImageUnityFrame : -1,
                    rt != null ? rt.LatestObservationAgeMs             : double.NaN,
                    rt != null ? rt.LatestPolicyOutputTargetMonoMs     : double.NaN,
                    rt != null ? rt.LatestSmoothingDelayMs             : double.NaN,
                    rt != null ? rt.LatestUnityPoseHandleMonoMs        : double.NaN,
                    rt != null ? rt.CurrentAnchorState.ToString()   : "MissingRuntime",
                    rt != null ? rt.LatestPolicyAction               : string.Empty,
                    rt != null ? rt.LatestPolicyReason               : string.Empty,
                    rt != null ? rt.LatestPhase                      : string.Empty,
                    rt != null ? rt.LatestFailure                    : "missing_runtime",
                    rt != null ? rt.CurrentMotionStateName           : string.Empty,
                    rt != null ? rt.LatestPredictAheadMs             : double.NaN,
                    rt != null ? rt.StrategyLabel                    : string.Empty,
                    rt != null ? rt.QualityGateMode                  : string.Empty,
                    rt != null ? rt.MotionModelName                  : string.Empty,
                    rt != null ? rt.SmoothingStrategyName            : string.Empty,
                    ResolveCachedConfigHash(ev, label),
                    rt != null ? rt.LatestResidualMeters             : float.NaN,
                    rt != null ? rt.LatestResidualDegrees            : float.NaN,
                    rt != null ? rt.LatestAcceptedScore              : float.NaN,
                    rt != null && rt.LatestStaticLocked,
                    hasRaw, rawPose,
                    hasArrival, arrivalPose,
                    rt != null ? rt.LatestArrivalTimeRawMonoMs       : double.NaN,
                    rt != null ? rt.LatestArrivalTimeRawUnityFrame   : -1,
                    rt != null ? rt.LatestArrivalTimeCameraReference.ToString() : string.Empty,
                    rt != null ? rt.LatestReliabilityScore           : 0f));
            }

            if (!hasPrimary && _snapshots.Count > 0)
                primary = _snapshots[0].SourceFrameId;
            return primary;
        }

        private static string ResolveLabel(EvalVariant v, int index)
            => string.IsNullOrEmpty(v.label) ? $"variant_{index}" : v.label;

        private void RefreshConfigHashCache()
        {
            _configHashCache.Clear();
            for (int i = 0; i < variants.Count; i++)
            {
                string label = ResolveLabel(variants[i], i);
                _configHashCache[label] = BuildVariantConfig(variants[i], label).ConfigHash;
            }
        }

        /// <summary>
        /// 在录制开始时固定 manifest 所需的变体标签与配置。
        /// 停止录制后保留该快照，直至下一次录制开始并用新配置覆盖。
        /// </summary>
        private void CaptureManifestMetadata()
        {
            _manifestVariantLabels.Clear();
            _manifestVariantConfigs.Clear();
            for (int i = 0; i < variants.Count; i++)
            {
                EvalVariant variant = variants[i];
                string label = ResolveLabel(variant, i);
                _manifestVariantLabels.Add(label);
                _manifestVariantConfigs.Add(BuildVariantConfig(variant, label));
            }
            _hasManifestMetadataSnapshot = true;
        }

        private string ResolveCachedConfigHash(EvalVariant v, string label)
        {
            if (_configHashCache.TryGetValue(label, out string hash)) return hash;
            hash = BuildVariantConfig(v, label).ConfigHash;
            _configHashCache[label] = hash;
            return hash;
        }

        private static EvalVariantConfig BuildVariantConfig(EvalVariant ev, string label)
        {
            PoseToAnchorRuntime rt = ev.runtime;
            AnchorPolicyHost policy = rt != null ? rt.PolicyHost : null;
            string motionModel    = policy != null ? policy.MotionModelName    : (rt != null ? rt.MotionModelName    : string.Empty);
            string smoothing      = policy != null ? policy.SmoothingStrategyName : (rt != null ? rt.SmoothingStrategyName : string.Empty);
            string qualityGate    = rt != null ? rt.QualityGateMode : string.Empty;
            string hash           = ComputeHash(label, motionModel, smoothing, qualityGate);
            return new EvalVariantConfig(label, motionModel, smoothing, qualityGate, hash);
        }

        /// <summary>FNV-1a 配置摘要，确保相同配置产生相同 hash。</summary>
        private static string ComputeHash(string label, string motionModel, string smoothing, string qualityGate)
        {
            string raw = $"{label}|{motionModel}|{smoothing}|{qualityGate}";
            unchecked
            {
                const ulong offset = 14695981039346656037UL;
                const ulong prime  = 1099511628211UL;
                ulong hash = offset;
                foreach (byte b in Encoding.UTF8.GetBytes(raw)) { hash ^= b; hash *= prime; }
                return hash.ToString("x16", CultureInfo.InvariantCulture);
            }
        }

        /// <summary>
        /// 解析当前 GT pose，支持手柄 sleep keep-alive。
        /// <para>
        /// OVR 明确跟踪时：更新缓存，返回最新 pose（valid=true）。<br/>
        /// OVR 跟踪丢失但距上次跟踪 &lt; GtKeepAliveMs：复用缓存 pose（valid=true）——
        /// 适用于静止放置手柄进入休眠但位姿不变的情况。<br/>
        /// 超过 keep-alive 窗口 or 未绑定 GT：返回 identity（valid=false）。
        /// </para>
        /// </summary>
        private (bool valid, Pose pose) ResolveGtPose(double nowMonoMs)
        {
            if (groundTruth == null) return (false, Pose.identity);

            bool ovrTracked = gtController == OVRInput.Controller.None
                || (OVRInput.GetControllerPositionTracked(gtController)
                    && OVRInput.GetControllerOrientationTracked(gtController));

            if (ovrTracked)
            {
                _lastTrackedGtPose   = new Pose(groundTruth.position, groundTruth.rotation);
                _lastTrackedGtMonoMs = nowMonoMs;
                return (true, _lastTrackedGtPose);
            }

            // OVR 已报丢失——用 keep-alive 缓存
            if (_lastTrackedGtMonoMs >= 0.0 && (nowMonoMs - _lastTrackedGtMonoMs) < GtKeepAliveMs)
                return (true, _lastTrackedGtPose);

            return (false, Pose.identity);
        }
    }
}

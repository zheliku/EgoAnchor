using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using EgoAnchor.Alignment;
using EgoAnchor.Client;
using EgoAnchor.Diagnostics;
using EgoAnchor.Policy;
using EgoAnchor.Quest;
using EgoAnchor.Protocol.Generated;
using EgoAnchor.Runtime;
using UnityEngine;

namespace EgoAnchor.Eval
{
    /// <summary>
    /// 参考位姿有效性策略。静止实验可短时复用最后一次真实追踪位姿；动态实验必须要求当前样本真实可追踪。
    /// </summary>
    public enum EvalReferenceFreshnessMode
    {
        /// <summary>允许在真实追踪暂时丢失时复用最后一次新鲜位姿，适用于静止观察。</summary>
        AllowStaticKeepAlive = 0,

        /// <summary>只有当前真实追踪样本才有效，适用于动态运动试次。</summary>
        RequireFreshTracking = 1,
    }

    /// <summary>一次参考位姿解析结果，显式区分真实追踪样本与静止 keep-alive。</summary>
    public readonly struct EvalReferencePose
    {
        /// <summary>该 pose 是否可用于当前评估样本。</summary>
        public readonly bool Valid;

        /// <summary>当前样本是否来自真实、可追踪的 Transform 更新。</summary>
        public readonly bool Fresh;

        /// <summary>当前有效 pose 是否复用了最后一次真实追踪样本。</summary>
        public readonly bool KeepAlive;

        /// <summary>参考物体的 world pose；无效时为 identity。</summary>
        public readonly Pose Pose;

        /// <summary>距最后一次真实追踪样本的毫秒数；从未追踪到时为 NaN。</summary>
        public readonly double FreshAgeMs;

        /// <summary>构造一次参考位姿解析结果。</summary>
        public EvalReferencePose(bool valid, bool fresh, bool keepAlive, Pose pose, double freshAgeMs)
        {
            Valid = valid;
            Fresh = fresh;
            KeepAlive = keepAlive;
            Pose = pose;
            FreshAgeMs = freshAgeMs;
        }
    }

    /// <summary>
    /// 参考位姿新鲜度跟踪器。该纯 C# 状态对象不读取 OVR API，便于独立验证动态与静止有效性规则。
    /// </summary>
    public sealed class EvalReferencePoseTracker
    {
        /// <summary>最后一次真实追踪到的参考位姿。</summary>
        private Pose _lastFreshPose;

        /// <summary>最后一次真实追踪样本的 Unity 单调时钟毫秒。</summary>
        private double _lastFreshMonoMs = double.NaN;

        /// <summary>清空参考位姿历史，防止跨 session 复用旧样本。</summary>
        public void Reset()
        {
            _lastFreshPose = Pose.identity;
            _lastFreshMonoMs = double.NaN;
        }

        /// <summary>按当前追踪状态和有效性策略解析可写入评估日志的参考位姿。</summary>
        /// <param name="hasTransform">是否绑定了参考 Transform。</param>
        /// <param name="currentPose">当前参考 Transform 的 world pose。</param>
        /// <param name="freshlyTracked">当前样本是否由追踪系统确认有效。</param>
        /// <param name="nowMonoMs">当前 Unity 单调时钟毫秒。</param>
        /// <param name="mode">动态 fresh-only 或静止 keep-alive 策略。</param>
        /// <param name="keepAliveMs">允许复用最后新鲜 pose 的最长毫秒数。</param>
        /// <returns>带新鲜度诊断的参考位姿样本。</returns>
        public EvalReferencePose Resolve(
            bool hasTransform,
            Pose currentPose,
            bool freshlyTracked,
            double nowMonoMs,
            EvalReferenceFreshnessMode mode,
            double keepAliveMs)
        {
            if (!hasTransform)
            {
                return new EvalReferencePose(false, false, false, Pose.identity, double.NaN);
            }

            if (freshlyTracked)
            {
                _lastFreshPose = currentPose;
                _lastFreshMonoMs = nowMonoMs;
                return new EvalReferencePose(true, true, false, currentPose, 0.0);
            }

            double ageMs = double.IsNaN(_lastFreshMonoMs)
                ? double.NaN
                : Math.Max(0.0, nowMonoMs - _lastFreshMonoMs);
            bool mayKeepAlive = mode == EvalReferenceFreshnessMode.AllowStaticKeepAlive
                && !double.IsNaN(ageMs)
                && ageMs <= Math.Max(0.0, keepAliveMs);
            return mayKeepAlive
                ? new EvalReferencePose(true, false, true, _lastFreshPose, ageMs)
                : new EvalReferencePose(false, false, false, Pose.identity, ageMs);
        }
    }

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
    /// - 接收发布器的发送尝试通知，在采集帧时写 unity_reference 行；<br/>
    /// - 在 <c>LateUpdate</c> 每渲染 tick 写 unity_render 行（含各变体输出和参考速度）。
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
        /// 设为 RTouch / LTouch 后，由 gtFreshnessMode 决定丢跟时立即失效或静止 keep-alive。
        /// </summary>
        [Header("GT Validity")]
        [Tooltip("可选：OVR 手柄类型，用于检测手柄跟踪是否有效。设为 None 则不过滤。")]
        [SerializeField] private OVRInput.Controller gtController = OVRInput.Controller.RTouch;

        /// <summary>参考位姿新鲜度策略；动态试次要求真实追踪，静止观察可允许短时 keep-alive。</summary>
        [Tooltip("参考位姿有效性策略。动态试次选择 RequireFreshTracking；静止观察选择 AllowStaticKeepAlive。")]
        [SerializeField] private EvalReferenceFreshnessMode gtFreshnessMode = EvalReferenceFreshnessMode.AllowStaticKeepAlive;

        /// <summary>静止 keep-alive 最长持续时间，单位秒；fresh-only 模式下不使用。</summary>
        [Tooltip("真实追踪暂时丢失后，静止实验允许复用最后新鲜参考位姿的秒数；fresh-only 模式忽略此值。")]
        [Min(0f)]
        [SerializeField] private float gtKeepAliveSeconds = 30f;

        /// <summary>要录制的 runtime 变体列表；主变体（isPrimary=true）额外记录 aligned raw。</summary>
        [Header("Variants")]
        [Tooltip("要录制的 runtime 变体列表。")]
        [SerializeField] private List<EvalVariant> variants = new List<EvalVariant>();

        // ── State ──

        private EvalLog _referenceLog;
        private EvalLog _admissionLog;
        private EvalLog _renderLog;
        private EvalLog _eventsLog;
        private bool _recording;
        private string _sessionId = string.Empty;

        /// <summary>最近一次关闭的 capture 日志后台队列统计。</summary>
        private EvalLogStats _referenceLogStats;

        /// <summary>最近一次关闭的 output 日志后台队列统计。</summary>
        private EvalLogStats _admissionLogStats;

        /// <summary>最近一次关闭的 render 日志后台队列统计。</summary>
        private EvalLogStats _renderLogStats;

        /// <summary>最近一次关闭的 events 日志后台队列统计。</summary>
        private EvalLogStats _eventsLogStats;

        /// <summary>上一帧 GT pose，用于计算 GT 速度。</summary>
        private Pose _lastGtPose;
        private double _lastGtMonoMs;
        private bool _hasLastGt;

        /// <summary>跨帧维护最后一次真实追踪参考 pose 的纯 C# 状态对象。</summary>
        private readonly EvalReferencePoseTracker _gtPoseTracker = new EvalReferencePoseTracker();

        /// <summary>当前渲染 tick 复用的系统变体快照缓冲。</summary>
        private readonly List<EvalVariantSnapshot> _snapshots = new List<EvalVariantSnapshot>();

        /// <summary>录制期间按标签缓存的配置 hash，避免逐帧反射读取组件参数。</summary>
        private readonly Dictionary<string, string> _configHashCache = new Dictionary<string, string>(StringComparer.Ordinal);

        /// <summary>本 session 已写入的 candidate × variant admission key，避免重复行。</summary>
        private readonly HashSet<string> _admissionKeys = new HashSet<string>(StringComparer.Ordinal);

        /// <summary>已绑定 admission 回调的 runtime 集合，避免重复订阅。</summary>
        private readonly HashSet<PoseToAnchorRuntime> _admissionRuntimes = new HashSet<PoseToAnchorRuntime>();

        /// <summary>按 source frame 缓存 Unity 侧候选序号；同一帧的多变体共用一个 candidate_id。</summary>
        private readonly Dictionary<long, int> _candidateSequencesByFrame = new Dictionary<long, int>();

        /// <summary>下一个尚未分配的候选序号。</summary>
        private int _nextCandidateSequence;

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

        /// <summary>最近一次录制中 capture 日志因队列饱和或写入失败丢弃的行数。</summary>
        public long ReferenceDroppedRows => _referenceLogStats.DroppedRows;

        /// <summary>最近一次录制中 capture 日志观察到的最大待写队列深度。</summary>
        public int ReferencePeakQueueDepth => _referenceLogStats.PeakQueueDepth;

        /// <summary>最近一次录制中 output 日志因队列饱和或写入失败丢弃的行数。</summary>
        public long AdmissionDroppedRows => _admissionLogStats.DroppedRows;

        /// <summary>最近一次录制中 output 日志观察到的最大待写队列深度。</summary>
        public int AdmissionPeakQueueDepth => _admissionLogStats.PeakQueueDepth;

        /// <summary>最近一次录制中 render 日志丢弃的行数。</summary>
        public long RenderDroppedRows => _renderLogStats.DroppedRows;

        /// <summary>最近一次录制中 render 日志观察到的最大待写队列深度。</summary>
        public int RenderPeakQueueDepth => _renderLogStats.PeakQueueDepth;

        /// <summary>最近一次录制中 events 日志丢弃的行数。</summary>
        public long EventsDroppedRows => _eventsLogStats.DroppedRows;

        /// <summary>最近一次录制中 events 日志观察到的最大待写队列深度。</summary>
        public int EventsPeakQueueDepth => _eventsLogStats.PeakQueueDepth;

        /// <summary>reference 日志完整统计快照。</summary>
        public EvalLogStats ReferenceLogStats => _referenceLogStats;

        /// <summary>admission 日志完整统计快照。</summary>
        public EvalLogStats AdmissionLogStats => _admissionLogStats;

        /// <summary>render 日志完整统计快照。</summary>
        public EvalLogStats RenderLogStats => _renderLogStats;

        /// <summary>events 日志完整统计快照。</summary>
        public EvalLogStats EventsLogStats => _eventsLogStats;

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
        /// 主变体实际显示用 anchor Transform。实时误差按它与 GT 比较；
        /// 录制时它对应 display_pos，而 output_pos 独立来自 runtime 输出。
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
        /// 的门控逻辑标 reference_pose_valid，两者互不影响。
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
            EvalReferencePose sample = ResolveGtPose(nowMs);
            pose = sample.Pose;
            return sample.Valid;
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
        public void BeginRecording(string referencePath, string admissionPath, string renderPath, string eventsPath, string sessionId = "")
        {
            StopRecording();
            _sessionId = sessionId ?? string.Empty;
            RefreshAdmissionSubscriptions();
            _referenceLogStats = default;
            _admissionLogStats = default;
            _renderLogStats = default;
            _eventsLogStats = default;
            _referenceLog = new EvalLog(referencePath);
            _admissionLog = new EvalLog(admissionPath);
            _renderLog = new EvalLog(renderPath);
            _eventsLog = new EvalLog(eventsPath);
            RefreshConfigHashCache();
            CaptureManifestMetadata();
            _hasLastGt = false;
            _gtPoseTracker.Reset();
            _recording = true;
            _eventsLog.Write(EvalJson.BuildEventLine(
                _sessionId, "session_started", "unity", "recording_started",
                UnityEngine.Time.realtimeSinceStartupAsDouble * 1000.0, UnityEngine.Time.frameCount));
        }

        /// <summary>停止录制并关闭文件句柄。</summary>
        public void StopRecording()
        {
            _recording = false;
            if (_referenceLog != null)
            {
                _referenceLogStats = CloseLog(_referenceLog, "reference");
                _referenceLog = null;
            }
            if (_admissionLog != null)
            {
                _admissionLogStats = CloseLog(_admissionLog, "admission");
                _admissionLog = null;
            }
            if (_renderLog != null)
            {
                _renderLogStats = CloseLog(_renderLog, "render");
                _renderLog = null;
            }
            if (_eventsLog != null)
            {
                _eventsLog.Write(EvalJson.BuildEventLine(
                    _sessionId, "session_stopped", "unity", "recording_stopped",
                    UnityEngine.Time.realtimeSinceStartupAsDouble * 1000.0, UnityEngine.Time.frameCount));
                _eventsLogStats = CloseLog(_eventsLog, "events");
                _eventsLog = null;
            }
            _snapshots.Clear();
            _configHashCache.Clear();
            _admissionKeys.Clear();
            _candidateSequencesByFrame.Clear();
            _nextCandidateSequence = 0;
            _hasLastGt = false;
            _gtPoseTracker.Reset();
        }

        /// <summary>关闭单个后台日志并把丢行、队列峰值和异常写入统一日志门面。</summary>
        private static EvalLogStats CloseLog(EvalLog log, string name)
        {
            if (log == null) return default;

            log.Dispose();
            EvalLogStats stats = log.Stats;
            if (stats.DroppedRows > 0 || !string.IsNullOrEmpty(stats.Error))
            {
                EgoAnchorLog.For<EvalRecorder>().Warning(
                    $"评估 {name} 日志后台写入异常：dropped={stats.DroppedRows} peak_queue={stats.PeakQueueDepth} error={stats.Error}");
            }
            return stats;
        }

        // ── Unity 生命周期 ──

        private void OnEnable()
        {
            if (streamPublisher != null)
                streamPublisher.StereoPublishAttempted += RecordCapturePublishAttempt;
            RefreshAdmissionSubscriptions();
        }

        private void OnDisable()
        {
            if (streamPublisher != null)
                streamPublisher.StereoPublishAttempted -= RecordCapturePublishAttempt;
            ClearAdmissionSubscriptions();
        }

        private void OnDestroy() => StopRecording();

        private void OnValidate()
        {
            if (variants == null) variants = new List<EvalVariant>();
        }

        /// <summary>按 Inspector 变体列表绑定每个 runtime 的真实 admission 回调。</summary>
        private void RefreshAdmissionSubscriptions()
        {
            ClearAdmissionSubscriptions();
            for (int i = 0; i < variants.Count; i++)
            {
                PoseToAnchorRuntime runtime = variants[i].runtime;
                if (runtime != null && _admissionRuntimes.Add(runtime))
                    runtime.AdmissionProcessed += RecordAdmission;
            }
        }

        /// <summary>解除所有 admission 回调。</summary>
        private void ClearAdmissionSubscriptions()
        {
            foreach (PoseToAnchorRuntime runtime in _admissionRuntimes)
            {
                if (runtime != null)
                    runtime.AdmissionProcessed -= RecordAdmission;
            }
            _admissionRuntimes.Clear();
        }

        // ── 采集事件：写 capture 行 ──

        /// <param name="timing">本帧图像时间代理与 payload-ready 时间。</param>
        public void RecordCapturePublishAttempt(
            FrameCaptureTiming timing,
            double publishAttemptMonoMs,
            bool publishSucceeded)
        {
            if (!_recording || _referenceLog == null) return;

            FramePoseRecord fr = default;
            bool hasFrameRecord = framePoseHistory != null && framePoseHistory.TryGet(timing.FrameId, out fr);
            Pose cameraPose = Pose.identity;
            bool cameraValid = hasFrameRecord && fr.TryGetCameraPose(alignmentRef, out cameraPose);

            double unixMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            double gtSampleMonoMs = UnityEngine.Time.realtimeSinceStartupAsDouble * 1000.0;
            EvalReferencePose gtSample = ResolveGtPose(gtSampleMonoMs);
            Pose headPose = headAnchor != null ? new Pose(headAnchor.position, headAnchor.rotation) : Pose.identity;

            _referenceLog.Write(EvalJson.BuildReferenceLine(
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
                gtSample,
                alignmentRef.ToString(),
                _sessionId));
        }

        // ── 渲染 tick：写 output 行 ──

        private void LateUpdate()
        {
            if (!_recording || _renderLog == null) return;

            double monoMs = UnityEngine.Time.realtimeSinceStartupAsDouble * 1000.0;
            double unixMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            EvalReferencePose gtSample = ResolveGtPose(monoMs);
            Pose headPose = headAnchor != null ? new Pose(headAnchor.position, headAnchor.rotation) : Pose.identity;

            // 计算 GT 速度（线速度 m/s，角速度 deg/s）
            float gtLinear = 0f, gtAngular = 0f;
            if (_hasLastGt && gtSample.Valid)
            {
                float dt = (float)((monoMs - _lastGtMonoMs) / 1000.0);
                if (dt > 1e-6f)
                {
                    gtLinear = (gtSample.Pose.position - _lastGtPose.position).magnitude / dt;
                    float dot = Mathf.Clamp01(Mathf.Abs(Quaternion.Dot(_lastGtPose.rotation, gtSample.Pose.rotation)));
                    gtAngular = 2f * Mathf.Acos(dot) * Mathf.Rad2Deg / dt;
                }
            }
            if (gtSample.Valid)
            {
                _lastGtPose = gtSample.Pose;
                _lastGtMonoMs = monoMs;
                _hasLastGt = true;
            }
            else
            {
                _hasLastGt = false;
            }

            long sourceFrameId = BuildSnapshots();
            for (int i = 0; i < _snapshots.Count; i++)
            {
                _renderLog.Write(EvalJson.BuildRenderLine(
                    monoMs, unixMs, UnityEngine.Time.frameCount,
                    headPose, gtSample, gtLinear, gtAngular,
                    _snapshots[i], _sessionId));
            }
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

                Pose runtimeOutputPose = Pose.identity;
                bool hasRuntimeOutput = rt != null && rt.TryGetOutputPose(out runtimeOutputPose);
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
                    hasRuntimeOutput, runtimeOutputPose,
                    hasDisplayPose, displayPose, poseSource,
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

        /// <summary>把 runtime 实际处理结果写成 candidate × variant admission 长表行。</summary>
        private void RecordAdmission(
            PoseToAnchorRuntime runtime,
            PoseResult result,
            PoseToAnchorRuntime.AcceptResult acceptResult)
        {
            if (!_recording || _admissionLog == null || runtime == null || result?.Header == null)
                return;

            long frameId = result.Header.FrameId;
            string candidateId = BuildCandidateId(frameId);
            for (int i = 0; i < variants.Count; i++)
            {
                EvalVariant variant = variants[i];
                if (variant.runtime != runtime)
                    continue;

                string label = ResolveLabel(variant, i);
                if (!_admissionKeys.Add($"{candidateId}:{label}"))
                    continue;

                Pose rawPose = Pose.identity;
                bool hasRaw = acceptResult == PoseToAnchorRuntime.AcceptResult.Aligned
                    && runtime.TryGetRawPose(out rawPose);
                Pose arrivalPose = Pose.identity;
                bool hasArrival = runtime.TryGetArrivalTimeRawPose(out arrivalPose);
                string decision = runtime.LatestPolicyAction;
                if (string.IsNullOrEmpty(decision))
                    decision = ToAdmissionDecision(acceptResult);
                string reason = runtime.LatestPolicyReason;
                if (string.IsNullOrEmpty(reason))
                    reason = runtime.LatestFailure;

                _admissionLog.Write(EvalJson.BuildAdmissionLine(new EvalAdmissionSnapshot(
                    _sessionId,
                    candidateId,
                    frameId,
                    label,
                    label,
                    runtime.LatestUnityPoseHandleMonoMs,
                    runtime.UsesCaptureTimeAlignment ? WorldAlignmentMode.CaptureTime : WorldAlignmentMode.ArrivalTime,
                    runtime.UsesCaptureTimeAlignment,
                    hasRaw,
                    hasRaw ? rawPose : Pose.identity,
                    hasArrival,
                    hasArrival ? arrivalPose : Pose.identity,
                    runtime.QualityGateMode == "enabled",
                    runtime.LatestReliabilityScore,
                    decision,
                    reason,
                    runtime.CurrentAnchorState.ToString(),
                    ResolveCachedConfigHash(variant, label))));
            }
        }

        private static string ToAdmissionDecision(PoseToAnchorRuntime.AcceptResult result)
        {
            switch (result)
            {
                case PoseToAnchorRuntime.AcceptResult.Aligned: return "aligned";
                case PoseToAnchorRuntime.AcceptResult.NoPose: return "no_pose";
                case PoseToAnchorRuntime.AcceptResult.InvalidMatrix: return "invalid_matrix";
                default: return "align_failed";
            }
        }

        /// <summary>构造与 Python candidate 行可配对的 Unity candidate 标识。</summary>
        private string BuildCandidateId(long frameId)
        {
            if (!_candidateSequencesByFrame.TryGetValue(frameId, out int sequence))
            {
                sequence = ++_nextCandidateSequence;
                _candidateSequencesByFrame[frameId] = sequence;
            }
            return $"{_sessionId}:{frameId}:{sequence}";
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
            return new EvalVariantConfig(
                label,
                motionModel,
                smoothing,
                qualityGate,
                hash,
                rt != null ? rt.WorldAlignmentModeName : string.Empty,
                rt != null && rt.UsesCaptureTimeAlignment,
                qualityGate == "enabled",
                smoothing.IndexOf("Delayed", StringComparison.OrdinalIgnoreCase) >= 0
                    || smoothing.IndexOf("Hermite", StringComparison.OrdinalIgnoreCase) >= 0,
                policy != null && policy.LatestStaticLocked);
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
        /// 解析当前参考 pose，并按场景配置应用动态 fresh-only 或静止 keep-alive。
        /// <para>
        /// OVR 明确跟踪时更新新鲜样本；fresh-only 丢跟后立即无效，keep-alive 模式可短时复用静止 pose。
        /// </para>
        /// </summary>
        private EvalReferencePose ResolveGtPose(double nowMonoMs)
        {
            bool hasTransform = groundTruth != null;
            Pose currentPose = hasTransform
                ? new Pose(groundTruth.position, groundTruth.rotation)
                : Pose.identity;
            bool freshlyTracked = hasTransform && (gtController == OVRInput.Controller.None
                || (OVRInput.GetControllerPositionTracked(gtController)
                    && OVRInput.GetControllerOrientationTracked(gtController)));
            return _gtPoseTracker.Resolve(
                hasTransform,
                currentPose,
                freshlyTracked,
                nowMonoMs,
                gtFreshnessMode,
                gtKeepAliveSeconds * 1000.0);
        }
    }
}

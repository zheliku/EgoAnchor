using System;
using System.Collections.Generic;
using System.Globalization;
using System.Runtime.CompilerServices;
using System.Text;
using EgoAnchor.Alignment;
using EgoAnchor.Client;
using EgoAnchor.Diagnostics;
using EgoAnchor.Eval.Experiment;
using EgoAnchor.Policy;
using EgoAnchor.Quest;
using EgoAnchor.Protocol.Generated;
using EgoAnchor.Runtime;
using UnityEngine;

namespace EgoAnchor.Eval
{
    /// <summary>一次参考位姿解析结果，显式区分激活 Transform 与失活后的保持状态。</summary>
    public readonly struct EvalReferencePose
    {
        /// <summary>该 pose 是否可用于当前评估样本。</summary>
        public readonly bool Valid;

        /// <summary>当前样本是否来自激活状态下的 Transform 更新。</summary>
        public readonly bool Fresh;

        /// <summary>当前有效 pose 是否复用了最后一次激活状态下的 Transform。</summary>
        public readonly bool KeepAlive;

        /// <summary>参考物体的 world pose；无效时为 identity。</summary>
        public readonly Pose Pose;

        /// <summary>距最后一次激活 Transform 样本的毫秒数；从未激活时为 NaN。</summary>
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
    /// 参考 Transform 保持器。激活时更新 world pose，失活或隐藏后无限期保持最后一次激活 pose。
    /// </summary>
    public sealed class EvalReferencePoseTracker
    {
        /// <summary>最后一次激活状态下读取到的参考位姿。</summary>
        private Pose _lastActivePose;

        /// <summary>最后一次激活 Transform 样本的 Unity 单调时钟毫秒。</summary>
        private double _lastActiveMonoMs = double.NaN;

        /// <summary>清空参考位姿历史，防止跨 session 复用旧样本。</summary>
        public void Reset()
        {
            _lastActivePose = Pose.identity;
            _lastActiveMonoMs = double.NaN;
        }

        /// <summary>按 Transform 激活状态解析可写入评估日志和实时面板的参考位姿。</summary>
        /// <param name="hasTransform">是否绑定了参考 Transform。</param>
        /// <param name="currentPose">当前参考 Transform 的 world pose。</param>
        /// <param name="active">参考对象当前是否激活且平台报告控制器可追踪。</param>
        /// <param name="nowMonoMs">当前 Unity 单调时钟毫秒。</param>
        /// <returns>带新鲜度诊断的参考位姿样本。</returns>
        public EvalReferencePose Resolve(
            bool hasTransform,
            Pose currentPose,
            bool active,
            double nowMonoMs)
        {
            if (!hasTransform)
            {
                return new EvalReferencePose(false, false, false, Pose.identity, double.NaN);
            }

            if (active)
            {
                _lastActivePose = currentPose;
                _lastActiveMonoMs = nowMonoMs;
                return new EvalReferencePose(true, true, false, currentPose, 0.0);
            }

            double ageMs = double.IsNaN(_lastActiveMonoMs)
                ? double.NaN
                : Math.Max(0.0, nowMonoMs - _lastActiveMonoMs);
            return !double.IsNaN(ageMs)
                ? new EvalReferencePose(true, false, true, _lastActivePose, ageMs)
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

        /// <summary>平台参考 Transform；位姿始终从该 Transform 读取，不把 OVR 状态当作另一套 pose 来源。</summary>
        [Header("Platform Reference")]
        [Tooltip("平台参考 Transform。激活时更新位姿，失活或隐藏时保持最后一次激活位姿。")]
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
        /// 可选：用于显示平台参考手柄当前是否激活的 OVR 控制器类型。
        /// 该状态只决定是否更新 Transform 快照；参考 pose 始终来自 groundTruth Transform。
        /// </summary>
        [Header("Platform Reference State")]
        [Tooltip("用于判断平台参考当前是否激活。设为 None 时仅使用 Transform 的层级激活状态。")]
        [SerializeField] private OVRInput.Controller gtController = OVRInput.Controller.RTouch;

        /// <summary>参考预检要求观察到的最小平移，单位米。</summary>
        [Min(0.001f)]
        [Tooltip("开始正式 session 前，平台参考至少需要产生该平移或下方旋转量，防止绑定到不会更新的静态对象。")]
        [SerializeField] private float referencePreflightTranslationMeters = 0.01f;

        /// <summary>参考预检要求观察到的最小旋转，单位度。</summary>
        [Min(0.1f)]
        [Tooltip("开始正式 session 前，平台参考至少需要产生该旋转或上方平移量。")]
        [SerializeField] private float referencePreflightRotationDegrees = 5f;

        /// <summary>要录制的 runtime 变体列表；主变体（isPrimary=true）额外记录 aligned raw。</summary>
        [Header("Variants")]
        [Tooltip("要录制的 runtime 变体列表。")]
        [SerializeField] private List<EvalVariant> variants = new List<EvalVariant>();

        /// <summary>实验上下文选择器；其状态会写入 admission/render/events 长表。</summary>
        [Header("Experiment Context")]
        [Tooltip("实验一/实验二上下文选择器；状态由 selector 统一维护并写入日志。")]
        [SerializeField] private ExperimentTrialSelector experimentSelector;

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

        /// <summary>参考预检第一次激活时的位姿。</summary>
        private Pose _referencePreflightOrigin;

        /// <summary>是否已经观察到参考对象的激活位姿。</summary>
        private bool _hasReferencePreflightOrigin;

        /// <summary>参考对象是否在本次 Play 生命周期中产生过可验证运动。</summary>
        private bool _referencePreflightPassed;

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

        /// <summary>按 PoseResult 对象缓存 candidate_id，确保所有 runtime 回调复用同一标识。</summary>
        private ConditionalWeakTable<PoseResult, CandidateIdHolder> _candidateIdsByResult =
            new ConditionalWeakTable<PoseResult, CandidateIdHolder>();

        /// <summary>会话开始时固定的变体标签，供停止后写 manifest。</summary>
        private readonly List<string> _manifestVariantLabels = new List<string>();

        /// <summary>会话开始时固定的变体配置，避免 runtime 销毁后摘要退化为空值。</summary>
        private readonly List<EvalVariantConfig> _manifestVariantConfigs = new List<EvalVariantConfig>();

        /// <summary>当前是否已经保存可供 manifest 使用的会话配置快照。</summary>
        private bool _hasManifestMetadataSnapshot;

        /// <summary>当前实验上下文快照。</summary>
        private ExperimentContext CurrentExperimentContext => experimentSelector != null
            ? experimentSelector.CurrentContext
            : default;

        // ── Public API ──

        /// <summary>GT Transform 名称，写入 manifest。</summary>
        public string GtTransformName => groundTruth != null ? groundTruth.name : string.Empty;

        /// <summary>平台参考 Transform 的完整场景层级路径，写入 manifest 供审计。</summary>
        public string PlatformReferenceTransformPath => BuildTransformPath(groundTruth);

        /// <summary>平台参考使用的 OVR 控制器枚举名，写入 manifest 供审计。</summary>
        public string PlatformReferenceController => gtController.ToString();

        /// <summary>本次 Play 生命周期是否观察到平台参考的有效运动。</summary>
        public bool PlatformReferencePreflightPassed => _referencePreflightPassed;

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
        /// 主变体实际显示用 anchor Transform。实时差异按它与平台控制器参考比较；
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

        /// <summary>主变体在 manifest 和实时诊断中使用的稳定标签。</summary>
        public string PrimaryVariantLabel
        {
            get
            {
                EvalVariant primary = ResolvePrimaryVariant();
                return primary.label ?? string.Empty;
            }
        }

        /// <summary>
        /// 读取主变体当前实际显示的 pose。优先使用 presenter，以保留 hold-last 与隐藏语义；
        /// 没有 presenter 时，仅在 runtime 有 output 且 Transform 已绑定时回退。
        /// </summary>
        /// <param name="pose">当前用户可见的 world pose。</param>
        /// <returns>主变体当前是否实际显示 pose。</returns>
        public bool TryGetPrimaryDisplayPose(out Pose pose)
        {
            EvalVariant primary = ResolvePrimaryVariant();
            DynamicObjectAnchor presenter = primary.anchorPresenter != null
                ? primary.anchorPresenter
                : primary.runtime != null ? primary.runtime.GetComponent<DynamicObjectAnchor>() : null;
            if (presenter != null)
                return presenter.TryGetDisplayPose(out pose);

            bool hasOutput = primary.runtime != null && primary.runtime.TryGetOutputPose(out _);
            bool hasDisplay = hasOutput && primary.anchorTransform != null;
            pose = hasDisplay
                ? new Pose(primary.anchorTransform.position, primary.anchorTransform.rotation)
                : Pose.identity;
            return hasDisplay;
        }

        /// <summary>frame_id → 图像时间代理 pose/时间缓存，用于反查 ImageMonoMs 算观测年龄。</summary>
        public FramePoseHistory FrameHistory => framePoseHistory;

        /// <summary>
        /// 读取平台控制器参考的统一 Transform 快照，并独立报告当前激活状态。
        /// 实时面板与正式日志共用 <see cref="EvalReferencePoseTracker"/>，失活时均保持最后一次激活 pose。
        /// 返回的参考不是外部光学真值。
        /// </summary>
        /// <param name="pose">有效时输出当前或保持中的参考 world pose。</param>
        /// <param name="active">参考对象当前是否激活；未绑定或保持中为 false。</param>
        /// <returns>当前或保持中的参考 pose 是否有效。</returns>
        public bool TryGetLiveReferencePose(out Pose pose, out bool active)
        {
            double nowMs = UnityEngine.Time.realtimeSinceStartupAsDouble * 1000.0;
            EvalReferencePose sample = ResolveGtPose(nowMs);
            pose = sample.Pose;
            active = sample.Fresh;
            return sample.Valid;
        }

        /// <summary>
        /// 验证正式采集使用的平台参考绑定和本次 Play 生命周期的运动预检。
        /// controller_right 必须绑定右手 OVRControllerVisual 的 prefab 根节点，不能只靠重名对象通过。
        /// </summary>
        public bool TryValidatePlatformReference(string objectId, out string error)
        {
            if (groundTruth == null)
            {
                error = "platformReferenceTransform";
                return false;
            }

            if (string.Equals(objectId, "controller_right", StringComparison.Ordinal))
            {
                const string expectedPath =
                    "OVRCameraRig/OVRInteractionComprehensive/OVRControllerVisualRight/OVRControllerPrefab";
                if (!string.Equals(
                        PlatformReferenceTransformPath,
                        expectedPath,
                        StringComparison.Ordinal))
                {
                    error = $"platformReferencePath[{PlatformReferenceTransformPath}]";
                    return false;
                }
                OVRControllerHelper helper = groundTruth.GetComponent<OVRControllerHelper>();
                if (helper == null || helper.m_controller != OVRInput.Controller.RTouch
                    || gtController != OVRInput.Controller.RTouch)
                {
                    error = "platformReferenceController[expected RTouch]";
                    return false;
                }
            }

            if (!_referencePreflightPassed)
            {
                error = "platformReferencePreflight[move the reference controller before starting]";
                return false;
            }

            error = string.Empty;
            return true;
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

        /// <summary>复制本 session 最终未作废的完成任务，供 manifest 固化模块化采集范围。</summary>
        public void CollectCompletedTasks(List<CompletedExperimentTask> tasks)
        {
            if (tasks == null) throw new ArgumentNullException(nameof(tasks));
            tasks.Clear();
            experimentSelector?.CollectCompletedTasks(tasks);
        }

        /// <summary>验证当前变体的标签、runtime 绑定和配置 hash 是否可用于正式采集。</summary>
        public bool TryValidateCurrentVariants(out string error)
        {
            error = string.Empty;
            if (variants == null || variants.Count == 0)
            {
                error = "variantConfigs";
                return false;
            }

            var labels = new HashSet<string>(StringComparer.Ordinal);
            for (int i = 0; i < variants.Count; i++)
            {
                EvalVariant variant = variants[i];
                string label = ResolveLabel(variant, i);
                if (!labels.Add(label))
                {
                    error = $"duplicateVariantLabel[{label}]";
                    return false;
                }
                if (variant.runtime == null)
                {
                    error = $"variantRuntime[{label}]";
                    return false;
                }
                if (string.IsNullOrWhiteSpace(BuildVariantConfig(variant, label).ConfigHash))
                {
                    error = $"variantConfigHash[{label}]";
                    return false;
                }
            }
            return true;
        }

        /// <summary>开始写入评估日志。</summary>
        public void BeginRecording(string referencePath, string admissionPath, string renderPath, string eventsPath, string sessionId = "")
        {
            StopRecording();
            _referenceLogStats = default;
            _admissionLogStats = default;
            _renderLogStats = default;
            _eventsLogStats = default;
            try
            {
                _referenceLog = new EvalLog(referencePath);
                _admissionLog = new EvalLog(admissionPath);
                _renderLog = new EvalLog(renderPath);
                // Python 运行在远端机器，不能与 Unity 通过本地 lock 文件共享追加。
                // 这里写本机独占分片，停止后由 schema-v2 finalize 合并为 events.jsonl。
                _eventsLog = new EvalLog(eventsPath);
            }
            catch
            {
                CloseOpenLogsAfterStartFailure();
                throw;
            }

            _sessionId = sessionId ?? string.Empty;
            RefreshAdmissionSubscriptions();
            RefreshConfigHashCache();
            CaptureManifestMetadata();
            _hasLastGt = false;
            _recording = true;
            _eventsLog.Write(EvalJson.BuildEventLine(
                _sessionId, "session_started", "unity", "recording_started",
                UnityEngine.Time.realtimeSinceStartupAsDouble * 1000.0, UnityEngine.Time.frameCount,
                CurrentExperimentContext.ExperimentId, CurrentExperimentContext.ScenarioId,
                CurrentExperimentContext.TrialId, CurrentExperimentContext.EventId,
                CurrentExperimentContext.ConditionId, CurrentExperimentContext.EventRole));
        }

        /// <summary>录制启动中途失败时关闭已经打开的文件和后台线程。</summary>
        private void CloseOpenLogsAfterStartFailure()
        {
            _referenceLog?.Dispose();
            _referenceLog = null;
            _admissionLog?.Dispose();
            _admissionLog = null;
            _renderLog?.Dispose();
            _renderLog = null;
            _eventsLog?.Dispose();
            _eventsLog = null;
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
                    UnityEngine.Time.realtimeSinceStartupAsDouble * 1000.0, UnityEngine.Time.frameCount,
                    CurrentExperimentContext.ExperimentId, CurrentExperimentContext.ScenarioId,
                    CurrentExperimentContext.TrialId, CurrentExperimentContext.EventId,
                    CurrentExperimentContext.ConditionId, CurrentExperimentContext.EventRole));
                _eventsLogStats = CloseLog(_eventsLog, "events");
                _eventsLog = null;
            }
            _snapshots.Clear();
            _configHashCache.Clear();
            _admissionKeys.Clear();
            _candidateSequencesByFrame.Clear();
            _candidateIdsByResult = new ConditionalWeakTable<PoseResult, CandidateIdHolder>();
            _hasLastGt = false;
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
            _gtPoseTracker.Reset();
            _referencePreflightOrigin = Pose.identity;
            _hasReferencePreflightOrigin = false;
            _referencePreflightPassed = false;
            if (streamPublisher != null)
            {
                streamPublisher.StereoPublishAttempted += RecordCapturePublishAttempt;
                streamPublisher.VrFocusChanged += RecordVrFocusChanged;
            }
            RefreshAdmissionSubscriptions();
            if (experimentSelector != null)
                experimentSelector.ContextEvent += RecordExperimentEvent;
        }

        /// <summary>在 session 启动前持续观察平台参考，确认绑定对象确实会更新。</summary>
        private void Update()
        {
            if (_referencePreflightPassed) return;
            double nowMs = UnityEngine.Time.realtimeSinceStartupAsDouble * 1000.0;
            EvalReferencePose sample = ResolveGtPose(nowMs);
            if (!sample.Fresh) return;
            if (!_hasReferencePreflightOrigin)
            {
                _referencePreflightOrigin = sample.Pose;
                _hasReferencePreflightOrigin = true;
                return;
            }

            float translation = Vector3.Distance(
                _referencePreflightOrigin.position,
                sample.Pose.position);
            float rotation = Quaternion.Angle(
                _referencePreflightOrigin.rotation,
                sample.Pose.rotation);
            _referencePreflightPassed = translation >= referencePreflightTranslationMeters
                || rotation >= referencePreflightRotationDegrees;
        }

        private void OnDisable()
        {
            if (streamPublisher != null)
            {
                streamPublisher.StereoPublishAttempted -= RecordCapturePublishAttempt;
                streamPublisher.VrFocusChanged -= RecordVrFocusChanged;
            }
            ClearAdmissionSubscriptions();
            if (experimentSelector != null)
                experimentSelector.ContextEvent -= RecordExperimentEvent;
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
                    _snapshots[i], _sessionId,
                    CurrentExperimentContext.ExperimentId, CurrentExperimentContext.ScenarioId,
                    CurrentExperimentContext.TrialId, CurrentExperimentContext.EventId,
                    CurrentExperimentContext.ConditionId));
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
                if (srcFrame < 0 && hasDisplayPose && presenter != null)
                {
                    srcFrame = presenter.LastAppliedFrameId;
                }
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
            string candidateId = BuildCandidateId(result);
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
                string reason = runtime.LatestPolicyReason;
                if (string.IsNullOrEmpty(reason))
                    reason = runtime.LatestFailure;

                AnchorPolicyHost policy = runtime.PolicyHost;
                FramePoseRecord sourceRecord = default;
                bool hasSourceTiming = framePoseHistory != null && framePoseHistory.TryGet(frameId, out sourceRecord);
                bool hasPolicy = policy != null;
                bool hasArrivalTiming = hasArrival && !double.IsNaN(runtime.LatestArrivalTimeRawMonoMs);
                string policyAction = runtime.LatestPolicyAction;
                string admissionDecision = ToAdmissionDecision(acceptResult, policyAction);

                _admissionLog.Write(EvalJson.BuildAdmissionLine(new EvalAdmissionSnapshot(
                    _sessionId,
                    candidateId,
                    frameId,
                    label,
                    label,
                    runtime.LatestUnityPoseHandleMonoMs,
                    Time.frameCount,
                    runtime.UsesCaptureTimeAlignment ? WorldAlignmentMode.CaptureTime : WorldAlignmentMode.ArrivalTime,
                    runtime.UsesCaptureTimeAlignment,
                    hasSourceTiming ? sourceRecord.ImageMonoMs : double.NaN,
                    hasSourceTiming ? sourceRecord.ImageUnityFrame : -1,
                    hasRaw,
                    hasRaw ? rawPose : Pose.identity,
                    hasArrival,
                    hasArrival ? arrivalPose : Pose.identity,
                    hasArrivalTiming ? runtime.LatestArrivalTimeRawMonoMs : double.NaN,
                    hasPolicy && policy.UsesVcdAdmission,
                    runtime.LatestReliabilityScore,
                    admissionDecision,
                    policyAction,
                    reason,
                    runtime.CurrentAnchorState.ToString(),
                    hasPolicy ? policy.QualityGateMode : runtime.QualityGateMode,
                    hasPolicy ? policy.MotionModelName : runtime.MotionModelName,
                    hasPolicy ? policy.SmoothingStrategyName : runtime.SmoothingStrategyName,
                    hasPolicy && policy.UsesTemporalSynthesis,
                    hasPolicy && policy.UsesStaticLock,
                    ResolveCachedConfigHash(variant, label),
                    CurrentExperimentContext.ExperimentId,
                    CurrentExperimentContext.ScenarioId,
                    CurrentExperimentContext.TrialId,
                    CurrentExperimentContext.EventId,
                    CurrentExperimentContext.ConditionId)));
            }
        }

        /// <summary>把 trial、场景和人工事件变化写入 events.jsonl。</summary>
        private void RecordExperimentEvent(ExperimentContext context, string eventType)
        {
            if (!_recording || _eventsLog == null) return;
            _eventsLog.Write(EvalJson.BuildEventLine(
                _sessionId, eventType, "experiment_ui", eventType,
                UnityEngine.Time.realtimeSinceStartupAsDouble * 1000.0,
                UnityEngine.Time.frameCount,
                context.ExperimentId, context.ScenarioId, context.TrialId,
                context.EventId, context.ConditionId, context.EventRole));
        }

        /// <summary>把 Quest Link/OpenXR 的 VR focus 丢失和恢复写入 Unity 事件流。</summary>
        private void RecordVrFocusChanged(bool hasFocus)
        {
            if (!_recording || _eventsLog == null) return;
            ExperimentContext context = CurrentExperimentContext;
            string eventType = hasFocus ? "xr_focus_acquired" : "xr_focus_lost";
            string state = hasFocus ? "focused" : "unfocused";
            _eventsLog.Write(EvalJson.BuildEventLine(
                _sessionId, eventType, "unity_xr", state,
                UnityEngine.Time.realtimeSinceStartupAsDouble * 1000.0,
                UnityEngine.Time.frameCount,
                context.ExperimentId, context.ScenarioId, context.TrialId,
                context.EventId, context.ConditionId, context.EventRole));
        }

        private static string ToAdmissionDecision(PoseToAnchorRuntime.AcceptResult result, string policyAction)
        {
            if (result == PoseToAnchorRuntime.AcceptResult.Aligned)
            {
                if (string.Equals(policyAction, nameof(AnchorPolicyAction.Accept), StringComparison.OrdinalIgnoreCase)
                    || string.Equals(policyAction, nameof(AnchorPolicyAction.Snap), StringComparison.OrdinalIgnoreCase))
                    return "accepted";
                return "rejected";
            }

            switch (result)
            {
                case PoseToAnchorRuntime.AcceptResult.NoPose: return "no_pose";
                case PoseToAnchorRuntime.AcceptResult.InvalidMatrix: return "invalid_matrix";
                default: return "align_failed";
            }
        }

        /// <summary>构造与 Python candidate 行可配对的 Unity candidate 标识。</summary>
        private string BuildCandidateId(PoseResult result)
        {
            if (result == null || result.Header == null)
                return string.Empty;

            if (_candidateIdsByResult.TryGetValue(result, out CandidateIdHolder existing))
                return existing.Value;

            long frameId = result.Header.FrameId;
            if (!_candidateSequencesByFrame.TryGetValue(frameId, out int sequence))
                sequence = 0;
            sequence++;
            _candidateSequencesByFrame[frameId] = sequence;
            string candidateId = $"{_sessionId}:{frameId}:{sequence}";
            _candidateIdsByResult.Add(result, new CandidateIdHolder(candidateId));
            return candidateId;
        }

        /// <summary>弱引用表的 candidate id 值对象。</summary>
        private sealed class CandidateIdHolder
        {
            /// <summary>跨端稳定 candidate id。</summary>
            public readonly string Value;

            /// <summary>构造不可变 candidate id 值。</summary>
            public CandidateIdHolder(string value) => Value = value ?? string.Empty;
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
            string motionConfig   = policy != null ? policy.MotionModelConfiguration : string.Empty;
            string smoothing      = policy != null ? policy.SmoothingStrategyName : (rt != null ? rt.SmoothingStrategyName : string.Empty);
            string qualityGate    = rt != null ? rt.QualityGateMode : string.Empty;
            string worldAlignment = rt != null ? rt.WorldAlignmentModeName : string.Empty;
            bool usesCaptureTime  = rt != null && rt.UsesCaptureTimeAlignment;
            bool usesVcd          = policy != null && policy.UsesVcdAdmission;
            bool usesTemporal     = policy != null && policy.UsesTemporalSynthesis;
            bool usesStaticLock   = policy != null && policy.UsesStaticLock;
            bool usesLowScore     = policy != null && policy.UsesLowScoreReacquire;
            bool usesServer       = policy != null && policy.UsesServerReacquire;
            string configurationFingerprint = string.Join(
                "|",
                rt != null ? rt.AlignmentConfigurationFingerprint : string.Empty,
                motionConfig,
                policy != null ? policy.SmoothingStrategyConfiguration : string.Empty,
                policy != null ? policy.ConfigurationFingerprint : string.Empty);
            string hash = ComputeHash(
                label, motionModel, smoothing, qualityGate, worldAlignment,
                configurationFingerprint,
                usesCaptureTime, usesVcd, usesTemporal, usesStaticLock, usesLowScore, usesServer);
            return new EvalVariantConfig(
                label,
                motionModel,
                smoothing,
                qualityGate,
                hash,
                worldAlignment,
                usesCaptureTime,
                usesVcd,
                usesTemporal,
                usesStaticLock,
                usesLowScore,
                usesServer,
                configurationFingerprint);
        }

        /// <summary>FNV-1a 配置摘要，确保相同配置产生相同 hash。</summary>
        private static string ComputeHash(
            string label,
            string motionModel,
            string smoothing,
            string qualityGate,
            string worldAlignment,
            string configurationFingerprint,
            bool usesCaptureTime,
            bool usesVcd,
            bool usesTemporal,
            bool usesStaticLock,
            bool usesLowScore,
            bool usesServer)
        {
            string raw = string.Join("|", new[]
            {
                label,
                motionModel,
                smoothing,
                qualityGate,
                worldAlignment,
                configurationFingerprint,
                usesCaptureTime ? "1" : "0",
                usesVcd ? "1" : "0",
                usesTemporal ? "1" : "0",
                usesStaticLock ? "1" : "0",
                usesLowScore ? "1" : "0",
                usesServer ? "1" : "0",
            });
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
        /// 解析当前平台参考 pose。位姿只从 Transform 读取，OVR 状态只决定是否更新快照。
        /// <para>
        /// 参考对象激活时更新；失活或隐藏时无限期保持最后一次激活 world pose，重新激活后继续更新。
        /// </para>
        /// </summary>
        private EvalReferencePose ResolveGtPose(double nowMonoMs)
        {
            bool hasTransform = groundTruth != null;
            Pose currentPose = hasTransform
                ? new Pose(groundTruth.position, groundTruth.rotation)
                : Pose.identity;
            bool active = hasTransform && groundTruth.gameObject.activeInHierarchy
                && (gtController == OVRInput.Controller.None
                || (OVRInput.GetControllerPositionTracked(gtController)
                    && OVRInput.GetControllerOrientationTracked(gtController)));
            return _gtPoseTracker.Resolve(
                hasTransform,
                currentPose,
                active,
                nowMonoMs);
        }

        /// <summary>返回包含场景根节点的 Transform 层级路径。</summary>
        private static string BuildTransformPath(Transform target)
        {
            if (target == null) return string.Empty;
            var names = new Stack<string>();
            for (Transform current = target; current != null; current = current.parent)
                names.Push(current.name);
            return string.Join("/", names);
        }
    }
}

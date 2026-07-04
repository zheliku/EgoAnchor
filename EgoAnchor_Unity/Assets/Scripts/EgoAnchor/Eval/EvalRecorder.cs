using System;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using System.Text;
using EgoAnchor.Alignment;
using EgoAnchor.Eval.RQ1;
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

        /// <summary>是否为主变体；主变体额外记录 aligned raw / arrival-time raw / reliability。</summary>
        [Tooltip("是否为主变体；主变体额外记录 aligned raw 和 reliability score。")]
        public bool isPrimary;
    }

    /// <summary>
    /// EgoAnchor 评估数据记录器。
    /// <para>
    /// - 订阅 <see cref="StereoFrameSource.FrameCaptured"/> 事件，在采集帧时写 unity_capture 行；<br/>
    /// - 在 <c>LateUpdate</c> 每渲染 tick 写 unity_output 行（含各变体输出和 GT 速度）。
    /// </para>
    /// </summary>
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

        /// <summary>frame_id → capture-time pose/timing 缓存，用于 source_capture_mono_ms。</summary>
        [Tooltip("frame_id → capture-time pose 缓存；必须与 StereoFrameSource / PoseToAnchorRuntime 共用同一实例。")]
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

        /// <summary>可选：RQ1 指标记录器，用于记录手动标记的指标类型。</summary>
        [Header("RQ1 Metrics (Optional)")]
        [Tooltip("可选：RQ1 指标记录器；若绑定，则在 output 行中记录当前指标。")]
        [SerializeField] private RQ1MetricRecorder rq1Recorder;

        // ── State ──

        private EvalLog _captureLog;
        private EvalLog _outputLog;
        private bool _recording;

        /// <summary>上一帧 GT pose，用于计算 GT 速度。</summary>
        private Pose _lastGtPose;
        private double _lastGtMonoMs;
        private bool _hasLastGt;

        private readonly List<EvalVariantSnapshot> _snapshots = new List<EvalVariantSnapshot>();
        private readonly Dictionary<string, string> _configHashCache = new Dictionary<string, string>(StringComparer.Ordinal);

        // ── Public API ──

        /// <summary>GT Transform 名称，写入 manifest。</summary>
        public string GtTransformName => groundTruth != null ? groundTruth.name : string.Empty;

        /// <summary>GT 来源标识，写入 manifest。</summary>
        public string GtSource => groundTruth != null ? "transform" : "transform_missing";

        /// <summary>收集当前变体标签列表，写入 manifest。</summary>
        public void CollectVariantLabels(List<string> labels)
        {
            if (labels == null) return;
            labels.Clear();
            for (int i = 0; i < variants.Count; i++)
                labels.Add(ResolveLabel(variants[i], i));
        }

        /// <summary>收集当前变体配置摘要，写入 manifest。</summary>
        public void CollectVariantConfigs(List<EvalVariantConfig> configs)
        {
            if (configs == null) return;
            configs.Clear();
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
            _hasLastGt = false;
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
        }

        // ── Unity 生命周期 ──

        private void OnEnable()
        {
            if (stereoSource != null) stereoSource.FrameCaptured += OnFrameCaptured;
        }

        private void OnDisable()
        {
            if (stereoSource != null) stereoSource.FrameCaptured -= OnFrameCaptured;
        }

        private void OnDestroy() => StopRecording();

        private void OnValidate()
        {
            if (variants == null) variants = new List<EvalVariant>();
        }

        // ── 采集事件：写 capture 行 ──

        private void OnFrameCaptured(long frameId, double captureMonoMs)
        {
            if (!_recording || _captureLog == null) return;

            FramePoseRecord fr = default;
            bool hasFrameRecord = framePoseHistory != null && framePoseHistory.TryGet(frameId, out fr);
            Pose cameraPose = Pose.identity;
            bool cameraValid = hasFrameRecord && fr.TryGetCameraPose(alignmentRef, out cameraPose);

            bool gtValid = groundTruth != null && IsGtTracked();
            Pose gtPose  = gtValid ? new Pose(groundTruth.position, groundTruth.rotation) : Pose.identity;
            Pose headPose = headAnchor != null ? new Pose(headAnchor.position, headAnchor.rotation) : Pose.identity;
            double unixMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

            _captureLog.Write(EvalJson.BuildCaptureLine(
                frameId, captureMonoMs, unixMs,
                hasFrameRecord ? fr.UnityFrame : UnityEngine.Time.frameCount,
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
            bool gtValid  = groundTruth != null && IsGtTracked();
            Pose gtPose   = gtValid ? new Pose(groundTruth.position, groundTruth.rotation) : Pose.identity;
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

            // 获取 RQ1 指标标记（如果有）
            string rq1Metric = "none";
            double rq1MetricDuration = 0.0;
            if (rq1Recorder != null && rq1Recorder.IsRecording)
            {
                rq1Metric = rq1Recorder.CurrentMetric.ToLogString();
                rq1MetricDuration = rq1Recorder.CurrentMetricDuration;
            }

            long sourceFrameId = BuildSnapshots();
            _outputLog.Write(EvalJson.BuildOutputLine(
                monoMs, unixMs, UnityEngine.Time.frameCount, sourceFrameId,
                headPose, gtValid, gtPose,
                gtLinear, gtAngular, _snapshots,
                rq1Metric, rq1MetricDuration));
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

                bool hasOut = ev.anchorTransform != null;
                Pose outPose = hasOut ? new Pose(ev.anchorTransform.position, ev.anchorTransform.rotation) : Pose.identity;
                string poseSource = hasOut ? "transform" : "none";

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
                    hasOut, outPose, poseSource,
                    hasTiming, hasTiming ? fr.SenderMonoMs : double.NaN,
                    hasTiming ? fr.UnityFrame : -1,
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
        /// 检查 GT 手柄当前是否被 OVR 有效跟踪。
        /// gtController == None 时恒返回 true（不过滤）。
        /// 手柄休眠、未配对或跟踪丢失时返回 false，评估端自动跳过这些帧。
        /// </summary>
        private bool IsGtTracked()
        {
            if (gtController == OVRInput.Controller.None) return true;
            return OVRInput.GetControllerPositionTracked(gtController)
                && OVRInput.GetControllerOrientationTracked(gtController);
        }
    }
}

using System;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using System.Text;
using EgoAnchor.Alignment;
using EgoAnchor.Policy;
using EgoAnchor.Quest;
using EgoAnchor.Runtime;
using UnityEngine;

namespace EgoAnchorEval
{
    /// <summary>
    /// 一个待记录的 pose-to-anchor runtime 变体。
    /// </summary>
    [Serializable]
    public struct RecordedRuntime
    {
        /// <summary>输出日志中的变体标签，例如 raw、lowpass、kalman 或 controller。</summary>
        [Tooltip("输出日志中的变体标签，例如 raw、lowpass、kalman 或 controller。")]
        public string label;

        /// <summary>该变体对应的 PoseToAnchorRuntime，用于记录 source frame、policy、reliability 与 aligned raw 诊断。</summary>
        [Tooltip("该变体对应的 PoseToAnchorRuntime，用于记录 source frame、policy、reliability 与 aligned raw 诊断；实际误差 pose 来自 anchorTransform。")]
        public PoseToAnchorRuntime runtime;

        /// <summary>该变体实际用于显示/评估的 Anchor Transform。</summary>
        [Tooltip("该变体实际用于显示/评估的 Anchor Transform。日志直接记录它的 world position/rotation；为空时该变体没有可评估 anchor pose。")]
        public Transform anchorTransform;

        /// <summary>主变体会额外记录 aligned raw pose 与 reliability score。</summary>
        [Tooltip("主变体会额外记录 aligned raw pose 与 reliability score，供离线回放和 latency 统计使用。")]
        public bool isPrimary;
    }

    /// <summary>
    /// EgoAnchor Unity 侧评估记录器：按 frame_id 记录采集瞬间 GT，按渲染 tick 记录各 runtime 输出。
    /// </summary>
    public sealed class AnchorEvalRecorder : MonoBehaviour
    {
        /// <summary>作为 GT 的场景 Transform，通常绑定 OVRControllerPrefab 根 Transform。</summary>
        [Header("Ground Truth")]
        [Tooltip("作为 GT 的场景 Transform，通常绑定 OVRControllerPrefab 根 Transform。日志直接记录它的 world position/rotation。")]
        [SerializeField] private Transform groundTruthTransform;

        /// <summary>头部中心参考 Transform，用于记录 render/capture 时的头部位姿并分析头动 slip/jitter。</summary>
        [Tooltip("头部中心参考 Transform，通常为 OVRCameraRig/CenterEyeAnchor。用于把 anchor 误差与快速头动、视角变化和 slip/jitter 关联起来。")]
        [SerializeField] private Transform headAnchor;

        /// <summary>与主 runtime 一致的 frame alignment 参考相机，用于记录 source frame 的相机位姿。</summary>
        [Header("Frame Alignment")]
        [Tooltip("与主 runtime 一致的 frame alignment 参考相机。当前 Python pose 语义默认是 Left；该字段用于写 capture camera pose 和 camera_reference。")]
        [SerializeField] private CameraReference alignmentReference = CameraReference.Left;

        /// <summary>Quest stereo 采集源，用于在 frame_id 诞生时记录 capture 行。</summary>
        [Tooltip("Quest stereo 采集源，用于在 frame_id 诞生时记录 capture 行。必须与运行时发送图像的 StereoFrameSource 是同一个实例。")]
        [SerializeField] private StereoFrameSource stereoSource;

        /// <summary>frame_id -> capture-time camera pose/timing 缓存，用于相机位姿和延迟统计。</summary>
        [Tooltip("frame_id -> capture-time camera pose/timing 缓存。用于记录 cam_pos、source_capture_mono_ms，并且必须与 StereoFrameSource/PoseToAnchorRuntime 共用同一个实例。")]
        [SerializeField] private FramePoseHistory framePoseHistory;

        /// <summary>需要记录的 runtime 变体列表。</summary>
        [Header("Runtime Variants")]
        [Tooltip("需要记录的 runtime 变体列表。主变体 isPrimary=true，用于额外记录 aligned raw 与 reliability。")]
        [SerializeField] private List<RecordedRuntime> recordedRuntimes = new List<RecordedRuntime>();

        /// <summary>每 frame_id 一行的采集日志 writer。</summary>
        private JsonlFileWriter captureWriter;

        /// <summary>每渲染 tick 一行的输出日志 writer。</summary>
        private JsonlFileWriter outputWriter;

        /// <summary>当前是否正在录制。</summary>
        private bool recording;

        /// <summary>复用的变体快照缓冲，避免 LateUpdate 高频分配列表。</summary>
        private readonly List<RecordedVariantSnapshot> variantSnapshots = new List<RecordedVariantSnapshot>();

        /// <summary>录制开始时缓存的 variant config hash，避免每渲染帧反射。</summary>
        private readonly Dictionary<string, string> variantConfigHashes = new Dictionary<string, string>();

        /// <summary>没有可用 GT pose。</summary>
        public const string SourceNone = "none";

        /// <summary>Transform pose 来源。</summary>
        public const string SourceTransform = "transform";

        /// <summary>写入 manifest 的 GT 来源标识。</summary>
        public string ManifestGtSource => groundTruthTransform != null ? SourceTransform : "transform_missing";

        /// <summary>写入 manifest 的 GT Transform 名称。</summary>
        public string ManifestGtTransform => groundTruthTransform != null ? groundTruthTransform.name : string.Empty;

        /// <summary>
        /// 开始写入评估日志。
        /// </summary>
        /// <param name="capturePath">unity_capture JSONL 路径。</param>
        /// <param name="outputPath">unity_output JSONL 路径。</param>
        public void BeginRecording(string capturePath, string outputPath)
        {
            StopRecording();
            captureWriter = new JsonlFileWriter(capturePath);
            outputWriter = new JsonlFileWriter(outputPath);
            RefreshVariantConfigHashCache();
            recording = true;
        }

        /// <summary>
        /// 停止录制并关闭文件句柄。
        /// </summary>
        public void StopRecording()
        {
            recording = false;
            captureWriter?.Dispose();
            outputWriter?.Dispose();
            captureWriter = null;
            outputWriter = null;
            variantSnapshots.Clear();
            variantConfigHashes.Clear();
        }

        /// <summary>
        /// Unity 启用组件时订阅采集事件。
        /// </summary>
        private void OnEnable()
        {
            if (stereoSource != null)
            {
                stereoSource.FrameCaptured += OnFrameCaptured;
            }
        }

        /// <summary>
        /// Unity 禁用组件时取消订阅采集事件。
        /// </summary>
        private void OnDisable()
        {
            if (stereoSource != null)
            {
                stereoSource.FrameCaptured -= OnFrameCaptured;
            }
        }

        /// <summary>
        /// Unity 销毁组件时确保文件被关闭。
        /// </summary>
        private void OnDestroy()
        {
            StopRecording();
        }

        /// <summary>
        /// Inspector 修改时保持列表非空。
        /// </summary>
        private void OnValidate()
        {
            if (recordedRuntimes == null)
            {
                recordedRuntimes = new List<RecordedRuntime>();
            }
        }

        /// <summary>
        /// 在 StereoFrameSource 同一 Unity 帧内采集 GT 与 camera pose。
        /// </summary>
        private void OnFrameCaptured(long frameId, double captureMonoMs)
        {
            if (!recording || captureWriter == null)
            {
                return;
            }

            PoseSample gtSample = ReadGroundTruthSample();
            bool hasFrameRecord = TryGetFrameRecord(frameId, out FramePoseRecord frameRecord);
            bool cameraValid = TryGetCameraPose(hasFrameRecord, frameRecord, out Pose cameraPose);
            Pose headPose = ResolveHeadPose();
            double unixMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            captureWriter.WriteLine(AnchorEvalJson.BuildCaptureLine(
                frameId,
                captureMonoMs,
                unixMs,
                headPose,
                cameraPose,
                gtSample.Pose,
                gtSample.HasPose,
                gtSample.PoseSource,
                cameraValid,
                hasFrameRecord ? frameRecord.UnityFrame : Time.frameCount,
                alignmentReference.ToString()));
        }

        /// <summary>
        /// 每个渲染 tick 记录各 runtime 变体输出。
        /// </summary>
        private void LateUpdate()
        {
            if (!recording || outputWriter == null)
            {
                return;
            }

            PoseSample gtSample = ReadGroundTruthSample();
            double monoMs = Time.realtimeSinceStartupAsDouble * 1000.0;
            double unixMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            Pose headPose = ResolveHeadPose();
            long sourceFrameId = BuildVariantSnapshots();
            outputWriter.WriteLine(AnchorEvalJson.BuildOutputLine(
                monoMs,
                unixMs,
                sourceFrameId,
                headPose,
                gtSample.Pose,
                gtSample.HasPose,
                gtSample.PoseSource,
                variantSnapshots,
                Time.frameCount));
        }

        /// <summary>
        /// 收集当前配置的 runtime 变体标签，用于写 session manifest。
        /// </summary>
        /// <param name="labels">接收标签的列表；调用前会被清空。</param>
        public void CollectVariantLabels(List<string> labels)
        {
            if (labels == null)
            {
                return;
            }

            labels.Clear();
            if (recordedRuntimes == null)
            {
                return;
            }

            for (int i = 0; i < recordedRuntimes.Count; i++)
            {
                string label = ResolveVariantLabel(recordedRuntimes[i], i);
                labels.Add(label);
            }
        }

        /// <summary>
        /// 收集当前配置的 runtime 变体模块组合和 Inspector 参数，用于写 session manifest。
        /// </summary>
        /// <param name="configs">接收配置快照的列表；调用前会被清空。</param>
        public void CollectVariantConfigs(List<EvalVariantConfig> configs)
        {
            if (configs == null)
            {
                return;
            }

            configs.Clear();
            if (recordedRuntimes == null)
            {
                return;
            }

            for (int i = 0; i < recordedRuntimes.Count; i++)
            {
                RecordedRuntime recorded = recordedRuntimes[i];
                string label = ResolveVariantLabel(recorded, i);
                configs.Add(BuildVariantConfig(recorded, label));
            }
        }

        /// <summary>
        /// 读取手柄 GT sample；Transform 缺失时返回无 pose。
        /// </summary>
        private PoseSample ReadGroundTruthSample()
        {
            if (groundTruthTransform != null)
            {
                return new PoseSample(true, ReadTransformPose(groundTruthTransform), SourceTransform);
            }

            return new PoseSample(false, Pose.identity, SourceNone);
        }

        /// <summary>
        /// 按 frame_id 从历史缓存取采集时刻记录。
        /// </summary>
        private bool TryGetFrameRecord(long frameId, out FramePoseRecord record)
        {
            record = default;
            return framePoseHistory != null && framePoseHistory.TryGet(frameId, out record);
        }

        /// <summary>
        /// 按 frame record 读取采集时刻参考相机 pose。
        /// </summary>
        private bool TryGetCameraPose(bool hasFrameRecord, FramePoseRecord record, out Pose cameraPose)
        {
            cameraPose = Pose.identity;
            if (!hasFrameRecord)
            {
                return false;
            }

            return record.TryGetCameraPose(alignmentReference, out cameraPose);
        }

        /// <summary>
        /// 读取当前头部 pose；未绑定时退化为 identity。
        /// </summary>
        private Pose ResolveHeadPose()
        {
            return headAnchor != null
                ? new Pose(headAnchor.position, headAnchor.rotation)
                : Pose.identity;
        }

        /// <summary>
        /// 从所有 runtime 变体采样当前输出，并返回主变体 source_frame_id。
        /// </summary>
        private long BuildVariantSnapshots()
        {
            variantSnapshots.Clear();
            long primaryFrameId = -1;
            bool hasPrimary = false;

            if (recordedRuntimes == null)
            {
                return primaryFrameId;
            }

            for (int i = 0; i < recordedRuntimes.Count; i++)
            {
                RecordedRuntime recorded = recordedRuntimes[i];
                PoseToAnchorRuntime runtime = recorded.runtime;
                string label = ResolveVariantLabel(recorded, i);
                Pose stablePose = Pose.identity;
                Pose rawPose = Pose.identity;
                Pose arrivalTimeRawPose = Pose.identity;
                string anchorPoseSource = SourceNone;
                bool hasStable = TryReadAnchorPose(recorded.anchorTransform, out stablePose, out anchorPoseSource);
                bool hasRaw = runtime != null && runtime.TryGetRawPose(out rawPose);
                bool hasArrivalTimeRaw = runtime != null && runtime.TryGetArrivalTimeRawPose(out arrivalTimeRawPose);
                long sourceFrameId = runtime != null ? runtime.LatestAlignedFrameId : -1;
                bool hasSourceTiming = TryGetFrameRecord(sourceFrameId, out FramePoseRecord sourceRecord);
                string state = runtime != null ? runtime.CurrentAnchorState.ToString() : "MissingRuntime";
                string action = runtime != null ? runtime.LatestPolicyAction : string.Empty;
                string reason = runtime != null ? runtime.LatestPolicyReason : string.Empty;
                string phase = runtime != null ? runtime.LatestPhase : string.Empty;
                string failure = runtime != null ? runtime.LatestFailure : "missing_runtime";
                float reliability = runtime != null ? runtime.LatestReliabilityScore : 0.0f;
                string motionState = runtime != null ? runtime.CurrentMotionStateName : string.Empty;
                double predictAheadMs = runtime != null ? runtime.LatestPredictAheadMs : double.NaN;
                string strategyLabel = runtime != null ? runtime.StrategyLabel : string.Empty;
                string gateModule = runtime != null ? runtime.GateModuleName : string.Empty;
                string estimatorModule = runtime != null ? runtime.EstimatorModuleName : string.Empty;
                string outputModule = runtime != null ? runtime.OutputModuleName : string.Empty;
                string configHash = ResolveCachedConfigHash(recorded, label);
                float residualMeters = runtime != null ? runtime.LatestResidualMeters : float.NaN;
                float residualDegrees = runtime != null ? runtime.LatestResidualDegrees : float.NaN;
                float acceptedScore = runtime != null ? runtime.LatestAcceptedScore : float.NaN;
                bool staticLocked = runtime != null && runtime.LatestStaticLocked;

                if (recorded.isPrimary && !hasPrimary)
                {
                    primaryFrameId = sourceFrameId;
                    hasPrimary = true;
                }

                variantSnapshots.Add(new RecordedVariantSnapshot(
                    label,
                    sourceFrameId,
                    hasStable,
                    stablePose,
                    state,
                    action,
                    reason,
                    phase,
                    failure,
                    anchorPoseSource,
                    hasSourceTiming,
                    hasSourceTiming ? sourceRecord.SenderMonoMs : double.NaN,
                    hasSourceTiming ? sourceRecord.UnityFrame : -1,
                    recorded.isPrimary,
                    hasRaw,
                    rawPose,
                    recorded.isPrimary && hasArrivalTimeRaw,
                    arrivalTimeRawPose,
                    runtime != null ? runtime.LatestArrivalTimeRawMonoMs : double.NaN,
                    runtime != null ? runtime.LatestArrivalTimeRawUnityFrame : -1,
                    runtime != null ? runtime.LatestArrivalTimeCameraReference.ToString() : string.Empty,
                    reliability,
                    motionState,
                    predictAheadMs,
                    strategyLabel,
                    gateModule,
                    estimatorModule,
                    outputModule,
                    configHash,
                    residualMeters,
                    residualDegrees,
                    acceptedScore,
                    staticLocked));
            }

            if (!hasPrimary && variantSnapshots.Count > 0)
            {
                primaryFrameId = variantSnapshots[0].SourceFrameId;
            }

            return primaryFrameId;
        }

        /// <summary>
        /// 读取实际 Anchor Transform；未绑定时该变体没有可评估 anchor pose。
        /// </summary>
        private static bool TryReadAnchorPose(Transform anchorTransform, out Pose pose, out string poseSource)
        {
            if (anchorTransform != null)
            {
                pose = ReadTransformPose(anchorTransform);
                poseSource = SourceTransform;
                return true;
            }

            pose = Pose.identity;
            poseSource = SourceNone;
            return false;
        }

        /// <summary>
        /// 解析 recorded runtime 的稳定 label。
        /// </summary>
        private static string ResolveVariantLabel(RecordedRuntime recorded, int index)
        {
            return string.IsNullOrEmpty(recorded.label) ? $"variant_{index}" : recorded.label;
        }

        /// <summary>
        /// 录制开始时缓存每个 variant 的配置摘要。
        /// </summary>
        private void RefreshVariantConfigHashCache()
        {
            variantConfigHashes.Clear();
            if (recordedRuntimes == null)
            {
                return;
            }

            for (int i = 0; i < recordedRuntimes.Count; i++)
            {
                string label = ResolveVariantLabel(recordedRuntimes[i], i);
                variantConfigHashes[label] = BuildVariantConfig(recordedRuntimes[i], label).ConfigHash;
            }
        }

        /// <summary>
        /// 从缓存取配置摘要，缺失时即时计算。
        /// </summary>
        private string ResolveCachedConfigHash(RecordedRuntime recorded, string label)
        {
            if (variantConfigHashes.TryGetValue(label, out string hash))
            {
                return hash;
            }

            hash = BuildVariantConfig(recorded, label).ConfigHash;
            variantConfigHashes[label] = hash;
            return hash;
        }

        /// <summary>
        /// 为一个 recorded runtime 生成模块组合和序列化字段快照。
        /// </summary>
        private static EvalVariantConfig BuildVariantConfig(RecordedRuntime recorded, string label)
        {
            PoseToAnchorRuntime runtime = recorded.runtime;
            AnchorPolicyHost policy = runtime != null ? runtime.PolicyHost : null;
            string strategyLabel = FirstNonEmpty(runtime != null ? runtime.StrategyLabel : string.Empty, label);
            string gateModule = FirstNonEmpty(policy != null ? policy.GateModuleName : string.Empty, runtime != null ? runtime.GateModuleName : string.Empty);
            string estimatorModule = FirstNonEmpty(policy != null ? policy.EstimatorModuleName : string.Empty, runtime != null ? runtime.EstimatorModuleName : string.Empty);
            string outputModule = FirstNonEmpty(policy != null ? policy.OutputModuleName : string.Empty, runtime != null ? runtime.OutputModuleName : string.Empty);
            SortedDictionary<string, string> parameters = new SortedDictionary<string, string>(StringComparer.Ordinal);

            if (policy != null)
            {
                CollectModuleParameters(parameters, "gate", policy.GateModule);
                CollectModuleParameters(parameters, "estimator", policy.EstimatorModule);
                CollectModuleParameters(parameters, "output", policy.OutputModule);
            }

            string configHash = ComputeConfigHash(label, strategyLabel, gateModule, estimatorModule, outputModule, parameters);
            return new EvalVariantConfig(label, strategyLabel, gateModule, estimatorModule, outputModule, configHash, parameters);
        }

        /// <summary>
        /// 收集一个 module 上所有 [SerializeField] 字段。
        /// </summary>
        private static void CollectModuleParameters(SortedDictionary<string, string> parameters, string prefix, MonoBehaviour module)
        {
            if (module == null)
            {
                return;
            }

            Type type = module.GetType();
            while (type != null && type != typeof(MonoBehaviour))
            {
                FieldInfo[] fields = type.GetFields(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
                foreach (FieldInfo field in fields)
                {
                    if (field.GetCustomAttribute(typeof(SerializeField)) == null)
                    {
                        continue;
                    }

                    parameters[$"{prefix}.{field.Name}"] = FormatParameterValue(field.GetValue(module));
                }

                type = type.BaseType;
            }
        }

        /// <summary>
        /// 把字段值转换为 invariant 明文。
        /// </summary>
        private static string FormatParameterValue(object value)
        {
            if (value == null)
            {
                return "";
            }

            switch (value)
            {
                case float f:
                    return f.ToString("R", CultureInfo.InvariantCulture);
                case double d:
                    return d.ToString("R", CultureInfo.InvariantCulture);
                case int i:
                    return i.ToString(CultureInfo.InvariantCulture);
                case long l:
                    return l.ToString(CultureInfo.InvariantCulture);
                case bool b:
                    return b ? "true" : "false";
                case string s:
                    return s;
                case Vector2 v2:
                    return FormatVector(v2.x, v2.y);
                case Vector3 v3:
                    return FormatVector(v3.x, v3.y, v3.z);
                case Vector4 v4:
                    return FormatVector(v4.x, v4.y, v4.z, v4.w);
                case Quaternion q:
                    return FormatVector(q.x, q.y, q.z, q.w);
                default:
                    return Convert.ToString(value, CultureInfo.InvariantCulture) ?? "";
            }
        }

        /// <summary>
        /// 按数组文本格式写入向量参数。
        /// </summary>
        private static string FormatVector(params float[] values)
        {
            StringBuilder builder = new StringBuilder();
            builder.Append('[');
            for (int i = 0; i < values.Length; i++)
            {
                if (i > 0)
                {
                    builder.Append(',');
                }

                builder.Append(values[i].ToString("R", CultureInfo.InvariantCulture));
            }
            builder.Append(']');
            return builder.ToString();
        }

        /// <summary>
        /// 计算稳定 FNV-1a 配置摘要。
        /// </summary>
        private static string ComputeConfigHash(
            string label,
            string strategyLabel,
            string gateModule,
            string estimatorModule,
            string outputModule,
            SortedDictionary<string, string> parameters)
        {
            StringBuilder builder = new StringBuilder();
            builder.Append(label).Append('|')
                .Append(strategyLabel).Append('|')
                .Append(gateModule).Append('|')
                .Append(estimatorModule).Append('|')
                .Append(outputModule);
            foreach (KeyValuePair<string, string> item in parameters)
            {
                builder.Append('|').Append(item.Key).Append('=').Append(item.Value);
            }

            unchecked
            {
                const ulong offset = 14695981039346656037UL;
                const ulong prime = 1099511628211UL;
                ulong hash = offset;
                byte[] bytes = Encoding.UTF8.GetBytes(builder.ToString());
                for (int i = 0; i < bytes.Length; i++)
                {
                    hash ^= bytes[i];
                    hash *= prime;
                }

                return hash.ToString("x16", CultureInfo.InvariantCulture);
            }
        }

        /// <summary>
        /// 返回第一段非空字符串。
        /// </summary>
        private static string FirstNonEmpty(params string[] values)
        {
            for (int i = 0; i < values.Length; i++)
            {
                if (!string.IsNullOrEmpty(values[i]))
                {
                    return values[i];
                }
            }

            return string.Empty;
        }

        /// <summary>
        /// 读取 Transform 的 Unity world pose。
        /// </summary>
        private static Pose ReadTransformPose(Transform source)
        {
            return new Pose(source.position, source.rotation);
        }

        /// <summary>
        /// 一次 Transform pose 采样结果。
        /// </summary>
        private readonly struct PoseSample
        {
            /// <summary>是否有可写入日志的 pose。</summary>
            public readonly bool HasPose;

            /// <summary>当前输出的 Unity world pose。</summary>
            public readonly Pose Pose;

            /// <summary>pose 来源，例如 transform 或 none。</summary>
            public readonly string PoseSource;

            /// <summary>构造 pose 采样结果。</summary>
            public PoseSample(bool hasPose, Pose pose, string poseSource)
            {
                HasPose = hasPose;
                Pose = pose;
                PoseSource = poseSource ?? SourceNone;
            }
        }
    }
}

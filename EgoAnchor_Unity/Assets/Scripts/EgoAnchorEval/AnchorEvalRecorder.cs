using System;
using System.Collections.Generic;
using EgoAnchor.Alignment;
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
                string label = string.IsNullOrEmpty(recordedRuntimes[i].label)
                    ? $"variant_{i}"
                    : recordedRuntimes[i].label;
                labels.Add(label);
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
                string label = string.IsNullOrEmpty(recorded.label) ? $"variant_{i}" : recorded.label;
                Pose stablePose = Pose.identity;
                Pose rawPose = Pose.identity;
                string anchorPoseSource = SourceNone;
                bool hasStable = TryReadAnchorPose(recorded.anchorTransform, out stablePose, out anchorPoseSource);
                bool hasRaw = runtime != null && runtime.TryGetRawPose(out rawPose);
                long sourceFrameId = runtime != null ? runtime.LatestAlignedFrameId : -1;
                bool hasSourceTiming = TryGetFrameRecord(sourceFrameId, out FramePoseRecord sourceRecord);
                string state = runtime != null ? runtime.CurrentAnchorState.ToString() : "MissingRuntime";
                string action = runtime != null ? runtime.LatestPolicyAction : string.Empty;
                string reason = runtime != null ? runtime.LatestPolicyReason : string.Empty;
                string phase = runtime != null ? runtime.LatestPhase : string.Empty;
                string failure = runtime != null ? runtime.LatestFailure : "missing_runtime";
                float reliability = runtime != null ? runtime.LatestReliabilityScore : 0.0f;

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
                    reliability));
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

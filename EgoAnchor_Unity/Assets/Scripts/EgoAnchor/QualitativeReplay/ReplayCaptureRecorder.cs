using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using EgoAnchor.Alignment;
using EgoAnchor.Client;
using EgoAnchor.Diagnostics;
using EgoAnchor.Eval;
using EgoAnchor.Protocol.Generated;
using EgoAnchor.Quest;
using EgoAnchor.Runtime;
using Google.Protobuf;
using UnityEngine;

namespace EgoAnchor.QualitativeReplay
{
    /// <summary>
    /// 专用定性 replay 采集器。
    /// 它复用 QuestStreamPublisher 已编码的左目 JPEG，并按 ImageUnityFrame 回查四种方法的
    /// LateUpdate 显示历史和左目 camera world pose，数据完全独立于正式 schema-v2。
    /// </summary>
    [DefaultExecutionOrder(100)]
    public sealed class ReplayCaptureRecorder : MonoBehaviour
    {
        /// <summary>统一日志通道。</summary>
        private static readonly EgoAnchorLog.Channel Log = EgoAnchorLog.For<ReplayCaptureRecorder>();

        /// <summary>Arrival-Hold 的稳定标识。</summary>
        public const string ArrivalHoldId = "arrival_hold";

        /// <summary>Capture-Hold 的稳定标识。</summary>
        public const string CaptureHoldId = "capture_hold";

        /// <summary>One-Euro Interpolation 的稳定标识。</summary>
        public const string OneEuroId = "one_euro_interpolation";

        /// <summary>EgoAnchor 的稳定标识。</summary>
        public const string EgoAnchorId = "egoanchor";

        /// <summary>Arrival-Hold 论文颜色。</summary>
        public const string ArrivalHoldColor = "#0072B2";

        /// <summary>Capture-Hold 论文颜色。</summary>
        public const string CaptureHoldColor = "#009E73";

        /// <summary>One-Euro Interpolation 论文颜色。</summary>
        public const string OneEuroColor = "#E69F00";

        /// <summary>EgoAnchor 论文颜色。</summary>
        public const string EgoAnchorColor = "#D55E00";

        /// <summary>提供 exact JPEG 和采集双时间的现有发布器。</summary>
        [Header("Existing Capture Chain")]
        [Tooltip("现有 QuestStreamPublisher；replay 只订阅其已编码左目 JPEG，不再次 GPU 读回。")]
        [SerializeField] private QuestStreamPublisher streamPublisher;

        /// <summary>读取左目标定的现有来源。</summary>
        [Tooltip("现有 CameraInfoSource；每个保存样本读取一次轻量标定快照。")]
        [SerializeField] private CameraInfoSource cameraInfoSource;

        /// <summary>frame_id 到 image-time 左目 world pose 的现有缓存。</summary>
        [Tooltip("与 StereoFrameSource 和四个 runtime 共用的 FramePoseHistory。")]
        [SerializeField] private FramePoseHistory framePoseHistory;

        /// <summary>Quest 官方右手柄参考 Transform。</summary>
        [Header("Platform Reference")]
        [Tooltip("必须绑定 OVRCameraRig/OVRInteractionComprehensive/OVRControllerVisualRight/OVRControllerPrefab。")]
        [SerializeField] private Transform platformReference;

        /// <summary>用于判断官方右手柄参考是否正在被平台追踪。</summary>
        [Tooltip("controller_right 固定使用 RTouch；pose 始终只从 platformReference Transform 读取。")]
        [SerializeField] private OVRInput.Controller platformReferenceController = OVRInput.Controller.RTouch;

        /// <summary>Arrival-Hold runtime。</summary>
        [Header("Experiment 1 Variants")]
        [Tooltip("Arrival-Hold 的 PoseToAnchorRuntime。")]
        [SerializeField] private PoseToAnchorRuntime arrivalHoldRuntime;

        /// <summary>Arrival-Hold 显示器。</summary>
        [Tooltip("Arrival-Hold 的 DynamicObjectAnchor；用于记录 hold-last 后的实际显示 pose。")]
        [SerializeField] private DynamicObjectAnchor arrivalHoldPresenter;

        /// <summary>Capture-Hold runtime。</summary>
        [Tooltip("Capture-Hold 的 PoseToAnchorRuntime。")]
        [SerializeField] private PoseToAnchorRuntime captureHoldRuntime;

        /// <summary>Capture-Hold 显示器。</summary>
        [Tooltip("Capture-Hold 的 DynamicObjectAnchor。")]
        [SerializeField] private DynamicObjectAnchor captureHoldPresenter;

        /// <summary>One-Euro Interpolation runtime。</summary>
        [Tooltip("One-Euro Interpolation 的 PoseToAnchorRuntime。")]
        [SerializeField] private PoseToAnchorRuntime oneEuroRuntime;

        /// <summary>One-Euro Interpolation 显示器。</summary>
        [Tooltip("One-Euro Interpolation 的 DynamicObjectAnchor。")]
        [SerializeField] private DynamicObjectAnchor oneEuroPresenter;

        /// <summary>EgoAnchor runtime。</summary>
        [Tooltip("完整 EgoAnchor 的 PoseToAnchorRuntime。")]
        [SerializeField] private PoseToAnchorRuntime egoAnchorRuntime;

        /// <summary>EgoAnchor 显示器。</summary>
        [Tooltip("完整 EgoAnchor 的 DynamicObjectAnchor。")]
        [SerializeField] private DynamicObjectAnchor egoAnchorPresenter;

        /// <summary>目标对象配置名。</summary>
        [Header("Replay Output")]
        [Tooltip("Python defaults.toml 中的对象配置名，例如 controller_right。")]
        [SerializeField] private string objectId = "controller_right";

        /// <summary>Python 目标 mesh 路径，仅作为 capture provenance。</summary>
        [Tooltip("相对 EgoAnchor_Python 的目标 mesh 路径。")]
        [SerializeField] private string modelMeshPath = "data/model/MetaQuestTouchPlus_Right.glb";

        /// <summary>Python 加载 mesh 后应用的尺度。</summary>
        [Tooltip("与 defaults.toml 对象配置一致的 mesh apply_scale。")]
        [Min(0.000001f)]
        [SerializeField] private float modelApplyScale = 1f;

        /// <summary>输出根目录覆盖；空值写入仓库本机 Python 数据目录。</summary>
        [Tooltip("留空时写 <repo>/EgoAnchor_Python/data/replay_capture；相对路径基于 EgoAnchor_Unity 项目根目录。")]
        [SerializeField] private string outputRoot = string.Empty;

        /// <summary>保存帧率；0 表示保存发布器产生的每一帧。</summary>
        [Tooltip("Link 定性采集固定使用 0，保存 QuestStreamPublisher 产生的全部左目 JPEG。")]
        [Min(0f)]
        [SerializeField] private float captureFps;

        /// <summary>后台 JPEG 队列容量。</summary>
        [Tooltip("后台 writer 最大排队样本数；队列满时整条 drop-newest，绝不阻塞追踪。")]
        [Min(1)]
        [SerializeField] private int writerQueueCapacity = 32;

        /// <summary>渲染帧 pose 历史容量。</summary>
        [Tooltip("按 Unity frame 保存四路 LateUpdate pose 的容量；必须覆盖 cameraPoseDelayFrames 对应延迟。")]
        [Min(32)]
        [SerializeField] private int poseHistoryCapacityFrames = 512;

        /// <summary>进入场景后是否自动开始。</summary>
        [Tooltip("专用 replay 场景默认自动开始；停止应用或禁用组件时自动排空并发布。")]
        [SerializeField] private bool autoStart = true;

        /// <summary>按 Unity frame 索引的四路 pose 历史。</summary>
        private readonly Dictionary<int, ReplayPoseFrame> poseHistory = new Dictionary<int, ReplayPoseFrame>();

        /// <summary>pose 历史写入顺序。</summary>
        private readonly Queue<int> poseHistoryOrder = new Queue<int>();

        /// <summary>等待 LateUpdate 配对的 JPEG 回调。</summary>
        private readonly Queue<PendingCapture> pendingCaptures = new Queue<PendingCapture>();

        /// <summary>当前后台 writer。</summary>
        private ReplayCaptureWriter writer;

        /// <summary>当前 capture 清单。</summary>
        private ReplayManifestDto manifest;

        /// <summary>当前 .inprogress 目录。</summary>
        private string inProgressDirectory = string.Empty;

        /// <summary>当前最终目录。</summary>
        private string finalDirectory = string.Empty;

        /// <summary>上次已接受样本的 image-time 毫秒。</summary>
        private double lastAcceptedImageMonoMs = double.NegativeInfinity;

        /// <summary>上次已接受样本的 image-time Unity frame。</summary>
        private int lastAcceptedImageUnityFrame = -1;

        /// <summary>本 capture 内样本序号。</summary>
        private int nextSampleSequence;

        /// <summary>本 capture 开始的 Unity frame；更早的延迟图像只预热，不计缺失。</summary>
        private int captureStartUnityFrame;

        /// <summary>开始录制时冻结的四路完整运行时配置指纹。</summary>
        private string[] runtimeFingerprints = Array.Empty<string>();

        /// <summary>低频刷新的左目标定快照，避免每个 JPEG 回调分配 protobuf。</summary>
        private QuestCameraInfo cachedCameraInfo;

        /// <summary>下一次允许刷新标定的 Unity 单调时钟毫秒。</summary>
        private double nextCameraInfoRefreshMonoMs;

        /// <summary>复用正式评估语义的平台参考保持器。</summary>
        private readonly EvalReferencePoseTracker referenceTracker = new EvalReferencePoseTracker();

        /// <summary>开始录制时冻结的平台参考 Transform 路径。</summary>
        private string platformReferencePath = string.Empty;

        /// <summary>是否正在接收新样本。</summary>
        public bool IsCapturing => writer != null;

        /// <summary>最近一次开始的最终目录；失败时对应 .inprogress 目录仍保留。</summary>
        public string CaptureDirectory => finalDirectory;

        /// <summary>组件启用时订阅 exact frame 事件并按配置自动开始。</summary>
        private void OnEnable()
        {
            if (streamPublisher != null)
            {
                streamPublisher.StereoFrameCaptured += OnStereoFrameCaptured;
            }
            if (autoStart)
            {
                StartCapture();
            }
        }

        /// <summary>组件禁用时先停止采集，再解除事件订阅。</summary>
        private void OnDisable()
        {
            StopCapture();
            if (streamPublisher != null)
            {
                streamPublisher.StereoFrameCaptured -= OnStereoFrameCaptured;
            }
        }

        /// <summary>应用退出前尽力排空后台队列。</summary>
        private void OnApplicationQuit()
        {
            StopCapture();
        }

        /// <summary>
        /// 在四个 DynamicObjectAnchor（execution order 0）之后锁存本渲染帧，
        /// 再把 Update 阶段到达的 JPEG 与其 ImageUnityFrame 历史配对。
        /// </summary>
        private void LateUpdate()
        {
            if (writer == null)
            {
                return;
            }
            CapturePoseHistoryFrame();
            ProcessPendingCaptures();
        }

        /// <summary>开始一个新的独立 replay capture。</summary>
        public void StartCapture()
        {
            if (writer != null)
            {
                return;
            }
            if (!Application.isEditor)
            {
                Log.Error("qualitative replay is Link-only and must run in Unity Editor Play Mode", this);
                return;
            }
            if (!ValidateBindings(out string error))
            {
                Log.Error($"qualitative replay start rejected: {error}", this);
                return;
            }

            string root = ResolveOutputRoot();
            string captureId = BuildCaptureId(objectId);
            inProgressDirectory = Path.Combine(root, captureId + ".inprogress");
            finalDirectory = Path.Combine(root, captureId);
            Directory.CreateDirectory(root);
            Directory.CreateDirectory(inProgressDirectory);

            manifest = BuildManifest(captureId);
            WriteManifest(inProgressDirectory, manifest);
            runtimeFingerprints = new[]
            {
                BuildRuntimeFingerprint(arrivalHoldRuntime),
                BuildRuntimeFingerprint(captureHoldRuntime),
                BuildRuntimeFingerprint(oneEuroRuntime),
                BuildRuntimeFingerprint(egoAnchorRuntime),
            };
            platformReferencePath = BuildTransformPath(platformReference);
            referenceTracker.Reset();
            writer = new ReplayCaptureWriter(inProgressDirectory, writerQueueCapacity);
            poseHistory.Clear();
            poseHistoryOrder.Clear();
            pendingCaptures.Clear();
            captureStartUnityFrame = Time.frameCount;
            cachedCameraInfo = null;
            nextCameraInfoRefreshMonoMs = double.NegativeInfinity;
            lastAcceptedImageMonoMs = double.NegativeInfinity;
            lastAcceptedImageUnityFrame = -1;
            nextSampleSequence = 0;
            Log.Info($"qualitative replay capture started: {inProgressDirectory}", this);
        }

        /// <summary>停止、排空并在无写入失败时把 .inprogress 原子改名为最终目录。</summary>
        public void StopCapture()
        {
            ReplayCaptureWriter currentWriter = writer;
            if (currentWriter == null)
            {
                return;
            }

            writer = null;
            pendingCaptures.Clear();
            try
            {
                currentWriter.Dispose();
                ReplayWriterStats stats = currentWriter.Stats;
                manifest.samples_written = stats.SamplesWritten;
                manifest.queue_dropped = stats.QueueDropped;
                manifest.write_failures = stats.WriteFailures;
                manifest.peak_queue_depth = stats.PeakQueueDepth;
                manifest.image_bytes_written = stats.ImageBytesWritten;
                manifest.writer_error = stats.Error;
                manifest.stopped_unix_ms = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                manifest.complete = stats.WriteFailures == 0;
                WriteManifest(inProgressDirectory, manifest);

                if (manifest.complete)
                {
                    Directory.Move(inProgressDirectory, finalDirectory);
                    Log.Info(
                        $"qualitative replay capture published: {finalDirectory}, "
                        + $"written={stats.SamplesWritten}, dropped={stats.QueueDropped}",
                        this);
                }
                else
                {
                    Log.Error(
                        $"qualitative replay capture kept incomplete: {inProgressDirectory}, error={stats.Error}",
                        this);
                }
            }
            catch (Exception exc)
            {
                Log.Error(
                    $"qualitative replay finalization failed; .inprogress data was retained: {exc}",
                    this);
            }
        }

        /// <summary>
        /// Update 阶段只做采样率筛选并缓存不可变 ByteString；不读取 runtime pose，也不做文件 I/O。
        /// </summary>
        private void OnStereoFrameCaptured(
            EncodedLeftFrame frame,
            FrameCaptureTiming timing,
            double publishAttemptMonoMs,
            bool publishSucceeded)
        {
            if (writer == null || frame.ImageJpeg == null || frame.ImageJpeg.Length == 0)
            {
                return;
            }
            if (timing.ImageUnityFrame < captureStartUnityFrame)
            {
                return;
            }
            if (timing.ImageUnityFrame <= lastAcceptedImageUnityFrame
                || timing.ImageMonoMs <= lastAcceptedImageMonoMs)
            {
                return;
            }
            double intervalMs = captureFps > 0f ? 1000.0 / captureFps : 0.0;
            if (intervalMs > 0.0 && timing.ImageMonoMs - lastAcceptedImageMonoMs + 1e-6 < intervalMs)
            {
                return;
            }

            double nowMonoMs = Time.realtimeSinceStartupAsDouble * 1000.0;
            if (!TryGetCameraInfo(nowMonoMs, out QuestCameraInfo cameraInfo))
            {
                manifest.calibration_missing++;
                return;
            }

            lastAcceptedImageMonoMs = timing.ImageMonoMs;
            lastAcceptedImageUnityFrame = timing.ImageUnityFrame;
            manifest.capture_attempts++;
            pendingCaptures.Enqueue(new PendingCapture(
                frame.FrameId,
                frame.ImageJpeg,
                frame.Width,
                frame.Height,
                frame.JpegQuality,
                timing,
                publishAttemptMonoMs,
                publishSucceeded,
                cameraInfo));
        }

        /// <summary>记录当前渲染帧四种方法的 output/display 双层状态。</summary>
        private void CapturePoseHistoryFrame()
        {
            int unityFrame = Time.frameCount;
            double nowMonoMs = Time.realtimeSinceStartupAsDouble * 1000.0;
            ReplayPoseFrame frame = new ReplayPoseFrame(
                unityFrame,
                nowMonoMs,
                ResolvePlatformReference(nowMonoMs),
                new[]
                {
                    CaptureVariantState(
                        ArrivalHoldId,
                        ArrivalHoldColor,
                        arrivalHoldRuntime,
                        arrivalHoldPresenter,
                        runtimeFingerprints[0]),
                    CaptureVariantState(
                        CaptureHoldId,
                        CaptureHoldColor,
                        captureHoldRuntime,
                        captureHoldPresenter,
                        runtimeFingerprints[1]),
                    CaptureVariantState(
                        OneEuroId,
                        OneEuroColor,
                        oneEuroRuntime,
                        oneEuroPresenter,
                        runtimeFingerprints[2]),
                    CaptureVariantState(
                        EgoAnchorId,
                        EgoAnchorColor,
                        egoAnchorRuntime,
                        egoAnchorPresenter,
                        runtimeFingerprints[3]),
                });

            if (!poseHistory.ContainsKey(unityFrame))
            {
                poseHistoryOrder.Enqueue(unityFrame);
            }
            poseHistory[unityFrame] = frame;
            while (poseHistory.Count > Mathf.Max(32, poseHistoryCapacityFrames) && poseHistoryOrder.Count > 0)
            {
                poseHistory.Remove(poseHistoryOrder.Dequeue());
            }
        }

        /// <summary>按正式评估语义读取 Quest 官方右手柄参考，并在失活时保持最后新鲜 pose。</summary>
        private EvalReferencePose ResolvePlatformReference(double nowMonoMs)
        {
            bool hasTransform = platformReference != null;
            Pose currentPose = hasTransform
                ? new Pose(platformReference.position, platformReference.rotation)
                : Pose.identity;
            bool active = hasTransform
                && platformReference.gameObject.activeInHierarchy
                && OVRInput.GetControllerPositionTracked(platformReferenceController)
                && OVRInput.GetControllerOrientationTracked(platformReferenceController);
            return referenceTracker.Resolve(hasTransform, currentPose, active, nowMonoMs);
        }

        /// <summary>读取一个 runtime 已应用后的显示状态。</summary>
        private static ReplayVariantState CaptureVariantState(
            string variantId,
            string colorHex,
            PoseToAnchorRuntime runtime,
            DynamicObjectAnchor presenter,
            string runtimeFingerprint)
        {
            Pose outputPose = Pose.identity;
            bool hasOutput = runtime != null && runtime.TryGetOutputPose(out outputPose);
            Pose displayPose = Pose.identity;
            bool hasDisplay = presenter != null && presenter.TryGetDisplayPose(out displayPose);
            string source = hasDisplay ? (hasOutput ? "transform" : "hold_last") : "none";
            long sourceFrameId = hasDisplay && presenter != null ? presenter.LastAppliedFrameId : -1;
            return new ReplayVariantState(
                variantId,
                colorHex,
                hasOutput,
                outputPose,
                hasDisplay,
                displayPose,
                source,
                sourceFrameId,
                runtimeFingerprint);
        }

        /// <summary>最多每秒刷新一次相机标定；刷新失败时继续使用最近成功快照。</summary>
        private bool TryGetCameraInfo(double nowMonoMs, out QuestCameraInfo cameraInfo)
        {
            if (cachedCameraInfo == null || nowMonoMs >= nextCameraInfoRefreshMonoMs)
            {
                if (cameraInfoSource != null && cameraInfoSource.TryCapture(out QuestCameraInfo freshInfo))
                {
                    cachedCameraInfo = freshInfo;
                }
                nextCameraInfoRefreshMonoMs = nowMonoMs + 1000.0;
            }
            cameraInfo = cachedCameraInfo;
            return cameraInfo != null;
        }

        /// <summary>把所有待处理 JPEG 与其 image-time pose/camera 历史配对并非阻塞入队。</summary>
        private void ProcessPendingCaptures()
        {
            while (writer != null && pendingCaptures.Count > 0)
            {
                PendingCapture pending = pendingCaptures.Dequeue();
                if (!poseHistory.TryGetValue(pending.Timing.ImageUnityFrame, out ReplayPoseFrame poseFrame))
                {
                    manifest.pose_history_missing++;
                    continue;
                }
                if (framePoseHistory == null
                    || !framePoseHistory.TryGet(pending.FrameId, out FramePoseRecord cameraRecord)
                    || !cameraRecord.TryGetCameraPose(CameraReference.Left, out Pose cameraWorldPose))
                {
                    manifest.camera_pose_missing++;
                    continue;
                }

                int sequence = nextSampleSequence + 1;
                string sampleId = sequence.ToString("D9", CultureInfo.InvariantCulture);
                string imagePath = $"images/{sampleId}.jpg";
                ReplaySampleDto sample = BuildSample(
                    sampleId,
                    imagePath,
                    pending,
                    poseFrame,
                    cameraWorldPose,
                    platformReferencePath,
                    platformReferenceController.ToString());
                string sampleJson = JsonUtility.ToJson(sample, prettyPrint: false);
                if (writer.TryEnqueue(new ReplayWriteItem(pending.LeftImageJpeg, imagePath, sampleJson)))
                {
                    nextSampleSequence = sequence;
                    manifest.samples_enqueued++;
                    if (!poseFrame.PlatformReference.Valid)
                    {
                        manifest.reference_invalid_samples++;
                    }
                    else if (poseFrame.PlatformReference.KeepAlive)
                    {
                        manifest.reference_held_samples++;
                    }
                }
            }
        }

        /// <summary>构造一条完整 replay 样本。</summary>
        private static ReplaySampleDto BuildSample(
            string sampleId,
            string imagePath,
            PendingCapture pending,
            ReplayPoseFrame poseFrame,
            Pose cameraWorldPose,
            string referencePath,
            string referenceController)
        {
            ReplayVariantPoseDto[] variants = new ReplayVariantPoseDto[poseFrame.Variants.Length];
            for (int i = 0; i < poseFrame.Variants.Length; i++)
            {
                ReplayVariantState state = poseFrame.Variants[i];
                variants[i] = new ReplayVariantPoseDto
                {
                    variant_id = state.VariantId,
                    color_hex = state.ColorHex,
                    has_output_pose = state.HasOutputPose,
                    output_world_pose = ReplayPoseDto.FromPose(state.OutputWorldPose),
                    has_display_pose = state.HasDisplayPose,
                    display_world_pose = ReplayPoseDto.FromPose(state.DisplayWorldPose),
                    pose_source = state.PoseSource,
                    source_frame_id = state.SourceFrameId,
                    projection_pose_cv_camera = state.HasDisplayPose
                        ? ReplayCaptureGeometry.ToOpenCvObjectMatrix(cameraWorldPose, state.DisplayWorldPose)
                        : new float[16],
                    runtime_configuration_fingerprint = state.RuntimeConfigurationFingerprint,
                };
            }

            return new ReplaySampleDto
            {
                sample_id = sampleId,
                background_frame_id = pending.FrameId,
                image_path = imagePath,
                image_bytes = pending.LeftImageJpeg.Length,
                image_width = pending.Width,
                image_height = pending.Height,
                jpeg_quality = pending.JpegQuality,
                image_mono_ms = pending.Timing.ImageMonoMs,
                image_unity_frame = pending.Timing.ImageUnityFrame,
                image_time_offset_frames = pending.Timing.ImageTimeOffsetFrames,
                sender_mono_ms = pending.Timing.SenderMonoMs,
                sender_unity_frame = pending.Timing.SenderUnityFrame,
                publish_attempt_mono_ms = pending.PublishAttemptMonoMs,
                publish_succeeded = pending.PublishSucceeded,
                render_tick_id = poseFrame.UnityFrame,
                snapshot_mono_ms = poseFrame.MonoMs,
                camera = BuildCameraDto(pending.CameraInfo, pending.Width, pending.Height, cameraWorldPose),
                platform_reference = BuildReferenceDto(
                    poseFrame.PlatformReference,
                    cameraWorldPose,
                    referencePath,
                    referenceController),
                variants = variants,
            };
        }

        /// <summary>把同帧平台参考状态转换为可校验的离线 DTO。</summary>
        private static ReplayReferenceDto BuildReferenceDto(
            EvalReferencePose reference,
            Pose cameraWorldPose,
            string transformPath,
            string controller)
        {
            return new ReplayReferenceDto
            {
                valid = reference.Valid,
                fresh = reference.Fresh,
                keep_alive = reference.KeepAlive,
                fresh_age_ms = double.IsNaN(reference.FreshAgeMs) ? -1.0 : reference.FreshAgeMs,
                world_pose = ReplayPoseDto.FromPose(reference.Pose),
                projection_pose_cv_camera = reference.Valid
                    ? ReplayCaptureGeometry.ToOpenCvObjectMatrix(cameraWorldPose, reference.Pose)
                    : new float[16],
                transform_path = transformPath ?? string.Empty,
                controller = controller ?? string.Empty,
                pose_source = reference.Fresh ? "transform" : reference.KeepAlive ? "held" : "none",
            };
        }

        /// <summary>按现有 QuestStereoCalibration 的中心裁剪规则生成保存分辨率 K。</summary>
        private static ReplayCameraDto BuildCameraDto(
            QuestCameraInfo info,
            int targetWidth,
            int targetHeight,
            Pose cameraWorldPose)
        {
            int calibrationWidth = info.ActiveRight - info.ActiveLeft;
            int calibrationHeight = info.ActiveBottom - info.ActiveTop;
            if (calibrationWidth <= 0 || calibrationHeight <= 0)
            {
                calibrationWidth = info.SensorWidth > 0 ? info.SensorWidth
                    : info.CurrentWidth > 0 ? info.CurrentWidth : info.LeftRequestedWidth;
                calibrationHeight = info.SensorHeight > 0 ? info.SensorHeight
                    : info.CurrentHeight > 0 ? info.CurrentHeight : info.LeftRequestedHeight;
            }

            ComputeScaledIntrinsics(
                info.LeftFx,
                info.LeftFy,
                info.LeftCx,
                info.LeftCy,
                calibrationWidth,
                calibrationHeight,
                targetWidth,
                targetHeight,
                out double fx,
                out double fy,
                out double cx,
                out double cy);
            return new ReplayCameraDto
            {
                reference = "Left",
                world_pose = ReplayPoseDto.FromPose(cameraWorldPose),
                fx = fx,
                fy = fy,
                cx = cx,
                cy = cy,
                calibration_width = calibrationWidth,
                calibration_height = calibrationHeight,
                sensor_width = info.SensorWidth,
                sensor_height = info.SensorHeight,
                active_left = info.ActiveLeft,
                active_top = info.ActiveTop,
                active_right = info.ActiveRight,
                active_bottom = info.ActiveBottom,
                current_width = info.CurrentWidth,
                current_height = info.CurrentHeight,
                requested_width = info.LeftRequestedWidth,
                requested_height = info.LeftRequestedHeight,
                distortion_model = "unknown",
            };
        }

        /// <summary>复现 Python QuestStereoCalibration.scaled_k 的中心裁剪与缩放。</summary>
        public static void ComputeScaledIntrinsics(
            double sourceFx,
            double sourceFy,
            double sourceCx,
            double sourceCy,
            int calibrationWidth,
            int calibrationHeight,
            int targetWidth,
            int targetHeight,
            out double fx,
            out double fy,
            out double cx,
            out double cy)
        {
            double sourceWidth = Math.Max(calibrationWidth, 1);
            double sourceHeight = Math.Max(calibrationHeight, 1);
            double outputWidth = Math.Max(targetWidth, 1);
            double outputHeight = Math.Max(targetHeight, 1);
            double sourceAspect = sourceWidth / sourceHeight;
            double outputAspect = outputWidth / outputHeight;
            double cropX = 0.0;
            double cropY = 0.0;
            double cropWidth = sourceWidth;
            double cropHeight = sourceHeight;
            if (Math.Abs(sourceAspect - outputAspect) > 1e-6)
            {
                if (sourceAspect > outputAspect)
                {
                    cropWidth = sourceHeight * outputAspect;
                    cropX = (sourceWidth - cropWidth) * 0.5;
                }
                else
                {
                    cropHeight = sourceWidth / outputAspect;
                    cropY = (sourceHeight - cropHeight) * 0.5;
                }
            }

            double scaleX = outputWidth / Math.Max(cropWidth, 1e-6);
            double scaleY = outputHeight / Math.Max(cropHeight, 1e-6);
            fx = sourceFx * scaleX;
            fy = sourceFy * scaleY;
            cx = (sourceCx - cropX) * scaleX;
            cy = (sourceCy - cropY) * scaleY;
        }

        /// <summary>验证专用场景必需引用和四路唯一性。</summary>
        private bool ValidateBindings(out string error)
        {
            if (!string.Equals(
                    gameObject.scene.name,
                    "EgoAnchor-ReplayCapture",
                    StringComparison.Ordinal))
            {
                error = "qualitative replay must run in the dedicated EgoAnchor-ReplayCapture scene";
                return false;
            }
            if (streamPublisher == null || cameraInfoSource == null || framePoseHistory == null)
            {
                error = "streamPublisher, cameraInfoSource and framePoseHistory are required";
                return false;
            }
            string referencePath = BuildTransformPath(platformReference);
            const string ExpectedReferencePath =
                "OVRCameraRig/OVRInteractionComprehensive/OVRControllerVisualRight/OVRControllerPrefab";
            OVRControllerHelper referenceHelper = platformReference != null
                ? platformReference.GetComponent<OVRControllerHelper>()
                : null;
            if (platformReference == null
                || !string.Equals(referencePath, ExpectedReferencePath, StringComparison.Ordinal)
                || platformReferenceController != OVRInput.Controller.RTouch
                || referenceHelper == null
                || referenceHelper.m_controller != OVRInput.Controller.RTouch)
            {
                error = $"platform reference must be RTouch at {ExpectedReferencePath}";
                return false;
            }
            if (Mathf.Abs(captureFps) > 1e-6f)
            {
                error = "Quest Link qualitative replay requires captureFps=0 to save every encoded frame";
                return false;
            }
            PoseToAnchorRuntime[] runtimes =
            {
                arrivalHoldRuntime,
                captureHoldRuntime,
                oneEuroRuntime,
                egoAnchorRuntime,
            };
            DynamicObjectAnchor[] presenters =
            {
                arrivalHoldPresenter,
                captureHoldPresenter,
                oneEuroPresenter,
                egoAnchorPresenter,
            };
            HashSet<PoseToAnchorRuntime> unique = new HashSet<PoseToAnchorRuntime>();
            HashSet<DynamicObjectAnchor> uniquePresenters = new HashSet<DynamicObjectAnchor>();
            for (int i = 0; i < runtimes.Length; i++)
            {
                if (runtimes[i] == null
                    || presenters[i] == null
                    || !unique.Add(runtimes[i])
                    || !uniquePresenters.Add(presenters[i]))
                {
                    error = $"variant binding {i} is missing or duplicated";
                    return false;
                }
                if (presenters[i].GetComponent<PoseToAnchorRuntime>() != runtimes[i])
                {
                    error = $"variant binding {i} presenter does not read the paired runtime";
                    return false;
                }
            }
            if (!ValidateVariantConfiguration(
                    arrivalHoldRuntime,
                    usesCaptureTime: false,
                    motionModel: "cv",
                    smoothingStrategy: "hold",
                    usesVcd: false,
                    usesTemporal: false,
                    usesStaticLock: false,
                    out error)
                || !ValidateVariantConfiguration(
                    captureHoldRuntime,
                    usesCaptureTime: true,
                    motionModel: "cv",
                    smoothingStrategy: "hold",
                    usesVcd: false,
                    usesTemporal: false,
                    usesStaticLock: false,
                    out error)
                || !ValidateVariantConfiguration(
                    oneEuroRuntime,
                    usesCaptureTime: true,
                    motionModel: "oneeuro",
                    smoothingStrategy: "linear_slerp",
                    usesVcd: true,
                    usesTemporal: true,
                    usesStaticLock: false,
                    out error)
                || !ValidateVariantConfiguration(
                    egoAnchorRuntime,
                    usesCaptureTime: true,
                    motionModel: "kalman",
                    smoothingStrategy: "linear_slerp",
                    usesVcd: true,
                    usesTemporal: true,
                    usesStaticLock: true,
                    out error))
            {
                return false;
            }
            error = string.Empty;
            return true;
        }

        /// <summary>冻结四种实验一方法的关键模块组合，防止 Inspector 误绑后错误标注。</summary>
        private static bool ValidateVariantConfiguration(
            PoseToAnchorRuntime runtime,
            bool usesCaptureTime,
            string motionModel,
            string smoothingStrategy,
            bool usesVcd,
            bool usesTemporal,
            bool usesStaticLock,
            out string error)
        {
            var policy = runtime != null ? runtime.PolicyHost : null;
            bool matches = runtime != null
                && policy != null
                && runtime.UsesCaptureTimeAlignment == usesCaptureTime
                && runtime.MotionModelName == motionModel
                && runtime.SmoothingStrategyName == smoothingStrategy
                && policy.UsesVcdAdmission == usesVcd
                && policy.UsesTemporalSynthesis == usesTemporal
                && policy.UsesStaticLock == usesStaticLock;
            if (!matches)
            {
                error = $"runtime configuration does not match {motionModel}/{smoothingStrategy}";
                return false;
            }
            error = string.Empty;
            return true;
        }

        /// <summary>组合 alignment、模型、策略、接纳、生命周期和 StaticLock 的完整指纹。</summary>
        private static string BuildRuntimeFingerprint(PoseToAnchorRuntime runtime)
        {
            var policy = runtime != null ? runtime.PolicyHost : null;
            if (runtime == null || policy == null)
            {
                return string.Empty;
            }
            return string.Join(
                "|",
                runtime.AlignmentConfigurationFingerprint,
                policy.MotionModelConfiguration,
                policy.SmoothingStrategyConfiguration,
                policy.ConfigurationFingerprint);
        }

        /// <summary>解析 Link/Editor 本机 replay 根目录。</summary>
        private string ResolveOutputRoot()
        {
            if (!string.IsNullOrWhiteSpace(outputRoot))
            {
                string configured = outputRoot.Trim();
                return Path.IsPathRooted(configured)
                    ? Path.GetFullPath(configured)
                    : Path.GetFullPath(Path.Combine(Application.dataPath, "..", configured));
            }
            return ResolveDefaultEditorOutputRoot(Application.dataPath);
        }

        /// <summary>从 Unity Assets 目录稳定推导仓库本机 Python replay 数据目录。</summary>
        public static string ResolveDefaultEditorOutputRoot(string applicationDataPath)
        {
            if (string.IsNullOrWhiteSpace(applicationDataPath))
            {
                throw new ArgumentException("applicationDataPath cannot be empty", nameof(applicationDataPath));
            }
            return Path.GetFullPath(
                Path.Combine(applicationDataPath, "..", "..", "EgoAnchor_Python", "data", "replay_capture"));
        }

        /// <summary>生成不依赖 Python formal session 的 capture_id。</summary>
        private static string BuildCaptureId(string objectId)
        {
            string safeObject = string.IsNullOrWhiteSpace(objectId) ? "object" : objectId.Trim();
            foreach (char invalid in Path.GetInvalidFileNameChars())
            {
                safeObject = safeObject.Replace(invalid, '_');
            }
            return $"{DateTime.UtcNow:yyyyMMdd_HHmmss_fff}_{safeObject}";
        }

        /// <summary>创建录制中清单。</summary>
        private ReplayManifestDto BuildManifest(string captureId)
        {
            return new ReplayManifestDto
            {
                capture_id = captureId,
                object_id = objectId?.Trim() ?? string.Empty,
                scene_name = gameObject.scene.name,
                unity_version = Application.unityVersion,
                application_version = Application.version,
                run_mode = "editor_link",
                output_root = ResolveOutputRoot(),
                platform_reference_transform_path = BuildTransformPath(platformReference),
                platform_reference_controller = platformReferenceController.ToString(),
                capture_fps = captureFps,
                created_unix_ms = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                complete = false,
                model_mesh_path = modelMeshPath?.Trim() ?? string.Empty,
                model_apply_scale = modelApplyScale,
                variant_ids = new[] { ArrivalHoldId, CaptureHoldId, OneEuroId, EgoAnchorId },
                variant_colors_hex = new[]
                {
                    ArrivalHoldColor,
                    CaptureHoldColor,
                    OneEuroColor,
                    EgoAnchorColor,
                },
            };
        }

        /// <summary>构造稳定的场景层级路径。</summary>
        private static string BuildTransformPath(Transform transform)
        {
            if (transform == null)
            {
                return string.Empty;
            }
            Stack<string> names = new Stack<string>();
            Transform current = transform;
            while (current != null)
            {
                names.Push(current.name);
                current = current.parent;
            }
            return string.Join("/", names);
        }

        /// <summary>通过同目录临时文件发布 replay_manifest.json，替换失败时保留旧清单。</summary>
        private static void WriteManifest(string directory, ReplayManifestDto value)
        {
            string path = Path.Combine(directory, "replay_manifest.json");
            string temporaryPath = path + ".tmp";
            File.WriteAllText(temporaryPath, JsonUtility.ToJson(value, prettyPrint: true));
            if (File.Exists(path))
            {
                try
                {
                    File.Replace(temporaryPath, path, null);
                    return;
                }
                catch (PlatformNotSupportedException)
                {
                    ReplaceManifestWithBackup(path, temporaryPath);
                    return;
                }
            }
            File.Move(temporaryPath, path);
        }

        /// <summary>不支持 File.Replace 的平台使用可恢复备份，第二步失败时还原旧清单。</summary>
        private static void ReplaceManifestWithBackup(string path, string temporaryPath)
        {
            string backupPath = path + ".bak";
            if (File.Exists(backupPath))
            {
                File.Delete(backupPath);
            }
            File.Move(path, backupPath);
            try
            {
                File.Move(temporaryPath, path);
                File.Delete(backupPath);
            }
            catch
            {
                if (!File.Exists(path) && File.Exists(backupPath))
                {
                    File.Move(backupPath, path);
                }
                throw;
            }
        }

        /// <summary>JPEG 回调在 LateUpdate 前的轻量暂存。</summary>
        private readonly struct PendingCapture
        {
            /// <summary>背景 frame_id。</summary>
            public readonly long FrameId;

            /// <summary>不可变左目 JPEG。</summary>
            public readonly ByteString LeftImageJpeg;

            /// <summary>JPEG 宽度。</summary>
            public readonly int Width;

            /// <summary>JPEG 高度。</summary>
            public readonly int Height;

            /// <summary>JPEG 质量。</summary>
            public readonly int JpegQuality;

            /// <summary>图像代理与 payload-ready 双时间。</summary>
            public readonly FrameCaptureTiming Timing;

            /// <summary>ZMQ 发布尝试时间。</summary>
            public readonly double PublishAttemptMonoMs;

            /// <summary>ZMQ 发布是否成功。</summary>
            public readonly bool PublishSucceeded;

            /// <summary>本样本左目标定。</summary>
            public readonly QuestCameraInfo CameraInfo;

            /// <summary>构造一条待配对 frame。</summary>
            public PendingCapture(
                long frameId,
                ByteString leftImageJpeg,
                int width,
                int height,
                int jpegQuality,
                FrameCaptureTiming timing,
                double publishAttemptMonoMs,
                bool publishSucceeded,
                QuestCameraInfo cameraInfo)
            {
                FrameId = frameId;
                LeftImageJpeg = leftImageJpeg;
                Width = width;
                Height = height;
                JpegQuality = jpegQuality;
                Timing = timing;
                PublishAttemptMonoMs = publishAttemptMonoMs;
                PublishSucceeded = publishSucceeded;
                CameraInfo = cameraInfo;
            }
        }

        /// <summary>单个 Unity render frame 的平台参考与四路方法快照。</summary>
        private readonly struct ReplayPoseFrame
        {
            /// <summary>Unity 渲染帧号。</summary>
            public readonly int UnityFrame;

            /// <summary>LateUpdate 锁存时间。</summary>
            public readonly double MonoMs;

            /// <summary>同一渲染帧的 Quest 官方右手柄参考。</summary>
            public readonly EvalReferencePose PlatformReference;

            /// <summary>固定顺序四路状态。</summary>
            public readonly ReplayVariantState[] Variants;

            /// <summary>构造一帧历史。</summary>
            public ReplayPoseFrame(
                int unityFrame,
                double monoMs,
                EvalReferencePose platformReference,
                ReplayVariantState[] variants)
            {
                UnityFrame = unityFrame;
                MonoMs = monoMs;
                PlatformReference = platformReference;
                Variants = variants;
            }
        }

        /// <summary>一个方法在某 Unity render frame 的纯值状态。</summary>
        private readonly struct ReplayVariantState
        {
            /// <summary>方法标识。</summary>
            public readonly string VariantId;

            /// <summary>论文颜色。</summary>
            public readonly string ColorHex;

            /// <summary>是否有 runtime output。</summary>
            public readonly bool HasOutputPose;

            /// <summary>runtime output world pose。</summary>
            public readonly Pose OutputWorldPose;

            /// <summary>是否有实际显示。</summary>
            public readonly bool HasDisplayPose;

            /// <summary>实际显示 world pose。</summary>
            public readonly Pose DisplayWorldPose;

            /// <summary>transform、hold_last 或 none。</summary>
            public readonly string PoseSource;

            /// <summary>显示来源候选 frame_id。</summary>
            public readonly long SourceFrameId;

            /// <summary>坐标与对齐配置指纹。</summary>
            public readonly string RuntimeConfigurationFingerprint;

            /// <summary>构造一个方法的纯值快照。</summary>
            public ReplayVariantState(
                string variantId,
                string colorHex,
                bool hasOutputPose,
                Pose outputWorldPose,
                bool hasDisplayPose,
                Pose displayWorldPose,
                string poseSource,
                long sourceFrameId,
                string runtimeConfigurationFingerprint)
            {
                VariantId = variantId;
                ColorHex = colorHex;
                HasOutputPose = hasOutputPose;
                OutputWorldPose = outputWorldPose;
                HasDisplayPose = hasDisplayPose;
                DisplayWorldPose = displayWorldPose;
                PoseSource = poseSource;
                SourceFrameId = sourceFrameId;
                RuntimeConfigurationFingerprint = runtimeConfigurationFingerprint;
            }
        }
    }
}

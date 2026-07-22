using System;
using EgoAnchor.Diagnostics;
using EgoAnchor.Protocol;
using EgoAnchor.Protocol.Generated;
using EgoAnchor.Quest;
using EgoAnchor.Transport;
using Google.Protobuf;
using UnityEngine;

namespace EgoAnchor.Client
{
    /// <summary>发布器已经编码完成的只读左目 payload，供旁路采集复用。</summary>
    public readonly struct EncodedLeftFrame
    {
        /// <summary>背景帧的稳定 frame_id。</summary>
        public readonly long FrameId;

        /// <summary>不可变左目 JPEG 字节。</summary>
        public readonly ByteString ImageJpeg;

        /// <summary>JPEG 宽度。</summary>
        public readonly int Width;

        /// <summary>JPEG 高度。</summary>
        public readonly int Height;

        /// <summary>JPEG 编码质量。</summary>
        public readonly int JpegQuality;

        /// <summary>从已编码 stereo 消息复制只读标量和 ByteString 引用。</summary>
        public EncodedLeftFrame(long frameId, ByteString imageJpeg, int width, int height, int jpegQuality)
        {
            FrameId = frameId;
            ImageJpeg = imageJpeg ?? ByteString.Empty;
            Width = width;
            Height = height;
            JpegQuality = jpegQuality;
        }
    }

    /// <summary>
    /// Quest 传感器流发布组件。
    ///
    /// 本组件是 通信 demo 的 Unity 场景入口，负责把：
    /// - Quest/StereoFrameSource 采集到的 QuestStereoFrame；
    /// - Quest/CameraInfoSource 采集到的 QuestCameraInfo；
    /// 按不同 topic 通过 Transport/ZmqTopicPublisher 发给 Python。
    /// </summary>
    public sealed class QuestStreamPublisher : MonoBehaviour
    {
        /// <summary>统一日志通道。</summary>
        private static readonly EgoAnchorLog.Channel Log = EgoAnchorLog.For<QuestStreamPublisher>();

        /// <summary>重新创建 publisher 的最小间隔，避免连接失败时每帧狂重试。</summary>
        private const double PublisherRetryIntervalSeconds = 1.0;

        /// <summary>Python 接收端 IP。</summary>
        [Header("Network / ZMQ")]
        [Tooltip("Python 数据接收端 IP。统一由 ServerEndpointConfig 在启动时下发 (SetServerIp)；也可直接在此填固定 IP。")]
        [SerializeField] private string serverIp = "127.0.0.1";

        /// <summary>Python 接收端端口。</summary>
        [Tooltip("Python 数据接收端端口。默认 15557；不要回退到旧链路 5557。")]
        [Min(1)]
        [SerializeField] private int serverPort = 15557;

        /// <summary>ZMQ 发送高水位。</summary>
        [Tooltip("ZMQ 发送高水位。数值越小越倾向丢弃积压帧，适合 latest-only 实时视频流。")]
        [Min(1)]
        [SerializeField] private int sendHighWatermark = 5;

        /// <summary>Socket 关闭 linger 毫秒数。</summary>
        [Tooltip("Socket 关闭时等待未发送消息的毫秒数。Play Mode/应用退出建议保持 0，避免退出卡顿。")]
        [Min(0)]
        [SerializeField] private int socketLingerMs = 0;

        /// <summary>双目图像源。</summary>
        [Header("Quest Sources")]
        [Tooltip("Quest 双目图像源：读取左右 Passthrough texture、JPEG 编码，并记录 frame_id 对应的左目相机位姿。")]
        [SerializeField] private StereoFrameSource stereoSource;

        /// <summary>相机标定源。</summary>
        [Tooltip("Quest 相机标定源：读取左右相机 intrinsics、lens pose、分辨率和 baseline。")]
        [SerializeField] private CameraInfoSource cameraInfoSource;

        /// <summary>双目图像目标发送帧率。</summary>
        [Header("Send Rates")]
        [Tooltip("双目图像目标发送帧率。实际帧率受相机刷新、JPEG 编码耗时和 ZMQ 发送结果影响。")]
        [Min(1)]
        [SerializeField] private int stereoFps = 30;

        /// <summary>相机标定发送频率。</summary>
        [Tooltip("相机标定发送频率。标定低频刷新即可；Python 端按 topic 独立缓存 latest camera_info。")]
        [Min(0.1f)]
        [SerializeField] private float cameraInfoFps = 1f;

        /// <summary>是否输出聚合统计。</summary>
        [Header("Debug")]
        [Tooltip("是否周期性输出发送统计。高频路径默认只打印聚合统计，避免每帧日志拖慢 Quest。")]
        [SerializeField] private bool logStats = true;

        /// <summary>统计输出间隔。</summary>
        [Tooltip("累计发送/丢弃/采集失败达到多少条后打印一次统计。")]
        [Min(1)]
        [SerializeField] private int statsIntervalFrames = 120;

        /// <summary>Quest Link/OpenXR 丢失 VR focus 时是否暂停高负载图像采集。</summary>
        [Header("XR Focus")]
        [Tooltip("VR focus 丢失时暂停双目 GPU 读回和 JPEG 编码；focus 恢复后自动继续，避免黑屏期间继续占用渲染主线程。")]
        [SerializeField] private bool pauseWhenVrFocusLost = true;

        /// <summary>底层 ZMQ topic 发布器。</summary>
        private ZmqTopicPublisher publisher;

        /// <summary>上次发送 stereo 的 Unity 单调时间。</summary>
        private double lastStereoSendTime;

        /// <summary>上次发送 camera_info 的 Unity 单调时间。</summary>
        private double lastCameraInfoSendTime;

        /// <summary>累计成功发送 stereo 数。</summary>
        private int sentStereo;

        /// <summary>累计成功发送 camera_info 数。</summary>
        private int sentCameraInfo;

        /// <summary>累计发送失败或队列满丢弃数。</summary>
        private int dropped;

        /// <summary>累计采集失败数。</summary>
        private int captureFailed;

        /// <summary>上次打印统计时的总计数。</summary>
        private int lastLoggedTotal;

        /// <summary>stereo 完成一次 ZMQ 发布尝试后触发；订阅者异常不会中断数据面。</summary>
        public event Action<FrameCaptureTiming, double, bool> StereoPublishAttempted;

        /// <summary>
        /// stereo 完成一次 ZMQ 发布尝试后触发，并暴露本次已经编码完成的只读左目 payload。
        /// 定性 replay 采集器通过该事件复用左目 JPEG，避免第二次 GPU 读回和 JPEG 编码。
        /// </summary>
        public event Action<EncodedLeftFrame, FrameCaptureTiming, double, bool> StereoFrameCaptured;

        /// <summary>Quest Link/OpenXR 的 VR focus 状态变化后触发。</summary>
        public event Action<bool> VrFocusChanged;

        /// <summary>OpenXR 当前是否把 VR focus 交给 Unity 应用。</summary>
        public bool HasVrFocus { get; private set; } = true;

        /// <summary>当前是否因 VR focus 丢失而暂停双目采集。</summary>
        public bool CapturePausedForVrFocus => pauseWhenVrFocusLost && !HasVrFocus;

        /// <summary>上次尝试重建 publisher 的 Unity 单调时间。</summary>
        private double lastPublisherAttemptTime;

        /// <summary>
        /// 更新 Python 接收端 IP (供 ServerEndpointConfig 启动时下发)。已连接则重建 publisher 使新 IP 生效。
        /// </summary>
        /// <param name="ip">新的 Python 接收端 IP。</param>
        public void SetServerIp(string ip)
        {
            if (string.IsNullOrWhiteSpace(ip))
            {
                return;
            }

            string trimmed = ip.Trim();
            if (trimmed == serverIp)
            {
                return;
            }

            serverIp = trimmed;
            if (isActiveAndEnabled)
            {
                TryStartPublisher(force: true);
            }
        }

        /// <summary>
        /// Unity Awake：开启新会话。IP 由 ServerEndpointConfig (执行序更早) 在此之前下发, 或用序列化默认值。
        /// </summary>
        private void Awake()
        {
            QuestStreamSession.BeginNewSession();
        }

        /// <summary>
        /// Unity Start：确保 publisher 已启动。
        /// </summary>
        private void Start()
        {
            TryStartPublisher(force: false);
        }

        /// <summary>
        /// Unity 启用时重新连接 publisher。用于 Play Mode 重入和组件重新启用。
        /// </summary>
        private void OnEnable()
        {
            OVRManager.VrFocusAcquired += OnVrFocusAcquired;
            OVRManager.VrFocusLost += OnVrFocusLost;
            HasVrFocus = !Application.isPlaying || OVRManager.hasVrFocus;
            QuestStreamSession.BeginNewSession();
            TryStartPublisher(force: true);
        }

        /// <summary>
        /// 重建 ZMQ publisher。可由 UI 网络设置面板或调试按钮调用。
        /// </summary>
        public void RestartPublisher()
        {
            DisposePublisher();
            TryStartPublisher(force: true);
        }

        /// <summary>
        /// Unity Update：按配置频率发送 camera_info 与 stereo。
        /// </summary>
        private void Update()
        {
            double now = Time.realtimeSinceStartupAsDouble;
            TryStartPublisher(force: false);
            if (publisher == null)
            {
                MaybeLogStats();
                return;
            }

            if (CapturePausedForVrFocus)
            {
                MaybeLogStats();
                return;
            }

            TrySendCameraInfo(now);
            TrySendStereo(now);
            MaybeLogStats();
        }

        /// <summary>
        /// 按目标帧率尝试发送一帧 stereo。
        /// </summary>
        private void TrySendStereo(double now)
        {
            double interval = 1.0 / Mathf.Max(1, stereoFps);
            if (now - lastStereoSendTime < interval)
            {
                return;
            }
            lastStereoSendTime = now;

            if (stereoSource == null || !stereoSource.TryCapture(out QuestStereoFrame frame))
            {
                captureFailed++;
                return;
            }

            byte[] payload = frame.ToByteArray();
            double publishAttemptMonoMs = Time.realtimeSinceStartupAsDouble * 1000.0;
            bool sent = publisher != null && publisher.TrySend(SubjectNames.QuestStereo, payload);
            if (stereoSource.TryGetCaptureTiming(frame.Header.FrameId, out FrameCaptureTiming timing))
            {
                NotifyStereoPublishAttempted(timing, publishAttemptMonoMs, sent);
                NotifyStereoFrameCaptured(
                    new EncodedLeftFrame(
                        frame.Header.FrameId,
                        frame.LeftImageJpeg,
                        frame.LeftWidth,
                        frame.LeftHeight,
                        frame.JpegQuality),
                    timing,
                    publishAttemptMonoMs,
                    sent);
            }
            if (sent)
            {
                sentStereo++;
            }
            else
            {
                dropped++;
            }
        }

        /// <summary>隔离诊断订阅者异常，避免评估代码打断实时发布。</summary>
        private void NotifyStereoPublishAttempted(
            FrameCaptureTiming timing,
            double publishAttemptMonoMs,
            bool publishSucceeded)
        {
            Action<FrameCaptureTiming, double, bool> handlers = StereoPublishAttempted;
            if (handlers == null)
            {
                return;
            }

            foreach (Delegate handler in handlers.GetInvocationList())
            {
                try
                {
                    ((Action<FrameCaptureTiming, double, bool>)handler).Invoke(
                        timing,
                        publishAttemptMonoMs,
                        publishSucceeded);
                }
                catch (Exception exc)
                {
                    Log.Warning($"stereo publish diagnostic callback ignored: {exc.Message}", this);
                }
            }
        }

        /// <summary>隔离 replay 订阅者异常，避免定性采集功能打断实时数据面。</summary>
        /// <param name="frame">本次已经发送尝试的只读左目 JPEG 和标量。</param>
        /// <param name="timing">图像时间代理与 payload-ready 时间。</param>
        /// <param name="publishAttemptMonoMs">ZMQ 发送尝试的 Unity 单调时钟毫秒。</param>
        /// <param name="publishSucceeded">本次 ZMQ 发送是否成功。</param>
        private void NotifyStereoFrameCaptured(
            EncodedLeftFrame frame,
            FrameCaptureTiming timing,
            double publishAttemptMonoMs,
            bool publishSucceeded)
        {
            Action<EncodedLeftFrame, FrameCaptureTiming, double, bool> handlers = StereoFrameCaptured;
            if (handlers == null)
            {
                return;
            }

            foreach (Delegate handler in handlers.GetInvocationList())
            {
                try
                {
                    ((Action<EncodedLeftFrame, FrameCaptureTiming, double, bool>)handler).Invoke(
                        frame,
                        timing,
                        publishAttemptMonoMs,
                        publishSucceeded);
                }
                catch (Exception exc)
                {
                    Log.Warning($"qualitative replay frame callback failed: {exc.Message}", this);
                }
            }
        }

        /// <summary>
        /// 按低频节奏发送相机标定。
        /// </summary>
        private void TrySendCameraInfo(double now)
        {
            double interval = 1.0 / Mathf.Max(0.1f, cameraInfoFps);
            if (now - lastCameraInfoSendTime < interval)
            {
                return;
            }
            lastCameraInfoSendTime = now;

            if (cameraInfoSource == null || !cameraInfoSource.TryCapture(out QuestCameraInfo info))
            {
                captureFailed++;
                return;
            }

            bool sent = publisher != null && publisher.TrySend(SubjectNames.QuestCameraInfo, info.ToByteArray());
            if (sent)
            {
                sentCameraInfo++;
            }
            else
            {
                dropped++;
            }
        }

        /// <summary>
        /// 聚合输出发送统计。
        /// </summary>
        private void MaybeLogStats()
        {
            if (!logStats || statsIntervalFrames <= 0)
            {
                return;
            }

            int total = sentStereo + sentCameraInfo + dropped + captureFailed;
            if (total > 0 && total - lastLoggedTotal >= statsIntervalFrames)
            {
                lastLoggedTotal = total;
                Log.Info(
                    $"stereo={sentStereo}, camera_info={sentCameraInfo}, " +
                    $"dropped={dropped}, captureFailed={captureFailed}, endpoint={publisher?.Endpoint}",
                    this);
            }
        }

        /// <summary>
        /// Unity 销毁组件时释放 ZMQ。
        /// </summary>
        private void OnDestroy()
        {
            DisposePublisher();
        }

        /// <summary>
        /// Unity 禁用组件时释放 ZMQ，避免切场景或退出 Play Mode 时残留 socket。
        /// </summary>
        private void OnDisable()
        {
            OVRManager.VrFocusAcquired -= OnVrFocusAcquired;
            OVRManager.VrFocusLost -= OnVrFocusLost;
            DisposePublisher();
        }

        /// <summary>
        /// 应用退出时释放 ZMQ。
        /// </summary>
        private void OnApplicationQuit()
        {
            DisposePublisher();
        }

        /// <summary>
        /// 统一释放 publisher，确保可重复调用。
        /// </summary>
        private void DisposePublisher()
        {
            publisher?.Dispose();
            publisher = null;
        }

        /// <summary>VR focus 恢复后继续采集，并通知评估事件记录器。</summary>
        private void OnVrFocusAcquired()
        {
            SetVrFocus(true);
        }

        /// <summary>VR focus 丢失后立即暂停高负载采集，并通知评估事件记录器。</summary>
        private void OnVrFocusLost()
        {
            SetVrFocus(false);
        }

        /// <summary>更新 VR focus 状态并隔离诊断订阅者异常。</summary>
        private void SetVrFocus(bool hasFocus)
        {
            if (HasVrFocus == hasFocus) return;
            HasVrFocus = hasFocus;
            if (hasFocus)
            {
                lastStereoSendTime = Time.realtimeSinceStartupAsDouble;
                lastCameraInfoSendTime = lastStereoSendTime;
                Log.Info("Quest VR focus restored; stereo capture resumed.", this);
            }
            else
            {
                Log.Warning("Quest VR focus lost; stereo capture paused until focus returns.", this);
            }

            Action<bool> handlers = VrFocusChanged;
            if (handlers == null) return;
            foreach (Delegate handler in handlers.GetInvocationList())
            {
                try
                {
                    ((Action<bool>)handler).Invoke(hasFocus);
                }
                catch (Exception exc)
                {
                    Log.Warning($"VR focus diagnostic callback ignored: {exc.Message}", this);
                }
            }
        }

        /// <summary>
        /// 尝试创建并连接底层 ZMQ publisher。
        /// 连接失败时不抛给 Unity 主循环，而是延迟重试，避免 Play Mode 启动阶段被一次性失败卡死。
        /// </summary>
        /// <param name="force">是否忽略重试间隔，立即尝试一次。</param>
        /// <returns>本次是否已经成功持有可用 publisher。</returns>
        private bool TryStartPublisher(bool force)
        {
            if (publisher != null)
            {
                return true;
            }

            double now = Time.realtimeSinceStartupAsDouble;
            if (!force && now - lastPublisherAttemptTime < PublisherRetryIntervalSeconds)
            {
                return false;
            }

            lastPublisherAttemptTime = now;

            try
            {
                publisher = new ZmqTopicPublisher();
                publisher.Connect(serverIp, serverPort, sendHighWatermark, socketLingerMs);
                lastStereoSendTime = 0.0;
                lastCameraInfoSendTime = 0.0;
                return true;
            }
            catch (Exception exc)
            {
                Log.Warning($"publisher connect failed, will retry: {exc.Message}", this);
                DisposePublisher();
                return false;
            }
        }
    }
}

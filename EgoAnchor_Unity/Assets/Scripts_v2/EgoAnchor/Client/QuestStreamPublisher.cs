using System;
using EgoAnchor.Protocol.V1;
using EgoAnchor.V2.Protocol;
using EgoAnchor.V2.Transport;
using Google.Protobuf;
using Meta.XR;
using UnityEngine;

namespace EgoAnchor.V2.Client
{
    /// <summary>
    /// Unity -> Python 的 Quest 输入流发布器。
    ///
    /// 职责：
    /// - 从左右 PassthroughCameraAccess 读取 texture；
    /// - JPEG 编码为 QuestStereoFrame protobuf；
    /// - 低频读取 camera intrinsics，编码为 QuestCameraInfo protobuf；
    /// - 发布到 v2 subject；
    /// - 在成功捕获 stereo frame 时触发 OnFrameEncoded(frameId, leftCameraPose)，供 frame-aligned anchor 缓存发送帧相机位姿。
    ///
    /// 当前实现优先保证功能闭环，后续真机性能优化时可减少临时对象、改异步 GPU readback。
    /// </summary>
    public class QuestStreamPublisher : MonoBehaviour
    {
        [SerializeField] private NatsConnection connection;
        [SerializeField] private PassthroughCameraAccess leftCameraAccess;
        [SerializeField] private PassthroughCameraAccess rightCameraAccess;
        [SerializeField] private string clientId = "unity";
        [SerializeField] private string anchorId = "main";
        [SerializeField] private float stereoFps = 10f;
        [SerializeField] private float cameraInfoFps = 1f;
        [Range(0.25f, 1f)]
        [SerializeField] private float outputScale = 1f;
        [Range(30, 100)]
        [SerializeField] private int jpegQuality = 90;
        [Header("Debug")]
        [SerializeField] private bool enableStatsLog;
        [SerializeField] private float statsLogIntervalSeconds = 2f;

        public FramePoseEvent OnFrameEncoded = new FramePoseEvent();

        private RenderTexture _leftRenderTexture;
        private RenderTexture _rightRenderTexture;
        private Texture2D _leftReadbackTexture;
        private Texture2D _rightReadbackTexture;
        private long _frameId;
        private double _nextStereoAt;
        private double _nextCameraInfoAt;
        private double _statsWindowStart;
        private int _stereoProducedInWindow;
        private int _stereoEnqueuedInWindow;
        private int _cameraInfoProducedInWindow;
        private int _cameraInfoEnqueuedInWindow;
        private long _payloadBytesInWindow;
        private int _failConnectionNull;
        private int _failCameraNull;
        private int _failNotPlaying;
        private int _failTextureNull;
        private int _failCameraPose;
        private int _failJpeg;
        private int _publishFailure;

        private void Update()
        {
            // 简单按 FPS 产出最新帧；发送层按 subject latest-only 覆盖旧 payload，避免网络层排队。
            if (connection == null)
            {
                return;
            }

            double now = Time.realtimeSinceStartupAsDouble;
            if (stereoFps > 0f && now >= _nextStereoAt)
            {
                _nextStereoAt = now + 1.0 / stereoFps;
                PublishStereo();
            }

            if (cameraInfoFps > 0f && now >= _nextCameraInfoAt)
            {
                _nextCameraInfoAt = now + 1.0 / cameraInfoFps;
                PublishCameraInfo();
            }

            MaybeLogStats(now);
        }

        private void PublishStereo()
        {
            // 高频实时流不做 ack；NATS Core at-most-once，发送端 latest-only 覆盖旧帧。
            if (!TryBuildStereoFrame(out QuestStereoFrame frame))
            {
                return;
            }

            PublishLatest(SubjectNames.QuestStereo, frame.ToByteArray(), true);
        }

        private void PublishCameraInfo()
        {
            // camera_info 是低频静态输入；Python 端收到后版本号递增并可刷新标定。
            if (!TryBuildCameraInfo(out QuestCameraInfo info))
            {
                return;
            }

            PublishLatest(SubjectNames.QuestCameraInfo, info.ToByteArray(), false);
        }

        private void PublishLatest(string subject, byte[] payload, bool stereo)
        {
            // 统一发布入口，便于后续增加限频日志或统计。
            if (connection == null)
            {
                _failConnectionNull++;
                return;
            }

            try
            {
                if (stereo)
                {
                    _stereoProducedInWindow++;
                }
                else
                {
                    _cameraInfoProducedInWindow++;
                }

                if (!connection.PublishLatest(subject, payload))
                {
                    _publishFailure++;
                    return;
                }

                if (stereo)
                {
                    _stereoEnqueuedInWindow++;
                }
                else
                {
                    _cameraInfoEnqueuedInWindow++;
                }
                _payloadBytesInWindow += payload?.Length ?? 0;
            }
            catch (Exception e)
            {
                _publishFailure++;
                Debug.LogWarning($"[EgoAnchorV2] Publish failed subject={subject}: {e.Message}", this);
            }
        }

        private bool TryBuildStereoFrame(out QuestStereoFrame frame)
        {
            // 只有左右 Passthrough camera 都在播放时才发送 stereo。
            frame = null;
            if (leftCameraAccess == null || rightCameraAccess == null || !leftCameraAccess.IsPlaying || !rightCameraAccess.IsPlaying)
            {
                if (leftCameraAccess == null || rightCameraAccess == null)
                {
                    _failCameraNull++;
                }
                else
                {
                    _failNotPlaying++;
                }
                return false;
            }

            Texture leftTexture = leftCameraAccess.GetTexture();
            Texture rightTexture = rightCameraAccess.GetTexture();
            if (leftTexture == null || rightTexture == null)
            {
                _failTextureNull++;
                return false;
            }

            Pose leftPose;
            try
            {
                leftPose = leftCameraAccess.GetCameraPose();
            }
            catch
            {
                _failCameraPose++;
                return false;
            }

            EnsureCaptureBuffers(leftTexture, rightTexture);
            Graphics.Blit(leftTexture, _leftRenderTexture);
            Graphics.Blit(rightTexture, _rightRenderTexture);

            byte[] leftJpeg = EncodeRenderTextureToJpeg(_leftRenderTexture, _leftReadbackTexture);
            byte[] rightJpeg = EncodeRenderTextureToJpeg(_rightRenderTexture, _rightReadbackTexture);
            if (leftJpeg == null || rightJpeg == null)
            {
                _failJpeg++;
                return false;
            }

            long frameId = ++_frameId;
            // 必须在同一帧读取左目 camera pose 并和 frame_id 一起发给 anchor 缓存。
            OnFrameEncoded?.Invoke(frameId, leftPose);
            frame = new QuestStereoFrame
            {
                Header = CreateHeader(frameId),
                LeftImageJpeg = ByteString.CopyFrom(leftJpeg),
                RightImageJpeg = ByteString.CopyFrom(rightJpeg),
                LeftWidth = _leftReadbackTexture.width,
                LeftHeight = _leftReadbackTexture.height,
                RightWidth = _rightReadbackTexture.width,
                RightHeight = _rightReadbackTexture.height,
                JpegQuality = jpegQuality,
            };
            return true;
        }

        private bool TryBuildCameraInfo(out QuestCameraInfo info)
        {
            // v2 camera_info 字段基本沿用旧 QuestCameraInfoMsg，迁移为强类型 protobuf。
            info = null;
            if (leftCameraAccess == null || rightCameraAccess == null || !leftCameraAccess.IsPlaying || !rightCameraAccess.IsPlaying)
            {
                if (leftCameraAccess == null || rightCameraAccess == null)
                {
                    _failCameraNull++;
                }
                else
                {
                    _failNotPlaying++;
                }
                return false;
            }

            PassthroughCameraAccess.CameraIntrinsics leftIntr = leftCameraAccess.Intrinsics;
            PassthroughCameraAccess.CameraIntrinsics rightIntr = rightCameraAccess.Intrinsics;
            Vector2Int leftRes = leftCameraAccess.CurrentResolution;
            int sensorWidth = leftIntr.SensorResolution.x;
            int sensorHeight = leftIntr.SensorResolution.y;
            float baseline = Vector3.Distance(leftIntr.LensOffset.position, rightIntr.LensOffset.position);

            info = new QuestCameraInfo
            {
                Header = CreateHeader(0),
                IsSupported = PassthroughCameraAccess.IsSupported,
                LeftFx = leftIntr.FocalLength.x,
                LeftFy = leftIntr.FocalLength.y,
                LeftCx = leftIntr.PrincipalPoint.x,
                LeftCy = leftIntr.PrincipalPoint.y,
                RightFx = rightIntr.FocalLength.x,
                RightFy = rightIntr.FocalLength.y,
                RightCx = rightIntr.PrincipalPoint.x,
                RightCy = rightIntr.PrincipalPoint.y,
                BaselineM = baseline,
                SensorWidth = sensorWidth,
                SensorHeight = sensorHeight,
                ActiveLeft = 0,
                ActiveTop = 0,
                ActiveRight = sensorWidth,
                ActiveBottom = sensorHeight,
                LeftRequestedWidth = leftCameraAccess.RequestedResolution.x,
                LeftRequestedHeight = leftCameraAccess.RequestedResolution.y,
                RightRequestedWidth = rightCameraAccess.RequestedResolution.x,
                RightRequestedHeight = rightCameraAccess.RequestedResolution.y,
                CurrentWidth = leftRes.x,
                CurrentHeight = leftRes.y,
                MaxFramerate = leftCameraAccess.MaxFramerate,
                LeftLensPose = ToLensPose(leftIntr.LensOffset),
                RightLensPose = ToLensPose(rightIntr.LensOffset),
            };
            return true;
        }

        private MessageHeader CreateHeader(long frameId)
        {
            // stream message 没有 request_id；frame_id/unity_frame/sender_mono_ms 用于对齐和诊断。
            return new MessageHeader
            {
                MessageId = Guid.NewGuid().ToString("N"),
                ClientId = clientId,
                AnchorId = anchorId,
                FrameId = frameId,
                UnityFrame = Time.frameCount,
                SenderMonoMs = Time.realtimeSinceStartupAsDouble * 1000.0,
                CreatedUnixMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                SchemaVersion = "v1",
            };
        }

        private static LensPose ToLensPose(Pose pose)
        {
            // Unity Pose -> protobuf LensPose；这里只记录数值，不做坐标系转换。
            return new LensPose
            {
                Position = new Vec3 { X = pose.position.x, Y = pose.position.y, Z = pose.position.z },
                Rotation = new Quat { X = pose.rotation.x, Y = pose.rotation.y, Z = pose.rotation.z, W = pose.rotation.w },
            };
        }

        private void EnsureCaptureBuffers(Texture leftTexture, Texture rightTexture)
        {
            // 根据源 texture 和 outputScale 复用 RenderTexture/Texture2D，避免每帧分配大对象。
            int leftWidth = Mathf.Max(1, Mathf.RoundToInt(leftTexture.width * outputScale));
            int leftHeight = Mathf.Max(1, Mathf.RoundToInt(leftTexture.height * outputScale));
            int rightWidth = Mathf.Max(1, Mathf.RoundToInt(rightTexture.width * outputScale));
            int rightHeight = Mathf.Max(1, Mathf.RoundToInt(rightTexture.height * outputScale));

            if (_leftRenderTexture == null || _leftReadbackTexture == null || _leftRenderTexture.width != leftWidth || _leftRenderTexture.height != leftHeight)
            {
                ReleaseBuffer(ref _leftRenderTexture, ref _leftReadbackTexture);
                _leftRenderTexture = new RenderTexture(leftWidth, leftHeight, 0, RenderTextureFormat.ARGB32);
                _leftReadbackTexture = new Texture2D(leftWidth, leftHeight, TextureFormat.RGB24, false);
            }

            if (_rightRenderTexture == null || _rightReadbackTexture == null || _rightRenderTexture.width != rightWidth || _rightRenderTexture.height != rightHeight)
            {
                ReleaseBuffer(ref _rightRenderTexture, ref _rightReadbackTexture);
                _rightRenderTexture = new RenderTexture(rightWidth, rightHeight, 0, RenderTextureFormat.ARGB32);
                _rightReadbackTexture = new Texture2D(rightWidth, rightHeight, TextureFormat.RGB24, false);
            }
        }

        private byte[] EncodeRenderTextureToJpeg(RenderTexture source, Texture2D readbackTexture)
        {
            // 同步 ReadPixels 简单可靠，但可能带来主线程开销；性能优化阶段再考虑 AsyncGPUReadback。
            RenderTexture prev = RenderTexture.active;
            try
            {
                RenderTexture.active = source;
                readbackTexture.ReadPixels(new Rect(0, 0, source.width, source.height), 0, 0, false);
                readbackTexture.Apply(false, false);
                return readbackTexture.EncodeToJPG(jpegQuality);
            }
            finally
            {
                RenderTexture.active = prev;
            }
        }

        private static void ReleaseBuffer(ref RenderTexture renderTexture, ref Texture2D texture)
        {
            if (renderTexture != null)
            {
                renderTexture.Release();
                Destroy(renderTexture);
                renderTexture = null;
            }

            if (texture != null)
            {
                Destroy(texture);
                texture = null;
            }
        }

        private void OnDestroy()
        {
            ReleaseBuffer(ref _leftRenderTexture, ref _leftReadbackTexture);
            ReleaseBuffer(ref _rightRenderTexture, ref _rightReadbackTexture);
        }

        private void MaybeLogStats(double now)
        {
            if (!enableStatsLog)
            {
                return;
            }

            if (_statsWindowStart <= 0.0)
            {
                _statsWindowStart = now;
                return;
            }

            double elapsed = now - _statsWindowStart;
            float interval = Mathf.Max(0.5f, statsLogIntervalSeconds);
            if (elapsed < interval)
            {
                return;
            }

            NatsConnection.LatestPublishStats stereoStats = connection != null
                ? connection.GetLatestPublishStats(SubjectNames.QuestStereo, true)
                : NatsConnection.LatestPublishStats.Empty;
            NatsConnection.LatestPublishStats cameraInfoStats = connection != null
                ? connection.GetLatestPublishStats(SubjectNames.QuestCameraInfo, true)
                : NatsConnection.LatestPublishStats.Empty;
            double stereoProducedFps = _stereoProducedInWindow / Math.Max(elapsed, 1e-6);
            double stereoSentFps = stereoStats.Sent / Math.Max(elapsed, 1e-6);
            int enqueued = _stereoEnqueuedInWindow + _cameraInfoEnqueuedInWindow;
            double avgPayloadKb = enqueued > 0
                ? (_payloadBytesInWindow / 1024.0) / enqueued
                : 0.0;

            Debug.Log(
                $"[EgoAnchorV2] StreamStats stereo produced={_stereoProducedInWindow} ({stereoProducedFps:F1}fps) " +
                $"enqueued={_stereoEnqueuedInWindow} sent={stereoStats.Sent} ({stereoSentFps:F1}fps) overwritten={stereoStats.Overwritten} " +
                $"timeout={stereoStats.TimedOut} failed={stereoStats.Failed} " +
                $"cameraInfo produced/enqueued/sent={_cameraInfoProducedInWindow}/{_cameraInfoEnqueuedInWindow}/{cameraInfoStats.Sent} " +
                $"avgPayload={avgPayloadKb:F1}KB " +
                $"fail conn/cam/play/tex/pose/jpeg/pub=" +
                $"{_failConnectionNull}/{_failCameraNull}/{_failNotPlaying}/{_failTextureNull}/{_failCameraPose}/{_failJpeg}/{_publishFailure}" +
                (string.IsNullOrEmpty(stereoStats.LastError) ? string.Empty : $" lastNetError={stereoStats.LastError}"),
                this);

            _statsWindowStart = now;
            _stereoProducedInWindow = 0;
            _stereoEnqueuedInWindow = 0;
            _cameraInfoProducedInWindow = 0;
            _cameraInfoEnqueuedInWindow = 0;
            _payloadBytesInWindow = 0;
            _failConnectionNull = 0;
            _failCameraNull = 0;
            _failNotPlaying = 0;
            _failTextureNull = 0;
            _failCameraPose = 0;
            _failJpeg = 0;
            _publishFailure = 0;
        }
    }
}

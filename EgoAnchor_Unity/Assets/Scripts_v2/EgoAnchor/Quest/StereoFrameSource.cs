using System;
using EgoAnchor.Protocol.V1;
using Google.Protobuf;
using Meta.XR;
using UnityEngine;

namespace EgoAnchor.V2.Quest
{
    /// <summary>
    /// Quest 双目图像源。
    ///
    /// 本类位于 EgoAnchor.V2.Quest 命名空间，因此类名省略重复的 Quest 前缀；
    /// 输出消息仍是共享协议里的 QuestStereoFrame。
    ///
    /// 职责边界：
    /// - 从左右 PassthroughCameraAccess 读取 texture。
    /// - 在同一采集周期读取左目 camera pose，用于 frame_id 对齐。
    /// - 将左右纹理缩放/读回/JPEG 编码，构造 QuestStereoFrame Protobuf。
    /// - 写入 FramePoseHistory，但不负责 ZMQ socket 或发送节奏。
    /// </summary>
    public sealed class StereoFrameSource : MonoBehaviour
    {
        [Header("Passthrough Cameras")]
        [Tooltip("左目 PassthroughCameraAccess。需要处于 IsPlaying 状态，且用于记录 frame-aligned 左目 camera world pose。")]
        [SerializeField] private PassthroughCameraAccess leftCameraAccess;

        [Tooltip("右目 PassthroughCameraAccess。需要处于 IsPlaying 状态，并与左目同一采集周期读取。")]
        [SerializeField] private PassthroughCameraAccess rightCameraAccess;

        [Tooltip("frame_id -> 采集时刻左目 camera pose 的环形缓存。PoseResult 回来后必须用它做 frame-aligned world anchor。")]
        [SerializeField] private FramePoseHistory framePoseHistory;

        [Header("Encoding")]
        [Tooltip("输出图像相对原始 texture 的缩放比例。降低比例可减小 JPEG 大小和编码耗时，但会影响 mask/depth/pose 精度。")]
        [Range(0.25f, 1f)]
        [SerializeField] private float outputScale = 1f;

        [Tooltip("JPEG 编码质量，范围 30-100。越高图像越清晰但 payload 更大、编码更慢。")]
        [Range(30, 100)]
        [SerializeField] private int jpegQuality = 85;

        private RenderTexture _leftRenderTexture;
        private RenderTexture _rightRenderTexture;
        private Texture2D _leftReadbackTexture;
        private Texture2D _rightReadbackTexture;
        private long _frameId;

        /// <summary>
        /// 尝试采集并编码一帧 stereo Protobuf。
        /// </summary>
        /// <param name="frame">成功时输出可直接序列化发送的 QuestStereoFrame。</param>
        /// <returns>采集、读回和 JPEG 编码是否全部成功。</returns>
        public bool TryCapture(out QuestStereoFrame frame)
        {
            frame = null;
            if (leftCameraAccess == null || rightCameraAccess == null)
            {
                return false;
            }

            if (!leftCameraAccess.IsPlaying || !rightCameraAccess.IsPlaying)
            {
                return false;
            }

            Texture leftTexture = leftCameraAccess.GetTexture();
            Texture rightTexture = rightCameraAccess.GetTexture();
            if (leftTexture == null || rightTexture == null)
            {
                return false;
            }

            Pose leftCameraPose;
            try
            {
                leftCameraPose = leftCameraAccess.GetCameraPose();
            }
            catch (Exception)
            {
                // PCA 在未完全就绪或生命周期切换时可能抛异常。这里让上层统计 captureFailed 即可。
                return false;
            }

            EnsureCaptureBuffers(leftTexture, rightTexture);

            double senderMonoMs = Time.realtimeSinceStartupAsDouble * 1000.0;
            long frameId = ++_frameId;
            int unityFrame = Time.frameCount;

            Graphics.Blit(leftTexture, _leftRenderTexture);
            Graphics.Blit(rightTexture, _rightRenderTexture);

            byte[] leftJpeg = EncodeRenderTextureToJpeg(_leftRenderTexture, _leftReadbackTexture);
            byte[] rightJpeg = EncodeRenderTextureToJpeg(_rightRenderTexture, _rightReadbackTexture);
            if (leftJpeg == null || rightJpeg == null)
            {
                return false;
            }

            // 必须在发送同一 frame_id 时记录采集时刻左目位姿，避免 pose 到达时 HMD 已经移动导致世界锚点漂移。
            framePoseHistory?.Record(frameId, leftCameraPose, senderMonoMs, unityFrame);

            frame = new QuestStereoFrame
            {
                Header = BuildHeader(frameId, unityFrame, senderMonoMs),
                LeftImageJpeg = ByteString.CopyFrom(leftJpeg),
                RightImageJpeg = ByteString.CopyFrom(rightJpeg),
                LeftWidth = _leftRenderTexture.width,
                LeftHeight = _leftRenderTexture.height,
                RightWidth = _rightRenderTexture.width,
                RightHeight = _rightRenderTexture.height,
                JpegQuality = jpegQuality,
            };
            return true;
        }

        /// <summary>
        /// 构造共享消息头。frame_id 是 Unity/Python/Anchor Runtime 之间对齐的主键。
        /// </summary>
        private MessageHeader BuildHeader(long frameId, int unityFrame, double senderMonoMs)
        {
            return new MessageHeader
            {
                MessageId = Guid.NewGuid().ToString("N"),
                FrameId = frameId,
                UnityFrame = unityFrame,
                SenderMonoMs = senderMonoMs,
                CreatedUnixMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                SchemaVersion = "v1",
            };
        }

        /// <summary>
        /// 按当前输入 texture 尺寸和 outputScale 确保 RenderTexture/Texture2D 缓冲可用。
        /// </summary>
        private void EnsureCaptureBuffers(Texture leftTexture, Texture rightTexture)
        {
            int leftWidth = Mathf.Max(1, Mathf.RoundToInt(leftTexture.width * outputScale));
            int leftHeight = Mathf.Max(1, Mathf.RoundToInt(leftTexture.height * outputScale));
            int rightWidth = Mathf.Max(1, Mathf.RoundToInt(rightTexture.width * outputScale));
            int rightHeight = Mathf.Max(1, Mathf.RoundToInt(rightTexture.height * outputScale));

            if (_leftRenderTexture == null || _leftReadbackTexture == null ||
                _leftRenderTexture.width != leftWidth || _leftRenderTexture.height != leftHeight)
            {
                ReleaseBuffer(ref _leftRenderTexture, ref _leftReadbackTexture);
                _leftRenderTexture = new RenderTexture(leftWidth, leftHeight, 0, RenderTextureFormat.ARGB32);
                _leftReadbackTexture = new Texture2D(leftWidth, leftHeight, TextureFormat.RGB24, false);
            }

            if (_rightRenderTexture == null || _rightReadbackTexture == null ||
                _rightRenderTexture.width != rightWidth || _rightRenderTexture.height != rightHeight)
            {
                ReleaseBuffer(ref _rightRenderTexture, ref _rightReadbackTexture);
                _rightRenderTexture = new RenderTexture(rightWidth, rightHeight, 0, RenderTextureFormat.ARGB32);
                _rightReadbackTexture = new Texture2D(rightWidth, rightHeight, TextureFormat.RGB24, false);
            }
        }

        /// <summary>
        /// 将 RenderTexture 同步读回 CPU 并编码为 JPEG。后续若性能不足，可替换为异步 GPU readback。
        /// </summary>
        private byte[] EncodeRenderTextureToJpeg(RenderTexture source, Texture2D readbackTexture)
        {
            RenderTexture previous = RenderTexture.active;
            try
            {
                RenderTexture.active = source;
                readbackTexture.ReadPixels(new Rect(0, 0, source.width, source.height), 0, 0, false);
                readbackTexture.Apply(false, false);
                return readbackTexture.EncodeToJPG(jpegQuality);
            }
            finally
            {
                RenderTexture.active = previous;
            }
        }

        /// <summary>
        /// 释放一组 GPU/CPU 读回缓冲。
        /// </summary>
        private void ReleaseBuffer(ref RenderTexture renderTexture, ref Texture2D readbackTexture)
        {
            if (renderTexture != null)
            {
                renderTexture.Release();
                Destroy(renderTexture);
                renderTexture = null;
            }

            if (readbackTexture != null)
            {
                Destroy(readbackTexture);
                readbackTexture = null;
            }
        }

        private void OnDestroy()
        {
            ReleaseBuffer(ref _leftRenderTexture, ref _leftReadbackTexture);
            ReleaseBuffer(ref _rightRenderTexture, ref _rightReadbackTexture);
        }
    }
}
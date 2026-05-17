using System;
using EgoAnchor.Protocol.V1;
using Google.Protobuf;
using Meta.XR;
using UnityEngine;

namespace EgoAnchor.V2.Quest
{
    /// <summary>
    /// Quest 双目图像采集源。
    ///
    /// 职责边界：
    /// - 从左右 PassthroughCameraAccess 读取 texture。
    /// - 同步读取左目 camera pose，用于 frame_id 对齐。
    /// - JPEG 编码并构造 QuestStereoFrame Protobuf。
    /// - 不负责 ZMQ socket，不负责发送节奏。
    /// </summary>
    public sealed class QuestStereoFrameSource : MonoBehaviour
    {
        [SerializeField] private PassthroughCameraAccess leftCameraAccess;
        [SerializeField] private PassthroughCameraAccess rightCameraAccess;
        [SerializeField] private FramePoseHistory framePoseHistory;

        [Range(0.25f, 1f)]
        [SerializeField] private float outputScale = 1f;
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

        private byte[] EncodeRenderTextureToJpeg(RenderTexture source, Texture2D readbackTexture)
        {
            RenderTexture previous = RenderTexture.active;
            RenderTexture.active = source;
            readbackTexture.ReadPixels(new Rect(0, 0, source.width, source.height), 0, 0, false);
            readbackTexture.Apply(false, false);
            RenderTexture.active = previous;
            return readbackTexture.EncodeToJPG(jpegQuality);
        }

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

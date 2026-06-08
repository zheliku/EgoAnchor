using System;
using EgoAnchor.Alignment;
using EgoAnchor.Protocol.Generated;
using Google.Protobuf;
using Meta.XR;
using UnityEngine;

namespace EgoAnchor.Quest
{
    /// <summary>
    /// Quest 双目图像源。
    ///
    /// 本类只负责读取左右 Passthrough texture、同步记录多参考 camera pose、JPEG 编码并构造 Protobuf。
    /// 它不负责 ZMQ 发送，也不负责发送频率调度。
    /// </summary>
    public sealed class StereoFrameSource : MonoBehaviour
    {
        /// <summary>左目 PassthroughCameraAccess。</summary>
        [Header("Passthrough Cameras")]
        [Tooltip("左目 PassthroughCameraAccess。需要处于 IsPlaying 状态，并用于记录 frame-aligned 左目 camera world pose。")]
        [SerializeField] private PassthroughCameraAccess leftCameraAccess;

        /// <summary>右目 PassthroughCameraAccess。</summary>
        [Tooltip("右目 PassthroughCameraAccess。需要处于 IsPlaying 状态，并与左目同一采集周期读取。")]
        [SerializeField] private PassthroughCameraAccess rightCameraAccess;

        /// <summary>中心参考相机 Transform 覆盖。</summary>
        [Tooltip("可选中心参考 Transform，例如 OVRCameraRig/CenterEyeAnchor。为空时使用左右 Passthrough camera pose 的中点和插值旋转作为 center。")]
        [SerializeField] private Transform centerReferenceOverride;

        /// <summary>frame pose 环形缓存。</summary>
        [Header("Frame Alignment")]
        [Tooltip("frame_id -> 采集时刻 left/right/center camera pose 的环形缓存。后续 PoseResult 回来后必须用它做 frame-aligned world anchor。")]
        [SerializeField] private FramePoseHistory framePoseHistory;

        /// <summary>输出图像缩放比例。</summary>
        [Header("Encoding")]
        [Tooltip("输出图像相对原始 texture 的缩放比例。降低比例可减小 JPEG 大小和编码耗时，但会影响算法输入质量。")]
        [Range(0.25f, 1f)]
        [SerializeField] private float outputScale = 1f;

        /// <summary>JPEG 编码质量。</summary>
        [Tooltip("JPEG 编码质量，范围 30-100。越高图像越清晰但 payload 更大、编码更慢。")]
        [Range(30, 100)]
        [SerializeField] private int jpegQuality = 85;

        /// <summary>左图缩放渲染目标。</summary>
        private RenderTexture leftRenderTexture;

        /// <summary>右图缩放渲染目标。</summary>
        private RenderTexture rightRenderTexture;

        /// <summary>左图 CPU 读回纹理。</summary>
        private Texture2D leftReadbackTexture;

        /// <summary>右图 CPU 读回纹理。</summary>
        private Texture2D rightReadbackTexture;

        /// <summary>单调递增 frame_id。</summary>
        private long frameId;

        /// <summary>采集并记录一帧 frame_id 相机位姿后触发；参数为 (frameId, captureMonoMs)。无订阅者时零成本。</summary>
        public event Action<long, double> FrameCaptured;

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
            Pose rightCameraPose;
            try
            {
                leftCameraPose = leftCameraAccess.GetCameraPose();
                rightCameraPose = rightCameraAccess.GetCameraPose();
            }
            catch (Exception)
            {
                return false;
            }

            Pose centerCameraPose = ResolveCenterCameraPose(leftCameraPose, rightCameraPose);

            EnsureCaptureBuffers(leftTexture, rightTexture);

            double senderMonoMs = Time.realtimeSinceStartupAsDouble * 1000.0;
            long currentFrameId = ++frameId;
            int unityFrame = Time.frameCount;

            Graphics.Blit(leftTexture, leftRenderTexture);
            Graphics.Blit(rightTexture, rightRenderTexture);

            byte[] leftJpeg = EncodeRenderTextureToJpeg(leftRenderTexture, leftReadbackTexture);
            byte[] rightJpeg = EncodeRenderTextureToJpeg(rightRenderTexture, rightReadbackTexture);
            if (leftJpeg == null || rightJpeg == null)
            {
                return false;
            }

            framePoseHistory?.Record(currentFrameId, leftCameraPose, rightCameraPose, centerCameraPose, senderMonoMs, unityFrame);
            FrameCaptured?.Invoke(currentFrameId, senderMonoMs);

            frame = new QuestStereoFrame
            {
                Header = QuestStreamSession.BuildHeader(currentFrameId, unityFrame, senderMonoMs),
                LeftImageJpeg = ByteString.CopyFrom(leftJpeg),
                RightImageJpeg = ByteString.CopyFrom(rightJpeg),
                LeftWidth = leftRenderTexture.width,
                LeftHeight = leftRenderTexture.height,
                RightWidth = rightRenderTexture.width,
                RightHeight = rightRenderTexture.height,
                JpegQuality = jpegQuality
            };
            return true;
        }

        /// <summary>
        /// 计算中心参考相机 pose。
        ///
        /// 如果用户显式指定 CenterEyeAnchor 或其它稳定 Transform，则使用该 Transform 的采集时刻 world pose；
        /// 否则使用左右 Passthrough camera pose 的中点和球面插值旋转，得到一个不依赖渲染眼相机启用状态的中心参考。
        /// </summary>
        /// <param name="leftCameraPose">采集时刻左目 Passthrough camera world pose。</param>
        /// <param name="rightCameraPose">采集时刻右目 Passthrough camera world pose。</param>
        /// <returns>中心参考 camera world pose。</returns>
        private Pose ResolveCenterCameraPose(Pose leftCameraPose, Pose rightCameraPose)
        {
            if (centerReferenceOverride != null)
            {
                return new Pose(centerReferenceOverride.position, centerReferenceOverride.rotation);
            }

            return new Pose(
                Vector3.Lerp(leftCameraPose.position, rightCameraPose.position, 0.5f),
                Quaternion.Slerp(leftCameraPose.rotation, rightCameraPose.rotation, 0.5f)
            );
        }

        /// <summary>
        /// 确保读回缓冲与当前输入 texture 尺寸匹配。
        /// </summary>
        private void EnsureCaptureBuffers(Texture leftTexture, Texture rightTexture)
        {
            int leftWidth = Mathf.Max(1, Mathf.RoundToInt(leftTexture.width * outputScale));
            int leftHeight = Mathf.Max(1, Mathf.RoundToInt(leftTexture.height * outputScale));
            int rightWidth = Mathf.Max(1, Mathf.RoundToInt(rightTexture.width * outputScale));
            int rightHeight = Mathf.Max(1, Mathf.RoundToInt(rightTexture.height * outputScale));

            if (leftRenderTexture == null || leftReadbackTexture == null || leftRenderTexture.width != leftWidth || leftRenderTexture.height != leftHeight)
            {
                ReleaseBuffer(ref leftRenderTexture, ref leftReadbackTexture);
                leftRenderTexture = new RenderTexture(leftWidth, leftHeight, 0, RenderTextureFormat.ARGB32);
                leftReadbackTexture = new Texture2D(leftWidth, leftHeight, TextureFormat.RGB24, false);
            }

            if (rightRenderTexture == null || rightReadbackTexture == null || rightRenderTexture.width != rightWidth || rightRenderTexture.height != rightHeight)
            {
                ReleaseBuffer(ref rightRenderTexture, ref rightReadbackTexture);
                rightRenderTexture = new RenderTexture(rightWidth, rightHeight, 0, RenderTextureFormat.ARGB32);
                rightReadbackTexture = new Texture2D(rightWidth, rightHeight, TextureFormat.RGB24, false);
            }
        }

        /// <summary>
        /// 同步读回 RenderTexture 并编码为 JPEG。
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

        /// <summary>
        /// Unity 销毁组件时释放图像缓冲。
        /// </summary>
        private void OnDestroy()
        {
            ReleaseBuffer(ref leftRenderTexture, ref leftReadbackTexture);
            ReleaseBuffer(ref rightRenderTexture, ref rightReadbackTexture);
        }
    }

}

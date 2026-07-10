using System;
using EgoAnchor.Alignment;
using EgoAnchor.Diagnostics;
using EgoAnchor.Protocol.Generated;
using Google.Protobuf;
using Meta.XR;
using UnityEngine;

namespace EgoAnchor.Quest
{
    /// <summary>
    /// 一次成功双目采集的图像时间代理与 payload-ready 时间。
    /// 图像时间来自延迟 camera pose 样本，不是硬件曝光时间戳。
    /// </summary>
    public readonly struct FrameCaptureTiming
    {
        /// <summary>与协议 Header 完全一致的 frame_id。</summary>
        public readonly long FrameId;

        /// <summary>图像时间代理对应的 Unity 单调时钟毫秒。</summary>
        public readonly double ImageMonoMs;

        /// <summary>图像时间代理对应的 Unity 帧号。</summary>
        public readonly int ImageUnityFrame;

        /// <summary>JPEG 编码完成后的 payload-ready 单调时钟毫秒。</summary>
        public readonly double SenderMonoMs;

        /// <summary>payload-ready 时的 Unity 帧号。</summary>
        public readonly int SenderUnityFrame;

        /// <summary>图像时间代理相对当前 payload-ready 帧回退的成功采集样本数。</summary>
        public readonly int ImageTimeOffsetFrames;

        /// <summary>构造一条采集双时间通知。</summary>
        public FrameCaptureTiming(
            long frameId,
            double imageMonoMs,
            int imageUnityFrame,
            double senderMonoMs,
            int senderUnityFrame,
            int imageTimeOffsetFrames)
        {
            FrameId = frameId;
            ImageMonoMs = imageMonoMs;
            ImageUnityFrame = imageUnityFrame;
            SenderMonoMs = senderMonoMs;
            SenderUnityFrame = senderUnityFrame;
            ImageTimeOffsetFrames = imageTimeOffsetFrames;
        }
    }

    /// <summary>
    /// Quest 双目图像源。
    ///
    /// 本类只负责读取左右 Passthrough texture、同步记录多参考 camera pose、JPEG 编码并构造 Protobuf。
    /// 它不负责 ZMQ 发送，也不负责发送频率调度。
    /// </summary>
    public sealed class StereoFrameSource : MonoBehaviour
    {
        /// <summary>统一日志通道。</summary>
        private static readonly EgoAnchorLog.Channel Log = EgoAnchorLog.For<StereoFrameSource>();

        /// <summary>高频采集失败的日志限频间隔。</summary>
        private const int FailureLogInterval = 120;

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
        [Tooltip("frame_id -> image-time proxy left/right/center camera pose 的环形缓存。PoseResult 返回后用它做 frame-aligned world anchor。")]
        [SerializeField] private FramePoseHistory framePoseHistory;

        /// <summary>用于 frame alignment 的相机 pose 回退帧数。</summary>
        [Tooltip("用于 frame alignment 的相机 pose 回退帧数。当前无硬件曝光时间戳，默认以回退 1 个成功采集样本作为 image-time proxy；正式评估需做 0/1/2 帧敏感性分析。")]
        [Min(0)]
        [SerializeField] private int cameraPoseDelayFrames = 1;

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

        /// <summary>读取 Passthrough camera pose 失败次数。</summary>
        private int cameraPoseFailures;

        /// <summary>图像读回或 JPEG 编码失败次数。</summary>
        private int imageEncodeFailures;

        /// <summary>用于补偿 passthrough 图像与当前相机 pose 时间差的短历史缓冲。</summary>
        private readonly FramePoseDelayBuffer framePoseDelayBuffer = new FramePoseDelayBuffer();

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
            catch (Exception exc)
            {
                cameraPoseFailures++;
                LogCaptureFailure("camera_pose", cameraPoseFailures, exc);
                return false;
            }

            Pose centerCameraPose = ResolveCenterCameraPose(leftCameraPose, rightCameraPose);

            double poseSampleMonoMs = Time.realtimeSinceStartupAsDouble * 1000.0;
            long currentFrameId = ++frameId;
            int unityFrame = Time.frameCount;
            FramePoseSample currentPoseSample = new FramePoseSample(
                leftCameraPose,
                rightCameraPose,
                centerCameraPose,
                poseSampleMonoMs,
                unityFrame);

            byte[] leftJpeg;
            byte[] rightJpeg;
            try
            {
                EnsureCaptureBuffers(leftTexture, rightTexture);
                Graphics.Blit(leftTexture, leftRenderTexture);
                Graphics.Blit(rightTexture, rightRenderTexture);
                leftJpeg = EncodeRenderTextureToJpeg(leftRenderTexture, leftReadbackTexture);
                rightJpeg = EncodeRenderTextureToJpeg(rightRenderTexture, rightReadbackTexture);
            }
            catch (Exception exc)
            {
                imageEncodeFailures++;
                LogCaptureFailure("image_encode", imageEncodeFailures, exc);
                return false;
            }

            if (leftJpeg == null || rightJpeg == null)
            {
                imageEncodeFailures++;
                LogCaptureFailure("image_encode_empty", imageEncodeFailures, null);
                return false;
            }

            int imageTimeOffsetFrames = Mathf.Max(0, cameraPoseDelayFrames);
            FramePoseSample alignmentPoseSample = framePoseDelayBuffer.Select(currentPoseSample, imageTimeOffsetFrames);
            double senderMonoMs = Time.realtimeSinceStartupAsDouble * 1000.0;
            int senderUnityFrame = Time.frameCount;
            framePoseHistory?.Record(
                currentFrameId,
                alignmentPoseSample.LeftCameraPose,
                alignmentPoseSample.RightCameraPose,
                alignmentPoseSample.CenterCameraPose,
                alignmentPoseSample.MonoMs,
                alignmentPoseSample.UnityFrame,
                imageTimeOffsetFrames,
                senderMonoMs,
                senderUnityFrame);
            frame = new QuestStereoFrame
            {
                Header = QuestStreamSession.BuildHeader(currentFrameId, senderUnityFrame, senderMonoMs),
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

        /// <summary>按 frame_id 读取刚完成采集的图像代理与 payload-ready 时间。</summary>
        /// <param name="frameId">协议 frame_id。</param>
        /// <param name="timing">命中时返回双时间信息。</param>
        /// <returns>该 frame_id 是否仍在历史缓存中。</returns>
        public bool TryGetCaptureTiming(long frameId, out FrameCaptureTiming timing)
        {
            timing = default;
            if (framePoseHistory == null || !framePoseHistory.TryGet(frameId, out FramePoseRecord record))
            {
                return false;
            }

            timing = new FrameCaptureTiming(
                frameId,
                record.ImageMonoMs,
                record.ImageUnityFrame,
                record.SenderMonoMs,
                record.SenderUnityFrame,
                record.ImageTimeOffsetFrames);
            return true;
        }

        /// <summary>
        /// 限频输出采集失败日志，保留真机排查线索但避免每帧刷屏。
        /// </summary>
        private void LogCaptureFailure(string stage, int count, Exception exc)
        {
            if (count <= 3 || count % FailureLogInterval == 0)
            {
                string detail = exc == null ? "empty result" : exc.Message;
                Log.Warning($"capture failed stage={stage}, count={count}, reason={detail}", this);
            }
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

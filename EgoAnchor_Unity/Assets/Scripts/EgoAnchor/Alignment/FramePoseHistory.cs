using System.Collections.Generic;
using UnityEngine;

namespace EgoAnchor.Alignment
{
    /// <summary>
    /// frame_id -> 图像时间代理对应的多参考相机 world pose 环形缓存。
    ///
    /// 当前通信 demo 主要验证图像链路，但仍在采集事务中记录 pose，
    /// 因为后续 frame-aligned anchor runtime 必须使用经标定回退得到的参考 camera pose，
    /// 不能使用 pose 结果到达时的 HMD pose。
    /// </summary>
    public sealed class FramePoseHistory : MonoBehaviour
    {
        /// <summary>缓存容量；容量太小会导致低帧率 pose 回来时查不到历史帧。</summary>
        [Tooltip("frame_id -> left/right/center camera pose 环形缓存容量。后续 pose-to-anchor 对齐必须依赖该缓存。")]
        [Min(8)]
        [SerializeField] private int capacity = 512;

        /// <summary>frame_id 到记录的映射。</summary>
        private readonly Dictionary<long, FramePoseRecord> records = new Dictionary<long, FramePoseRecord>();

        /// <summary>按写入顺序保存 frame_id，用于淘汰最旧记录。</summary>
        private readonly Queue<long> order = new Queue<long>();

        /// <summary>最近一次写入的 frame_id，用于 arrival-time raw 诊断。</summary>
        private long latestFrameId = -1;

        /// <summary>累计写入次数。</summary>
        public int RecordedCount { get; private set; }

        /// <summary>当前缓存中的记录数量。</summary>
        public int Count => records.Count;

        /// <summary>
        /// 记录一帧图像时间代理的多参考相机 world pose，并保存 payload-ready 时刻。
        /// </summary>
        /// <param name="frameId">与 QuestStereoFrame.header.frame_id 完全一致的帧号。</param>
        /// <param name="leftCameraPose">图像时间代理对应的左目 camera world pose。</param>
        /// <param name="rightCameraPose">图像时间代理对应的右目 camera world pose。</param>
        /// <param name="centerCameraPose">图像时间代理对应的中心参考 camera world pose。</param>
        /// <param name="imageMonoMs">图像对应的 Unity 单调时钟毫秒。</param>
        /// <param name="imageUnityFrame">图像对应的 Unity 帧号。</param>
        /// <param name="imageTimeOffsetFrames">图像时间代理相对当前样本回退的成功采集样本数。</param>
        /// <param name="senderMonoMs">JPEG 编码完成后的 payload-ready 单调时钟毫秒。</param>
        /// <param name="senderUnityFrame">payload-ready 时的 Unity 帧号。</param>
        public void Record(
            long frameId,
            Pose leftCameraPose,
            Pose rightCameraPose,
            Pose centerCameraPose,
            double imageMonoMs,
            int imageUnityFrame,
            int imageTimeOffsetFrames,
            double senderMonoMs,
            int senderUnityFrame)
        {
            FramePoseRecord record = new FramePoseRecord(
                frameId,
                leftCameraPose,
                rightCameraPose,
                centerCameraPose,
                imageMonoMs,
                imageUnityFrame,
                imageTimeOffsetFrames,
                senderMonoMs,
                senderUnityFrame);
            latestFrameId = frameId;
            if (records.ContainsKey(frameId))
            {
                records[frameId] = record;
                return;
            }

            records.Add(frameId, record);
            order.Enqueue(frameId);
            RecordedCount++;

            while (records.Count > Mathf.Max(8, capacity) && order.Count > 0)
            {
                long oldest = order.Dequeue();
                records.Remove(oldest);
            }
        }

        /// <summary>
        /// 尝试按 frame_id 查询历史 camera pose。
        /// </summary>
        /// <param name="frameId">待查询的帧号。</param>
        /// <param name="record">命中时输出记录。</param>
        /// <returns>是否命中缓存。</returns>
        public bool TryGet(long frameId, out FramePoseRecord record)
        {
            return records.TryGetValue(frameId, out record);
        }

        /// <summary>
        /// 尝试读取最近一次记录的 camera pose。
        /// 仅用于 arrival-time raw 对照诊断；正式 anchor 仍必须按 source frame_id 回查 image-time proxy pose。
        /// </summary>
        /// <param name="record">命中时输出最近记录。</param>
        /// <returns>是否存在可用记录。</returns>
        public bool TryGetLatest(out FramePoseRecord record)
        {
            record = default;
            return latestFrameId >= 0 && records.TryGetValue(latestFrameId, out record);
        }

        /// <summary>
        /// 清空历史记录；后续 reset/reacquire 时可调用。
        /// </summary>
        public void Clear()
        {
            records.Clear();
            order.Clear();
            latestFrameId = -1;
        }
    }

    /// <summary>
    /// 单帧图像时间代理 camera pose 与 payload-ready 时刻记录。
    /// </summary>
    public readonly struct FramePoseRecord
    {
        /// <summary>帧号。</summary>
        public readonly long FrameId;

        /// <summary>图像时间代理对应的左目 camera world pose。</summary>
        public readonly Pose LeftCameraPose;

        /// <summary>图像时间代理对应的右目 camera world pose。</summary>
        public readonly Pose RightCameraPose;

        /// <summary>图像时间代理对应的中心参考 camera world pose。</summary>
        public readonly Pose CenterCameraPose;

        /// <summary>图像时间代理对应的 Unity 单调时钟毫秒。</summary>
        public readonly double ImageMonoMs;

        /// <summary>图像时间代理对应的 Unity 帧号。</summary>
        public readonly int ImageUnityFrame;

        /// <summary>图像时间代理相对当前样本回退的成功采集样本数。</summary>
        public readonly int ImageTimeOffsetFrames;

        /// <summary>JPEG 编码完成后的 payload-ready 单调时钟毫秒。</summary>
        public readonly double SenderMonoMs;

        /// <summary>payload-ready 时的 Unity 帧号。</summary>
        public readonly int SenderUnityFrame;

        /// <summary>构造一条多参考 frame pose 记录。</summary>
        public FramePoseRecord(
            long frameId,
            Pose leftCameraPose,
            Pose rightCameraPose,
            Pose centerCameraPose,
            double imageMonoMs,
            int imageUnityFrame,
            int imageTimeOffsetFrames,
            double senderMonoMs,
            int senderUnityFrame)
        {
            FrameId = frameId;
            LeftCameraPose = leftCameraPose;
            RightCameraPose = rightCameraPose;
            CenterCameraPose = centerCameraPose;
            ImageMonoMs = imageMonoMs;
            ImageUnityFrame = imageUnityFrame;
            ImageTimeOffsetFrames = imageTimeOffsetFrames;
            SenderMonoMs = senderMonoMs;
            SenderUnityFrame = senderUnityFrame;
        }

        /// <summary>
        /// 按参考相机读取本帧缓存的 world pose。
        /// </summary>
        /// <param name="reference">目标参考相机。</param>
        /// <param name="cameraPose">成功时输出对应参考相机在图像时间代理处的 world pose。</param>
        /// <returns>参考相机是否需要且能够返回 world pose。</returns>
        public bool TryGetCameraPose(CameraReference reference, out Pose cameraPose)
        {
            switch (reference)
            {
                case CameraReference.None:
                    cameraPose = Pose.identity;
                    return false;
                case CameraReference.Right:
                    cameraPose = RightCameraPose;
                    return true;
                case CameraReference.Center:
                    cameraPose = CenterCameraPose;
                    return true;
                case CameraReference.Left:
                default:
                    cameraPose = LeftCameraPose;
                    return true;
            }
        }
    }

    /// <summary>
    /// 一次待写入 frame history 的多参考相机 pose 采样。
    /// </summary>
    public readonly struct FramePoseSample
    {
        /// <summary>采样时刻左目 camera world pose。</summary>
        public readonly Pose LeftCameraPose;

        /// <summary>采样时刻右目 camera world pose。</summary>
        public readonly Pose RightCameraPose;

        /// <summary>采样时刻中心参考 camera world pose。</summary>
        public readonly Pose CenterCameraPose;

        /// <summary>采样时刻 Unity 单调时钟毫秒。</summary>
        public readonly double MonoMs;

        /// <summary>采样时刻 Unity 帧号。</summary>
        public readonly int UnityFrame;

        /// <summary>
        /// 构造相机 pose 采样。
        /// </summary>
        public FramePoseSample(
            Pose leftCameraPose,
            Pose rightCameraPose,
            Pose centerCameraPose,
            double monoMs,
            int unityFrame)
        {
            LeftCameraPose = leftCameraPose;
            RightCameraPose = rightCameraPose;
            CenterCameraPose = centerCameraPose;
            MonoMs = monoMs;
            UnityFrame = unityFrame;
        }
    }

    /// <summary>
    /// 采集端相机 pose 延迟缓冲。
    ///
    /// Quest Passthrough texture 与当前 Unity camera pose 可能存在时间偏移；本缓冲让
    /// StereoFrameSource 可以把当前图像 frame_id 绑定到更早的 camera pose，减少快速头动时
    /// 静止物体跟随头显漂移。偏移量以成功采集样本数表达，不假定固定物理时长。
    /// 该类不依赖 MonoBehaviour，便于 smoke 直接验证。
    /// </summary>
    public sealed class FramePoseDelayBuffer
    {
        /// <summary>按采样顺序保存最近的相机 pose。</summary>
        private readonly Queue<FramePoseSample> samples = new Queue<FramePoseSample>();

        /// <summary>
        /// 按延迟帧数选择用于当前图像 frame_id 的相机 pose。
        /// </summary>
        /// <param name="current">当前 Unity tick 读到的相机 pose。</param>
        /// <param name="delayFrames">希望回退的成功采集帧数；0 表示直接使用当前 pose。</param>
        /// <returns>用于 frame alignment 的相机 pose 采样。</returns>
        public FramePoseSample Select(FramePoseSample current, int delayFrames)
        {
            if (delayFrames <= 0)
            {
                Clear();
                return current;
            }

            samples.Enqueue(current);
            while (samples.Count > delayFrames + 1)
            {
                samples.Dequeue();
            }

            return samples.Count > delayFrames ? samples.Dequeue() : current;
        }

        /// <summary>
        /// 清空延迟缓冲，避免相机暂停或配置切换后复用过旧 pose。
        /// </summary>
        public void Clear()
        {
            samples.Clear();
        }
    }
}

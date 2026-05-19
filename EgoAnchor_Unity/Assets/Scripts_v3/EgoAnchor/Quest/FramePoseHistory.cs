using System.Collections.Generic;
using UnityEngine;

namespace EgoAnchor.V3.Quest
{
    /// <summary>
    /// frame_id -> 采集时刻左目 camera world pose 的环形缓存。
    ///
    /// 当前通信 demo 主要验证图像链路，但仍在采集事务中记录 pose，
    /// 因为后续 frame-aligned anchor runtime 必须用发送帧时的 camera pose，
    /// 不能使用 pose 结果到达时的 HMD pose。
    /// </summary>
    public sealed class FramePoseHistory : MonoBehaviour
    {
        /// <summary>缓存容量；容量太小会导致低帧率 pose 回来时查不到历史帧。</summary>
        [Tooltip("frame_id -> camera pose 环形缓存容量。后续 pose-to-anchor 对齐必须依赖该缓存。")]
        [Min(8)]
        [SerializeField] private int capacity = 512;

        /// <summary>frame_id 到记录的映射。</summary>
        private readonly Dictionary<long, FramePoseRecord> records = new Dictionary<long, FramePoseRecord>();

        /// <summary>按写入顺序保存 frame_id，用于淘汰最旧记录。</summary>
        private readonly Queue<long> order = new Queue<long>();

        /// <summary>累计写入次数。</summary>
        public int RecordedCount { get; private set; }

        /// <summary>当前缓存中的记录数量。</summary>
        public int Count => records.Count;

        /// <summary>
        /// 记录一帧采集时刻的左目 camera world pose。
        /// </summary>
        /// <param name="frameId">与 QuestStereoFrame.header.frame_id 完全一致的帧号。</param>
        /// <param name="cameraPose">采集时刻左目 camera world pose。</param>
        /// <param name="senderMonoMs">Unity 发送侧单调时钟毫秒。</param>
        /// <param name="unityFrame">Unity Time.frameCount。</param>
        public void Record(long frameId, Pose cameraPose, double senderMonoMs, int unityFrame)
        {
            if (records.ContainsKey(frameId))
            {
                records[frameId] = new FramePoseRecord(frameId, cameraPose, senderMonoMs, unityFrame);
                return;
            }

            records.Add(frameId, new FramePoseRecord(frameId, cameraPose, senderMonoMs, unityFrame));
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
        /// 清空历史记录；后续 reset/reacquire 时可调用。
        /// </summary>
        public void Clear()
        {
            records.Clear();
            order.Clear();
        }
    }

    /// <summary>
    /// 单帧采集时刻 camera pose 记录。
    /// </summary>
    public readonly struct FramePoseRecord
    {
        /// <summary>帧号。</summary>
        public readonly long FrameId;

        /// <summary>采集时刻左目 camera world pose。</summary>
        public readonly Pose CameraPose;

        /// <summary>Unity 发送侧单调时钟毫秒。</summary>
        public readonly double SenderMonoMs;

        /// <summary>Unity 帧号。</summary>
        public readonly int UnityFrame;

        /// <summary>构造一条 frame pose 记录。</summary>
        public FramePoseRecord(long frameId, Pose cameraPose, double senderMonoMs, int unityFrame)
        {
            FrameId = frameId;
            CameraPose = cameraPose;
            SenderMonoMs = senderMonoMs;
            UnityFrame = unityFrame;
        }
    }
}
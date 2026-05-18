using System;
using UnityEngine;

namespace EgoAnchor.V2.Quest
{
    /// <summary>
    /// frame_id -> capture-time camera pose 的环形缓存。
    ///
    /// 这是 v2 Pose-to-Anchor 的关键模块：
    /// Python 返回的是相机坐标系 pose，Unity 必须用“采集该帧时”的左目相机 world pose，
    /// 而不是 pose 到达时的 HMD pose，才能得到 frame-aligned world anchor。
    /// </summary>
    public sealed class FramePoseHistory : MonoBehaviour
    {
        [Tooltip("缓存最近多少帧的采集时刻 camera pose。容量需覆盖 Python 推理延迟对应的帧数；过小会导致 PoseResult 回来时查不到 frame_id。")]
        [Min(8)]
        [SerializeField] private int capacity = 512;

        private Entry[] _entries;
        private int _writeIndex;

        /// <summary>
        /// 单帧采集记录。所有字段都描述 Unity 发送该 frame_id 时的状态。
        /// </summary>
        [Serializable]
        public struct Entry
        {
            /// <summary>与 QuestStereoFrame.Header.FrameId 对应的递增帧号。</summary>
            public long FrameId;

            /// <summary>采集该帧时左目 camera 的 Unity world pose。</summary>
            public Pose CameraPose;

            /// <summary>Unity 发送端单调时钟毫秒，用于估计端到端延迟和调试，不等价于跨设备真实时钟。</summary>
            public double SenderMonoMs;

            /// <summary>采集该帧时的 Unity Time.frameCount。</summary>
            public int UnityFrame;

            /// <summary>该 ring buffer 槽位是否已经写入有效记录。</summary>
            public bool Valid;
        }

        private void Awake()
        {
            EnsureBuffer();
        }

        /// <summary>
        /// 记录一帧发送时刻的左目相机 world pose。
        /// </summary>
        public void Record(long frameId, Pose cameraPose, double senderMonoMs, int unityFrame)
        {
            EnsureBuffer();
            _entries[_writeIndex] = new Entry
            {
                FrameId = frameId,
                CameraPose = cameraPose,
                SenderMonoMs = senderMonoMs,
                UnityFrame = unityFrame,
                Valid = true,
            };
            _writeIndex = (_writeIndex + 1) % _entries.Length;
        }

        /// <summary>
        /// 查找指定 frame_id 的相机 pose。
        ///
        /// 当前容量很小，线性扫描足够简单可靠；若后续容量显著增大或查询频率升高，
        /// 可改成 Dictionary + ring eviction，但仍需保持 frame_id 精确匹配语义。
        /// </summary>
        public bool TryGet(long frameId, out Entry entry)
        {
            EnsureBuffer();
            for (int i = 0; i < _entries.Length; i++)
            {
                Entry candidate = _entries[i];
                if (candidate.Valid && candidate.FrameId == frameId)
                {
                    entry = candidate;
                    return true;
                }
            }

            entry = default;
            return false;
        }

        private void EnsureBuffer()
        {
            int safeCapacity = Mathf.Max(8, capacity);
            if (_entries == null || _entries.Length != safeCapacity)
            {
                _entries = new Entry[safeCapacity];
                _writeIndex = 0;
            }
        }
    }
}

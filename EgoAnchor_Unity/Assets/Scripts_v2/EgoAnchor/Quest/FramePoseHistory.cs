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
        [SerializeField] private int capacity = 512;

        private Entry[] _entries;
        private int _writeIndex;

        [Serializable]
        public struct Entry
        {
            public long FrameId;
            public Pose CameraPose;
            public double SenderMonoMs;
            public int UnityFrame;
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

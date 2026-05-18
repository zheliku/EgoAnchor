using UnityEngine;

namespace EgoAnchor.V2.Anchor
{
    /// <summary>
    /// camera-space pose -> Unity world anchor pose 的 frame-aligned 转换器占位。
    ///
    /// 后续将从 Quest.FramePoseHistory 中按 frame_id 查找“采集该帧时”的左目 camera world pose，
    /// 再把 Python 输出的 OpenCV camera pose（x 右、y 下、z 前）转换为 Unity camera-local pose（x 右、y 上、z 前），
    /// 最后映射到 Unity world raw anchor pose。
    ///
    /// 这相当于把旧链路中的 PoseDecoder + FrameAlignedObjectAnchor 的关键逻辑正式拆分出来，
    /// 是 v2 frame-aligned real-object anchoring 的核心模块。
    /// </summary>
    public sealed class CameraPoseFrameAligner
    {
        /// <summary>
        /// 按 frame_id 对齐并输出 world pose。
        /// 当前仍是骨架实现；后续需要接入 FramePoseHistory 和 OpenCV->Unity 坐标转换。
        /// </summary>
        public bool TryAlign(long frameId, out Pose worldPose)
        {
            worldPose = default;
            return false;
        }
    }
}

using UnityEngine;

namespace EgoAnchor.V2.Anchor
{
    /// <summary>
    /// camera-space pose -> Unity world anchor pose 的 frame-aligned 转换器占位。
    ///
    /// 后续将从 FramePoseHistory 中按 frame_id 查找采集时刻左目 camera pose，
    /// 再把 Python 输出的 OpenCV camera pose 转为 Unity world raw anchor pose。
    /// </summary>
    public sealed class CameraPoseFrameAligner
    {
        public bool TryAlign(long frameId, out Pose worldPose)
        {
            worldPose = default;
            return false;
        }
    }
}

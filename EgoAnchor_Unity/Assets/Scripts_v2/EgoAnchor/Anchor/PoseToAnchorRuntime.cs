using UnityEngine;

namespace EgoAnchor.V2.Anchor
{
    /// <summary>
    /// v2 Pose-to-Anchor runtime 占位。
    ///
    /// 后续职责：
    /// - 接收 PoseResult observation。
    /// - 调用 CameraPoseFrameAligner 得到 raw world anchor pose。
    /// - 交给 reliability gate / filter / state machine。
    /// - 输出稳定 dynamic anchor pose。
    /// </summary>
    public sealed class PoseToAnchorRuntime
    {
        public bool TryGetStablePose(out Pose pose)
        {
            pose = default;
            return false;
        }
    }
}

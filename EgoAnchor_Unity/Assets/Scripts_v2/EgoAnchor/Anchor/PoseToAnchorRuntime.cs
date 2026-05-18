using UnityEngine;

namespace EgoAnchor.V2.Anchor
{
    /// <summary>
    /// v2 Pose-to-Anchor runtime 占位。
    ///
    /// 这是 Unity v2 Anchor Runtime 的核心组合点：它接收 Python 返回的相机坐标系 pose observation，
    /// 调用 frame aligner 得到 raw world pose，再进入 reliability gate / filter / state machine，
    /// 最终输出可应用到 Transform 的稳定 world anchor pose。
    ///
    /// 注意：本类不负责网络订阅、不解码 Protobuf、不直接读 Quest camera；这些输入应由 Client/Quest 层提供。
    ///
    /// 后续职责：
    /// - 接收 PoseResult observation。
    /// - 调用 CameraPoseFrameAligner 得到 raw world anchor pose。
    /// - 交给 reliability gate / filter / state machine。
    /// - 输出稳定 dynamic anchor pose。
    /// </summary>
    public sealed class PoseToAnchorRuntime
    {
        /// <summary>
        /// 尝试获取当前稳定 anchor pose。
        /// 当前仍是骨架实现，后续由滤波器/预测器/状态机维护稳定输出。
        /// </summary>
        public bool TryGetStablePose(out Pose pose)
        {
            pose = default;
            return false;
        }
    }
}

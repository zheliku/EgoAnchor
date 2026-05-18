using UnityEngine;

namespace EgoAnchor.V2.Client
{
    /// <summary>
    /// v2 PoseResult 接收器占位。
    ///
    /// 本类属于 Client 层：后续负责把 NATS control plane 收到的 PoseResult 转成 Unity 主线程事件，
    /// 再交给 Anchor/PoseToAnchorRuntime。它不应直接修改场景 Transform，也不应自己持有滤波/状态机。
    ///
    /// 后续职责：
    /// - 通过 NATS 订阅 egoanchor.v1.pose.result。
    /// - 解码 Protobuf PoseResult。
    /// - 在 Unity 主线程把 pose observation 交给 PoseToAnchorRuntime。
    /// - has_pose=false 时不应用 transform，但仍应把状态/失败原因交给 anchor runtime。
    ///
    /// 当前视频流 demo 不启用该组件，避免把数据面验证和 anchor runtime 混在一起。
    /// </summary>
    public sealed class PoseResultReceiver : MonoBehaviour
    {
    }
}

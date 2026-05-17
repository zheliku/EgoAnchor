using UnityEngine;

namespace EgoAnchor.V2.Client
{
    /// <summary>
    /// v2 PoseResult 接收器占位。
    ///
    /// 后续职责：
    /// - 通过 NATS 订阅 egoanchor.v1.pose.result。
    /// - 解码 Protobuf PoseResult。
    /// - 在 Unity 主线程把 pose observation 交给 PoseToAnchorRuntime。
    ///
    /// 当前视频流 demo 不启用该组件，避免把数据面验证和 anchor runtime 混在一起。
    /// </summary>
    public sealed class PoseResultReceiver : MonoBehaviour
    {
    }
}

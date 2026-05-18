using UnityEngine;

namespace EgoAnchor.V2.Anchor
{
    /// <summary>
    /// v2 dynamic object anchor Transform 应用组件占位。
    ///
    /// 该组件将是场景中真正移动/稳定虚拟物体的 MonoBehaviour。职责应保持非常薄：
    /// - 从 PoseToAnchorRuntime 读取稳定 world pose。
    /// - 把 pose 应用到当前 Transform 或指定目标 Transform。
    /// - 暴露交互系统需要的挂载点。
    ///
    /// 当前不订阅网络、不解码 Protobuf；后续也不应把 NATS/ZMQ 逻辑写进这里。
    /// </summary>
    public sealed class DynamicObjectAnchor : MonoBehaviour
    {
    }
}

using UnityEngine;

namespace EgoAnchor.V2.Anchor
{
    /// <summary>
    /// v2 dynamic object anchor Transform 应用组件占位。
    ///
    /// 当前不订阅网络、不解码 Protobuf；后续只接收 PoseToAnchorRuntime 的稳定输出并应用到 Transform。
    /// </summary>
    public sealed class DynamicObjectAnchor : MonoBehaviour
    {
    }
}

using EgoAnchor.V2.Transport;
using UnityEngine;

namespace EgoAnchor.V2.Client
{
    /// <summary>
    /// v2 Unity 侧聚合组件。
    ///
    /// 它本身不发消息、不收消息，只把场景中常用的 v2 组件引用集中起来，方便
    /// UI、调试脚本或 prefab 对外暴露一个统一入口。
    ///
    /// 具体职责仍然拆在独立组件中：
    /// - NatsConnection：连接和 bytes 传输；
    /// - AnchorControlApi：命令 request/reply；
    /// - PoseResultReceiver：pose result 订阅；
    /// - AnchorStatusReceiver：状态事件订阅。
    /// </summary>
    public class EgoAnchorClient : MonoBehaviour
    {
        [SerializeField] private NatsConnection connection;
        [SerializeField] private AnchorControlApi controlApi;
        [SerializeField] private PoseResultReceiver poseResultReceiver;
        [SerializeField] private AnchorStatusReceiver anchorStatusReceiver;

        public NatsConnection Connection => connection;
        public AnchorControlApi ControlApi => controlApi;
        public PoseResultReceiver PoseResultReceiver => poseResultReceiver;
        public AnchorStatusReceiver AnchorStatusReceiver => anchorStatusReceiver;
    }
}

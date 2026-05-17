using UnityEngine;

namespace EgoAnchor.V2.Transport
{
    /// <summary>
    /// v2 NATS 控制面占位组件。
    ///
    /// 当前 Quest -> Python 视频流 demo 不启用 NATS。
    /// 后续本类负责：
    /// - 连接 NATS。
    /// - 订阅 PoseResult / AnchorStatus / ServerHeartbeat。
    /// - 发送 Reset/Reacquire/Control request 并处理 CommandAck。
    ///
    /// 注意：NATS handler 不应直接修改 Transform，也不应直接运行复杂状态机。
    /// </summary>
    public sealed class NatsControlClient : MonoBehaviour
    {
        [SerializeField] private string natsUrl = "nats://127.0.0.1:4222";

        public string NatsUrl => natsUrl;
    }
}

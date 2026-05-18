using UnityEngine;

namespace EgoAnchor.V2.Transport
{
    /// <summary>
    /// v2 NATS 控制面客户端占位组件。
    ///
    /// control plane（控制面）与 ZMQ 高频数据面相对：它只承载低频、小 payload、需要状态语义的消息，
    /// 例如 PoseResult、AnchorStatus、ServerHeartbeat 以及 reset/reacquire/control request。
    /// 当前 Quest -> Python 视频流 demo 不启用 NATS，本类只保留配置入口和职责说明。
    ///
    /// 后续本类负责：
    /// - 连接 NATS。
    /// - 订阅 PoseResult / AnchorStatus / ServerHeartbeat。
    /// - 发送 Reset/Reacquire/Control request 并处理 CommandAck。
    ///
    /// 注意：NATS handler 不应直接修改 Transform，也不应直接运行复杂状态机。
    /// </summary>
    public sealed class NatsControlClient : MonoBehaviour
    {
        [Tooltip("NATS server URL。开发机默认 nats://127.0.0.1:4222；Quest 真机部署时应通过 UI/PlayerPrefs 等配置注入。")]
        [SerializeField] private string natsUrl = "nats://127.0.0.1:4222";

        /// <summary>当前配置的 NATS 服务地址。</summary>
        public string NatsUrl => natsUrl;
    }
}

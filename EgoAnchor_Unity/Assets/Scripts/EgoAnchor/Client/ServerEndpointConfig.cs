using System;
using UnityEngine;

namespace EgoAnchor.Client
{
    /// <summary>
    /// 单点服务器端点配置：一处填 IP，启动时顺链路下发给数据面 (ZMQ) 和消息/命令面 (NATS)。
    ///
    /// 解决"切 3090/5090 要在多个组件手改 IP/URL"的痛点。纯 Inspector、无 PlayerPrefs 持久化：
    ///   1. 场景里挂一个本组件 (整个场景只需一个)，拖入下面那唯一一套连接组件的引用。
    ///   2. Inspector 选 <see cref="selected"/> 预设 (或勾 useCustomIp 填自定义 IP)。
    ///   3. 执行序 -1000，在所有连接组件的 Start 之前 Awake 调 publisher.SetServerIp / natsClient.SetNatsUrl，
    ///      自动把裸 IP 拼成 nats://&lt;ip&gt;:&lt;natsPort&gt;。
    ///
    /// 切服务器 = 改这一个下拉，零重挂、零持久化、零多处手填。
    /// </summary>
    [DefaultExecutionOrder(-1000)]
    public sealed class ServerEndpointConfig : MonoBehaviour
    {
        /// <summary>一个命名服务器预设：标签 + 裸 IP。</summary>
        [Serializable]
        public struct ServerPreset
        {
            [Tooltip("显示名，例如 LocalHost / RTX3090 / RTX5090。")]
            public string label;

            [Tooltip("Python 服务器裸 IP，例如 127.0.0.1 或 172.24.247.32。NATS URL 会自动拼成 nats://<ip>:<natsPort>。")]
            public string ip;
        }

        /// <summary>数据面 ZMQ publisher (Quest -> Python)。下发裸 IP。</summary>
        [Header("Targets (拖入唯一一套连接组件)")]
        [Tooltip("数据面 ZMQ publisher。启动时 SetServerIp(裸 IP)。")]
        [SerializeField] private QuestStreamPublisher dataPlanePublisher;

        /// <summary>消息/命令面 NATS client。下发完整 nats:// URL。</summary>
        [Tooltip("消息/命令面 NATS client。启动时 SetNatsUrl(nats://<ip>:<natsPort>)。")]
        [SerializeField] private NatsControlClient natsClient;

        /// <summary>可选服务器预设列表。</summary>
        [Header("Presets")]
        [Tooltip("服务器预设列表。每个预设只填一个裸 IP；数据面/NATS 地址由本组件自动分发。")]
        [SerializeField]
        private ServerPreset[] presets =
        {
            new ServerPreset { label = "LocalHost", ip = "127.0.0.1" },
            new ServerPreset { label = "RTX3090", ip = "127.0.0.1" },
            new ServerPreset { label = "RTX5090", ip = "172.24.247.32" },
        };

        /// <summary>当前选中的预设下标。</summary>
        [Tooltip("当前选中的预设下标。切 3090/5090 只改这一个值。")]
        [SerializeField] private int selected;

        /// <summary>勾选后用 customIp 覆盖预设，便于临时连任意 IP。</summary>
        [Header("Custom Override")]
        [Tooltip("勾选后用下面的 customIp 覆盖预设，便于临时连一个不在预设里的 IP。")]
        [SerializeField] private bool useCustomIp;

        /// <summary>自定义裸 IP（useCustomIp 勾选时生效）。</summary>
        [Tooltip("自定义裸 IP（useCustomIp 勾选时生效）。")]
        [SerializeField] private string customIp = "127.0.0.1";

        /// <summary>NATS 端口，用于拼 nats://&lt;ip&gt;:&lt;port&gt;。</summary>
        [Header("Ports")]
        [Tooltip("NATS 端口，用于拼 nats://<ip>:<port>。默认 4222。")]
        [SerializeField] private int natsPort = 4222;

        /// <summary>当前生效的裸 IP。</summary>
        public string ActiveIp => useCustomIp ? (customIp ?? string.Empty).Trim() : ResolvePresetIp();

        /// <summary>当前生效的 NATS URL。</summary>
        public string ActiveNatsUrl => $"nats://{ActiveIp}:{Mathf.Max(natsPort, 1)}";

        private void Awake()
        {
            Apply();
        }

        /// <summary>把当前选中 IP 顺链路下发给数据面 publisher 和 NATS client。</summary>
        public void Apply()
        {
            string ip = ActiveIp;
            if (string.IsNullOrWhiteSpace(ip))
            {
                Debug.LogWarning("[ServerEndpointConfig] 选中的 IP 为空，跳过下发。", this);
                return;
            }

            if (dataPlanePublisher != null)
            {
                dataPlanePublisher.SetServerIp(ip);
            }

            if (natsClient != null)
            {
                natsClient.SetNatsUrl(ActiveNatsUrl);
            }

            Debug.Log($"[ServerEndpointConfig] 服务器端点 = {ip} (data-plane IP) + {ActiveNatsUrl}。", this);
        }

        private string ResolvePresetIp()
        {
            if (presets == null || presets.Length == 0)
            {
                return string.Empty;
            }

            int index = Mathf.Clamp(selected, 0, presets.Length - 1);
            return (presets[index].ip ?? string.Empty).Trim();
        }
    }
}

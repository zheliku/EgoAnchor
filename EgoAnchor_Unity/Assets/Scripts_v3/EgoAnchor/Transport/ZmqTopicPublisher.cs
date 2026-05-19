using System;
using NetMQ;
using NetMQ.Sockets;
using UnityEngine;

namespace EgoAnchor.V3.Transport
{
    /// <summary>
    /// ZMQ topic 发布器。
    ///
    /// 本类是纯传输层，只负责 PUB socket 生命周期和 multipart 发送：
    /// [topic_utf8, protobuf_payload_bytes]。
    /// 它不理解 Quest 图像、相机标定、Protobuf 字段或 anchor 业务。
    /// </summary>
    public sealed class ZmqTopicPublisher : IDisposable
    {
        /// <summary>NetMQ PUB socket；为空表示尚未连接或已释放。</summary>
        private PublisherSocket socket;

        /// <summary>当前连接的 endpoint，例如 tcp://127.0.0.1:15557。</summary>
        private string endpoint;

        /// <summary>发送队列高水位；用于限制实时视频积压。</summary>
        private int sendHighWatermark;

        /// <summary>关闭 socket 时等待发送完成的毫秒数。</summary>
        private int socketLingerMs;

        /// <summary>当前是否已经创建并连接 PUB socket。</summary>
        public bool IsConnected => socket != null;

        /// <summary>当前连接目标 endpoint。</summary>
        public string Endpoint => endpoint;

        /// <summary>
        /// 连接到 Python v3 ZMQ SUB 接收端。
        /// </summary>
        /// <param name="serverIp">Python 接收端 IP；Quest 真机通常填开发机局域网 IP。</param>
        /// <param name="serverPort">Python 接收端端口，默认 15557。</param>
        /// <param name="hwm">发送高水位，越小越符合 latest-only 实时链路。</param>
        /// <param name="lingerMs">关闭 socket 等待毫秒数，demo 建议为 0。</param>
        public void Connect(string serverIp, int serverPort, int hwm, int lingerMs)
        {
            if (socket != null)
            {
                return;
            }

            endpoint = $"tcp://{serverIp}:{serverPort}";
            sendHighWatermark = Mathf.Max(1, hwm);
            socketLingerMs = Mathf.Max(0, lingerMs);

            // Unity/IL2CPP 下 NetMQ 通常需要强制托管 AsyncIO，避免运行时初始化问题。
            AsyncIO.ForceDotNet.Force();

            socket = new PublisherSocket();
            socket.Options.SendHighWatermark = sendHighWatermark;
            socket.Options.Linger = TimeSpan.FromMilliseconds(socketLingerMs);
            socket.Connect(endpoint);

            Debug.Log($"[V3 ZmqTopicPublisher] connected endpoint={endpoint}, hwm={sendHighWatermark}");
        }

        /// <summary>
        /// 发送一条 topic + payload 消息。
        /// </summary>
        /// <param name="topic">subjects.v1.json 定义的逻辑 channel 名称。</param>
        /// <param name="payload">已经序列化好的 Protobuf bytes。</param>
        /// <returns>消息是否被 NetMQ 立即接受；false 表示未连接、payload 无效或队列已满。</returns>
        public bool TrySend(string topic, byte[] payload)
        {
            if (socket == null || string.IsNullOrWhiteSpace(topic) || payload == null || payload.Length == 0)
            {
                return false;
            }

            NetMQMessage message = new NetMQMessage();
            message.Append(topic);
            message.Append(payload);
            return socket.TrySendMultipartMessage(TimeSpan.Zero, message);
        }

        /// <summary>
        /// 释放 socket。该方法可重复调用。
        /// </summary>
        public void Dispose()
        {
            if (socket == null)
            {
                return;
            }

            socket.Close();
            socket.Dispose();
            socket = null;
        }
    }
}
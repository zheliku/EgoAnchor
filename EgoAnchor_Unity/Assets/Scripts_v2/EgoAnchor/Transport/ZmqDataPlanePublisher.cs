using System;
using NetMQ;
using NetMQ.Sockets;
using UnityEngine;

namespace EgoAnchor.V2.Transport
{
    /// <summary>
    /// v2 ZMQ 数据面发布器。
    ///
    /// 职责边界：
    /// - 只管理 ZMQ PUB socket 生命周期。
    /// - 只发送 multipart [topic_utf8, protobuf_payload_bytes]。
    /// - 不理解 Quest 图像、相机标定或 anchor 语义。
    ///
    /// 注意：
    /// - Unity/Quest 端作为 PUB connect。
    /// - Python v2 端作为 SUB bind，默认端口 15557。
    /// </summary>
    public sealed class ZmqDataPlanePublisher : IDisposable
    {
        private PublisherSocket _socket;
        private string _endpoint;
        private int _sendHighWatermark;
        private int _socketLingerMs;

        public bool IsConnected => _socket != null;
        public string Endpoint => _endpoint;

        /// <summary>
        /// 连接到 Python v2 数据面接收端。
        /// </summary>
        public void Connect(string serverIp, int serverPort, int sendHighWatermark, int socketLingerMs)
        {
            if (_socket != null)
            {
                return;
            }

            _endpoint = $"tcp://{serverIp}:{serverPort}";
            _sendHighWatermark = Mathf.Max(1, sendHighWatermark);
            _socketLingerMs = Mathf.Max(0, socketLingerMs);

            // NetMQ 在 Unity/IL2CPP 环境中通常需要先强制使用托管 AsyncIO。
            AsyncIO.ForceDotNet.Force();

            _socket = new PublisherSocket();
            _socket.Options.SendHighWatermark = _sendHighWatermark;
            _socket.Options.Linger = TimeSpan.FromMilliseconds(_socketLingerMs);
            _socket.Connect(_endpoint);

            Debug.Log($"[ZmqDataPlanePublisher] Connected to {_endpoint}, hwm={_sendHighWatermark}");
        }

        /// <summary>
        /// 发送一条 v2 Protobuf payload。
        /// </summary>
        public bool TrySend(string topic, byte[] payload)
        {
            if (_socket == null || string.IsNullOrWhiteSpace(topic) || payload == null || payload.Length == 0)
            {
                return false;
            }

            NetMQMessage message = new NetMQMessage();
            message.Append(topic);
            message.Append(payload);
            return _socket.TrySendMultipartMessage(TimeSpan.Zero, message);
        }

        /// <summary>
        /// 断开 socket。linger=0 避免退出 Play Mode 时卡住。
        /// </summary>
        public void Dispose()
        {
            if (_socket == null)
            {
                return;
            }

            _socket.Close();
            _socket.Dispose();
            _socket = null;
        }
    }
}

using System;
using EgoAnchor.Net;
using NetMQ;
using NetMQ.Sockets;
using UnityEngine;

namespace EgoAnchor.V2.Transport
{
    /// <summary>
    /// ZMQ topic 发布器。
    ///
    /// 本类只管理 PUB socket 生命周期，并发送 multipart [topic_utf8, protobuf_payload_bytes]。
    /// 它不理解 Quest 图像、相机标定、anchor 或 Protobuf schema，因此命名为 TopicPublisher
    /// 比旧名 ZmqDataPlanePublisher 更贴近代码职责。
    ///
    /// 架构术语说明：data plane 是“高频数据面”，在本文项目中指 Quest stereo/camera_info
    /// 这类大吞吐实时数据；control plane 是“控制面”，指 NATS 上的命令、状态和心跳。
    /// 术语仍保留在文档和架构讨论中，但底层工具类尽量使用具体职责命名。
    /// </summary>
    public sealed class ZmqTopicPublisher : IDisposable
    {
        private PublisherSocket _socket;
        private string _endpoint;
        private int _sendHighWatermark;
        private int _socketLingerMs;
        private bool _ownsNetMqLease;

        /// <summary>当前是否已经创建并连接 PUB socket。</summary>
        public bool IsConnected => _socket != null;

        /// <summary>当前连接目标，例如 tcp://127.0.0.1:15557。</summary>
        public string Endpoint => _endpoint;

        /// <summary>
        /// 连接到 Python v2 ZMQ SUB 接收端。
        /// </summary>
        /// <param name="serverIp">Python 接收端 IP。</param>
        /// <param name="serverPort">Python 接收端端口，v2 默认 15557。</param>
        /// <param name="sendHighWatermark">发送队列高水位，用于限制积压。</param>
        /// <param name="socketLingerMs">关闭 socket 时等待发送完成的毫秒数。</param>
        public void Connect(string serverIp, int serverPort, int sendHighWatermark, int socketLingerMs)
        {
            if (_socket != null)
            {
                return;
            }

            _endpoint = $"tcp://{serverIp}:{serverPort}";
            _sendHighWatermark = Mathf.Max(1, sendHighWatermark);
            _socketLingerMs = Mathf.Max(0, socketLingerMs);

            try
            {
                NetMQUnityRuntime.Acquire();
                _ownsNetMqLease = true;
                _socket = new PublisherSocket();
                _socket.Options.SendHighWatermark = _sendHighWatermark;
                _socket.Options.Linger = TimeSpan.FromMilliseconds(_socketLingerMs);
                _socket.Connect(_endpoint);
            }
            catch
            {
                _socket?.Dispose();
                _socket = null;
                ReleaseNetMqLease();
                throw;
            }

            Debug.Log($"[ZmqTopicPublisher] Connected to {_endpoint}, hwm={_sendHighWatermark}");
        }

        /// <summary>
        /// 发送一条 topic + Protobuf bytes 消息。
        /// </summary>
        /// <param name="topic">subjects.v1.json 中定义的逻辑 channel 名称。</param>
        /// <param name="payload">已序列化的 Protobuf payload。</param>
        /// <returns>消息是否被 NetMQ 立即接受；false 通常表示 socket 未连接、payload 为空或队列已满。</returns>
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
        /// 断开 socket。linger=0 时可避免退出 Play Mode 卡住。
        /// </summary>
        public void Dispose()
        {
            if (_socket == null)
            {
                return;
            }

            try
            {
                _socket.Close();
            }
            catch (Exception exc)
            {
                Debug.LogWarning($"[ZmqTopicPublisher] socket close ignored: {exc.Message}");
            }
            finally
            {
                _socket.Dispose();
                _socket = null;
                ReleaseNetMqLease();
            }
        }

        private void ReleaseNetMqLease()
        {
            if (!_ownsNetMqLease)
            {
                return;
            }

            _ownsNetMqLease = false;
            NetMQUnityRuntime.Release();
        }
    }
}
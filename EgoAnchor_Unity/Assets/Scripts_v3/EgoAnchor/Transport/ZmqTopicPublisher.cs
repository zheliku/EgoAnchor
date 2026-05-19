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

            try
            {
                PrepareNetMq();
                socket = new PublisherSocket();
                socket.Options.SendHighWatermark = sendHighWatermark;
                socket.Options.Linger = TimeSpan.FromMilliseconds(socketLingerMs);
                socket.Connect(endpoint);
            }
            catch
            {
                socket?.Dispose();
                socket = null;
                CleanupNetMq("connect failed");
                throw;
            }

            Debug.Log($"[V3 ZmqTopicPublisher] connected endpoint={endpoint}, hwm={sendHighWatermark}");
        }

        /// <summary>
        /// 显式重连到当前 endpoint。用于 Play Mode 热重启或网络设置变更后的恢复。
        /// </summary>
        /// <param name="serverIp">Python 接收端 IP。</param>
        /// <param name="serverPort">Python 接收端端口。</param>
        /// <param name="hwm">发送高水位。</param>
        /// <param name="lingerMs">关闭 linger 毫秒数。</param>
        public void Reconnect(string serverIp, int serverPort, int hwm, int lingerMs)
        {
            Dispose();
            Connect(serverIp, serverPort, hwm, lingerMs);
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

            try
            {
                socket.Close();
            }
            catch (Exception exc)
            {
                Debug.LogWarning($"[V3 ZmqTopicPublisher] socket close ignored: {exc.Message}");
            }
            finally
            {
                socket.Dispose();
                socket = null;
                CleanupNetMq("publisher disposed");
            }
        }

        /// <summary>
        /// 创建 socket 前准备 NetMQ 运行环境。
        ///
        /// 当前 v3 场景只在 Unity 主线程创建/释放一个 ZMQ PUB socket，
        /// 因此不需要额外的全局状态锁或 lease manager。
        /// 如果未来同一场景出现多个 NetMQ socket 或后台 NetMQ 线程，再升级为集中 runtime。
        /// </summary>
        private static void PrepareNetMq()
        {
            AsyncIO.ForceDotNet.Force();
            NetMQConfig.Linger = TimeSpan.Zero;
        }

        /// <summary>
        /// 清理 NetMQ 进程级状态。
        ///
        /// 本方法只在本发布器失败或释放后调用；因为 v3 当前只有一个 ZMQ 发布器，
        /// 不需要全局锁。若未来多个 NetMQ 对象并存，应改回集中 runtime 统一清理。
        /// </summary>
        /// <param name="reason">触发清理的原因，便于日志排查。</param>
        private static void CleanupNetMq(string reason)
        {
            try
            {
                NetMQConfig.Cleanup(false);
            }
            catch (Exception exc)
            {
                Debug.LogWarning($"[V3 ZmqTopicPublisher] cleanup ignored ({reason}): {exc.Message}");
            }
        }
    }
}
using UnityEngine;
using NetMQ;
using NetMQ.Sockets;

public class PGMClient : MonoBehaviour
{
    private SubscriberSocket _subSocket;

    void Start()
    {
        AsyncIO.ForceDotNet.Force();
        _subSocket = new SubscriberSocket();

        try
        {
            // 连接到 Python 的广播地址
            // 对应 Python 的 epgm
            _subSocket.Connect("pgm://127.0.0.1:5555");

            // 重要！！Subscriber 必须订阅至少一个主题才能收到消息
            // Subscribe("") 表示订阅所有消息
            _subSocket.Subscribe("");

            Debug.Log("Unity: 已调频至广播电台...");
        }
        catch (NetMQException)
        {
            Debug.LogWarning("连接 PGM 失败，尝试 TCP...");
            _subSocket.Connect("tcp://localhost:5555");
            _subSocket.Subscribe("");
        }
    }

    void Update()
    {
        // 在 Update 中非阻塞接收
        string message;
        if (_subSocket.TryReceiveFrameString(out message))
        {
            Debug.Log($"Unity 收到广播: {message}");
        }
    }

    void OnDestroy()
    {
        if (_subSocket != null) _subSocket.Dispose();
        NetMQConfig.Cleanup();
    }
}
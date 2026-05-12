using UnityEngine;
using NetMQ;
using NetMQ.Sockets;
using System.Threading;

public class WeatherRadio : MonoBehaviour
{
    private Thread _clientThread;
    private volatile bool _isRunning;

    // 我们想听哪个频道？在 Inspector 里可以改，比如改成 "Alert" 或 "" (全听)
    public string TopicToSubscribe = "Weather";

    void Start()
    {
        AsyncIO.ForceDotNet.Force();
        _isRunning = true;
        _clientThread = new Thread(ClientWork);
        _clientThread.Start();
    }

    private void ClientWork()
    {
        try
        {
            // 1. 创建 Subscriber Socket (SUB)
            using (var subSocket = new SubscriberSocket())
            {
                // 2. 连接
                subSocket.Connect("tcp://localhost:5556");
                Debug.Log("Unity: 已连接气象站");

                // 3. 【关键】订阅主题
                // 如果 TopicToSubscribe 是 "Weather"，我们只收 Weather 开头的消息
                // 如果是 ""，收所有。
                subSocket.Subscribe(TopicToSubscribe);
                Debug.Log($"Unity: 已订阅频道 '{TopicToSubscribe}'");

                while (_isRunning)
                {
                    // 4. 接收多帧消息
                    // 我们知道 Python 发的是两帧：[Topic] + [Content]

                    // 接收第一帧 (Topic)
                    // 这里的 ReceiveFrameString 是阻塞的，所以必须放在子线程
                    string topic = subSocket.ReceiveFrameString();

                    // 接收第二帧 (Content)
                    string content = subSocket.ReceiveFrameString();

                    Debug.Log($"[收音机] 频道: {topic} | 内容: {content}");
                }
            }
        }
        catch (NetMQException ex)
        {
            // 退出时 socket 关闭可能会触发这里的异常，属正常现象
            if (_isRunning)
                Debug.LogError($"NetMQ 异常: {ex.Message}");
        }
    }

    void OnDestroy()
    {
        _isRunning = false;
        // 稍微等待线程结束
        if (_clientThread != null && _clientThread.IsAlive) _clientThread.Join(200);
        NetMQConfig.Cleanup(false);
    }
}
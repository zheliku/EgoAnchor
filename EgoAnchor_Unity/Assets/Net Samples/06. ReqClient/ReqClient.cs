using UnityEngine;
using NetMQ;
using NetMQ.Sockets;
using System.Threading;

public class ReqClient : MonoBehaviour
{
    private Thread _clientThread;
    private volatile bool _isRunning;

    void Start()
    {
        AsyncIO.ForceDotNet.Force();
        _isRunning = true;

        // 启动子线程运行网络逻辑
        _clientThread = new Thread(ClientWork);
        _clientThread.Start();
    }

    private void ClientWork()
    {
        try
        {
            // 1. 创建 Request Socket (REQ)
            // 它是主动的，必须先发，再收
            using (var client = new RequestSocket())
            {
                client.Connect("tcp://localhost:5555");
                Debug.Log("Unity: 已连接");

                while (_isRunning)
                {
                    // 2. 【必须】先发送 (Send)
                    Debug.Log("Unity: 发送 'Knock Knock'");
                    client.SendFrame("Knock Knock");

                    // 3. 【必须】等待接收 (Receive)
                    // 这里的 ReceiveFrameString 是阻塞的！
                    // 如果 Python 服务端挂了，或者忘了回消息，
                    // 这行代码会一直卡住，直到永远。
                    // 这就是为什么 REQ 模式有时候很危险。
                    string reply = client.ReceiveFrameString();

                    Debug.Log($"Unity: 收到回复 '{reply}'");

                    // 休息 2 秒再发下一次
                    Thread.Sleep(2000);
                }
            }
        }
        catch (NetMQException ex)
        {
            // 如果你打破了 Send->Receive 的顺序，会在这里捕获异常
            Debug.LogError($"NetMQ 异常: {ex.Message}");
        }
    }

    void OnDestroy()
    {
        _isRunning = false;
        // 强制清理，防止 Unity 卡死
        NetMQConfig.Cleanup(false);
    }
}
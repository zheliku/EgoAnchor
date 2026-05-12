using UnityEngine;
using NetMQ;
using NetMQ.Sockets;
using System.Threading;

public class Multipart2Client : MonoBehaviour
{
    // 线程管理，避免卡死 Unity 主线程
    private Thread _clientThread;
    private bool _isRunning;

    void Start()
    {
        // NetMQ 初始化必须步骤
        AsyncIO.ForceDotNet.Force();

        _isRunning = true;
        _clientThread = new Thread(ClientWork);
        _clientThread.Start();
    }

    // 这一块代码在子线程运行
    private void ClientWork()
    {
        try
        {
            // 创建 Request Socket
            using (var client = new RequestSocket())
            {
                client.Connect("tcp://localhost:5555");
                Debug.Log("Unity: 已连接服务器");

                // ====================================================
                // 演示：发送多帧消息 (Chaining 方式)
                // 目标发送: ["LOGIN", "Zelda", "123456"]
                // ====================================================

                Debug.Log("Unity: 正在发送登录请求...");

                // 注意：前两帧用 SendMoreFrame，最后一帧必须用 SendFrame
                client.SendMoreFrame("LOGIN")       // 第一帧
                      .SendMoreFrame("Zelda")       // 第二帧
                      .SendFrame("123456");         // 第三帧 (结束)

                // ====================================================
                // 演示：接收多帧消息 (NetMQMessage 方式)
                // 目标接收: ["STATUS", "OK"]
                // ====================================================

                // ReceiveMultipartMessage 会阻塞直到收到完整的消息包
                NetMQMessage response = client.ReceiveMultipartMessage();

                Debug.Log($"Unity: 收到回复，共 {response.FrameCount} 帧");

                // 遍历打印每一帧的内容
                // response[i] 返回的是 NetMQFrame 对象，需要转换成 String
                for (int i = 0; i < response.FrameCount; i++)
                {
                    string frameContent = response[i].ConvertToString();
                    Debug.Log($"   -> 第 {i} 帧: {frameContent}");
                }

                // 简单的逻辑判断
                if (response.FrameCount >= 2)
                {
                    string status = response[0].ConvertToString();
                    string result = response[1].ConvertToString();

                    if (status == "STATUS" && result == "OK")
                    {
                        Debug.Log(">>> 登录成功！ <<<");
                    }
                }
            }
        }
        catch (NetMQException ex)
        {
            Debug.LogError($"NetMQ 错误: {ex.Message}");
        }
    }

    // 停止游戏时清理线程
    void OnDestroy()
    {
        _isRunning = false;
        // 如果线程还在跑，稍微等一下或者强制关闭（这里简单处理）
        if (_clientThread != null && _clientThread.IsAlive)
        {
            _clientThread.Join(500);
        }
        NetMQConfig.Cleanup();
    }
}
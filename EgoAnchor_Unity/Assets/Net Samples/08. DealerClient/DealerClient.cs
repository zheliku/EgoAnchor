using UnityEngine;
using NetMQ;
using NetMQ.Sockets;
using System.Text;
using System.Threading;
using UnityEngine.InputSystem;

public class DealerClient : MonoBehaviour
{
    private DealerSocket _clientSocket;
    private NetMQPoller _poller;
    private Thread _pollerThread;
    private bool _isRunning;

    // 给自己起个名字，方便服务器认识我们
    public string ClientIdentity = "UnityHero_01";

    void Start()
    {
        AsyncIO.ForceDotNet.Force();
        _isRunning = true;

        // 启动网络线程
        _pollerThread = new Thread(StartPoller);
        _pollerThread.Start();
    }

    private void StartPoller()
    {
        // 1. 创建 Dealer Socket
        // Dealer 就像个话痨，它想发就发，不用等回复
        _clientSocket = new DealerSocket();

        // 【重要】设置 Identity
        // 如果不设置，Router 会收到一串乱码一样的随机二进制 ID
        // 设置了之后，Python 那边就能看到 "UnityHero_01"
        _clientSocket.Options.Identity = Encoding.UTF8.GetBytes(ClientIdentity);

        _clientSocket.Connect("tcp://localhost:5556");

        // 2. 绑定接收事件
        // 当有消息到达时，这个函数会被自动调用
        _clientSocket.ReceiveReady += OnReceiveReady;

        // 3. 创建 Poller 并加入 Socket
        _poller = new NetMQPoller { _clientSocket };

        // 4. 运行 Poller
        // RunAsync 是 NetMQ 提供的简便方法，但在 Unity 中为了完全控制线程，
        // 我们通常在自己的 Thread 里调用 Run()。
        Debug.Log("Unity: Poller 开始运行，准备接收消息...");
        _poller.Run();
    }

    // 当收到消息时触发（注意：这还是在子线程中）
    private void OnReceiveReady(object sender, NetMQSocketEventArgs e)
    {
        // Dealer 收到的消息不需要 Identity 帧（因为就通过这一根线连服务器）
        // 但根据我们在 Python 写的协议，服务器发回来的是 [Empty, Data]
        // 或者如果服务器没发 Empty，就是 [Data]
        // 让我们看看实际收到了什么。

        var msg = e.Socket.ReceiveMultipartMessage();

        // 打印调试
        string log = $"收到 {msg.FrameCount} 帧: ";
        foreach (var frame in msg) log += frame.ConvertToString() + " | ";
        Debug.Log($"[子线程收到] {log}");
    }

    void Update()
    {
        // 在主线程发送消息
        if (Keyboard.current != null && Keyboard.current.spaceKey.wasPressedThisFrame)
        {
            SendMessageToServer();
        }
    }

    private void SendMessageToServer()
    {
        if (_clientSocket == null) return;

        // 构建消息
        // 我们要模仿 Req-Rep 的结构：[Empty, Data]
        // 虽然 Dealer 不强制要求发 Empty，但为了配合 Python 那个 Router 的解析逻辑
        // 我们最好加上。
        var message = new NetMQMessage();
        message.AppendEmptyFrame(); // 对应 Python 的 frames[1]
        message.Append("Hello Router!"); // 对应 Python 的 frames[2]

        // 因为 Dealer 是线程安全的（在某种程度上），
        // 但最好还是把发送任务也交给 Poller 线程，或者直接发（NetMQ 内部处理了锁）
        // 这里为了简单，直接在主线程发（NetMQ 4.0+ 允许这样做，但要注意异常）
        // 更严谨的做法是用一个队列把数据传给 Poller 线程去发。
        // 但 DealerSocket 本身是可以在多线程环境使用的。

        _clientSocket.SendMultipartMessage(message);
        Debug.Log("Unity: 已发送消息 (不需要等待回复)");
    }

    void OnDestroy()
    {
        _isRunning = false;

        // 优雅关闭 Poller
        if (_poller != null)
        {
            _poller.Stop();
            _poller.Dispose();
        }

        if (_clientSocket != null)
        {
            _clientSocket.Dispose();
        }

        NetMQConfig.Cleanup(false);
    }
}
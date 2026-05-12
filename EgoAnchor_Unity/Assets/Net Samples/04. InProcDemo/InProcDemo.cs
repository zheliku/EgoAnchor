using UnityEngine;
using NetMQ;
using NetMQ.Sockets;
using System.Threading.Tasks; // 使用 Task 来模拟多线程

public class InProcDemo : MonoBehaviour
{
    private void Start()
    {
        AsyncIO.ForceDotNet.Force();

        // 启动示例
        RunInProcExample();
    }

    private void RunInProcExample()
    {
        // 创建两个 Socket：一个用来收 (receiver)，一个用来发 (sender)
        // PairSocket 是一种“一对一”的专属连接模式，非常适合线程间通信
        using (var receiver = new PairSocket())
        using (var sender = new PairSocket())
        {
            // 1. 绑定地址
            // 注意前缀是 inproc://，后面跟一个唯一的名字
            string address = "inproc://my-internal-pipe";

            receiver.Bind(address);
            sender.Connect(address);

            Debug.Log("Unity: InProc 管道已建立");

            // 2. 启动一个子线程 (Task)
            Task.Run(() =>
            {
                // --- 这里是子线程 ---
                // 模拟一些耗时计算
                System.Threading.Thread.Sleep(1000);

                string msg = "这是来自子线程的问候";
                Debug.Log($"[子线程 {System.Threading.Thread.CurrentThread.ManagedThreadId}] 正在发送: {msg}");

                // 发送给主线程
                sender.SendFrame(msg);
            });

            // --- 这里是主线程 ---
            Debug.Log($"[主线程] 等待消息...");

            // 接收消息
            // 注意：ReceiveFrameString 是阻塞的。
            // 在实际 Unity 项目中，建议使用 TryReceiveFrameString 放在 Update 中以免卡住界面
            string receivedMsg = receiver.ReceiveFrameString();

            Debug.Log($"[主线程] 收到: {receivedMsg}");
        }
    }

    private void OnDestroy()
    {
        NetMQConfig.Cleanup();
    }
}
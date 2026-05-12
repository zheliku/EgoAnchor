using UnityEngine;
using NetMQ;
using NetMQ.Sockets;
using System.Threading;
using System;
using System.Collections.Generic;
using System.Linq;

public class HelloClient : MonoBehaviour
{
    // 用于管理线程，避免 Unity 卡死
    private Thread _clientThread;
    private bool _isRunning;

    // 延迟统计相关
    [SerializeField]
    private List<double> _latencies = new List<double>(); // 存储所有延迟数据（毫秒）
    private int _messageCount = 0; // 发送消息计数
    private readonly object _lockObject = new object(); // 用于线程安全

    private void Start()
    {
        // 1. NetMQ 在 Unity 中的必要初始化
        // 如果不加这行，NetMQ 在 Unity 中可能会报错
        AsyncIO.ForceDotNet.Force();

        _isRunning = true;
        _clientThread = new Thread(ClientWork);
        _clientThread.Start();
    }

    private void ClientWork()
    {
        // 2. 创建 Socket
        // 使用 RequestSocket (REQ)，因为我们要发起请求
        // 这里的 using 语法会自动处理 socket 的释放（Cleanup）
        using (var client = new RequestSocket())
        {
            // 3. 连接 (Connect)
            // 注意：客户端使用的是 Connect，而不是 Bind
            // localhost 代表连接本机
            client.Connect("tcp://172.24.245.115:5555");
            Debug.Log("Unity 客户端已连接...");

            while (_isRunning)
            {
                // 记录客户端发送时间
                long clientSendTicks = DateTime.UtcNow.Ticks;
                string clientSendTimeStr = clientSendTicks.ToString();

                _messageCount++;
                Debug.Log($"Unity: [消息 #{_messageCount}] 正在发送，客户端时间戳: {clientSendTimeStr}");

                // 4. 发送消息 (Send)
                // 使用 SendMoreFrame + SendFrame 发送多帧消息
                client.SendMoreFrame("Hello").SendFrame(clientSendTimeStr);

                // 5. 接收回复并处理延迟统计
                ProcessServerResponse(client, clientSendTicks);

                // 休息一下再发下一次
                // Thread.Sleep(1000);
            }
        }
    }

    /// <summary>
    /// 处理服务器响应并计算延迟统计
    /// </summary>
    private void ProcessServerResponse(RequestSocket client, long clientSendTicks)
    {
        // 接收第一帧（消息内容）
        string messageContent = client.ReceiveFrameString(out bool hasMore);

        // 记录客户端接收时间
        long clientReceiveTicks = DateTime.UtcNow.Ticks;

        // 检查是否有更多帧
        if (!hasMore)
        {
            Debug.LogWarning($"Unity: 收到单帧消息: {messageContent}");
            return;
        }

        // 接收后续帧
        string returnedClientSendTime = client.ReceiveFrameString(out hasMore);
        if (!hasMore)
        {
            Debug.LogWarning($"Unity: 服务器未返回完整的4帧数据（缺少帧3和4）");
            return;
        }

        string serverReceiveTime = client.ReceiveFrameString(out hasMore);
        if (!hasMore)
        {
            Debug.LogWarning($"Unity: 服务器未返回完整的4帧数据（缺少帧4）");
            return;
        }

        string serverSendTime = client.ReceiveFrameString(out hasMore);
        if (!hasMore)
        {
            Debug.LogWarning($"Unity: 服务器未返回完整的5帧数据（缺少帧5）");
            return;
        }

        // 接收第五帧（服务器处理时间，单位：毫秒）
        string serverProcessTimeStr = client.ReceiveFrameString();

        // 解析服务器处理时间
        if (!double.TryParse(serverProcessTimeStr, out double serverProcessMs))
        {
            Debug.LogWarning($"Unity: 无法解析服务器处理时间");
            return;
        }

        // 计算延迟统计（使用参数中的 clientSendTicks，而非服务器返回的）
        CalculateAndLogLatency(messageContent, clientSendTicks, serverProcessMs, clientReceiveTicks);
    }

    /// <summary>
    /// 计算并记录延迟统计
    /// </summary>
    private void CalculateAndLogLatency(string messageContent, long clientSendTicks,
        double serverProcessMs, long clientReceiveTicks)
    {
        // 计算总往返延迟（RTT）
        long ticksDiff = clientReceiveTicks - clientSendTicks;
        double totalRttMs = ticksDiff / 10000.0;

        // 验证数据有效性
        if (totalRttMs <= 0)
        {
            Debug.LogWarning($"Unity: [消息 #{_messageCount}] 检测到无效延迟: {totalRttMs:F6} ms (Ticks差值: {ticksDiff})");
            Debug.LogWarning($"  发送时间: {clientSendTicks}, 接收时间: {clientReceiveTicks}");
            // 不添加到统计列表
            return;
        }

        // 计算网络延迟（往返延迟 - 服务器处理时间）
        double networkLatencyMs = totalRttMs - serverProcessMs;

        // 假设上行和下行延迟相等（单程网络延迟）
        double oneWayNetworkMs = networkLatencyMs / 2.0;

        // 线程安全地添加延迟数据
        lock (_lockObject)
        {
            _latencies.Add(totalRttMs);
        }

        // 输出延迟分析
        Debug.Log($"Unity: [消息 #{_messageCount}] 收到回复: {messageContent}");
        Debug.Log($"Unity: [消息 #{_messageCount}] ━━━━━━ 延迟分析 ━━━━━━");
        Debug.Log($"  🔄 总往返延迟(RTT): {totalRttMs:F4} ms (Ticks: {ticksDiff})");
        Debug.Log($"  ⚙️  服务器处理时间: {serverProcessMs:F2} ms");
        Debug.Log($"  🌐 网络延迟(往返): {networkLatencyMs:F4} ms");
        Debug.Log($"  📡 单程网络延迟(估算): {oneWayNetworkMs:F4} ms");
        Debug.Log($"Unity: ━━━━━━━━━━━━━━━━━━━━━━━━");

        // 每5条消息输出一次统计
        if (_messageCount % 5 == 0)
        {
            PrintLatencyStats();
        }
    }

    /// <summary>
    /// 打印延迟统计信息
    /// </summary>
    private void PrintLatencyStats()
    {
        lock (_lockObject)
        {
            if (_latencies.Count == 0)
                return;

            // 过滤掉无效值（0和负数）
            var validLatencies = _latencies.Where(x => x > 0).ToList();

            if (validLatencies.Count == 0)
            {
                Debug.LogWarning("所有延迟数据都是无效值！0）");
                return;
            }

            double avgLatency = validLatencies.Average();
            double minLatency = validLatencies.Min();
            double maxLatency = validLatencies.Max();

            // 计算标准差
            double variance = validLatencies.Select(x => Math.Pow(x - avgLatency, 2)).Average();
            double stdDev = Math.Sqrt(variance);

            Debug.Log("====== 网络延迟统计 ======");
            Debug.Log($"样本总数: {_latencies.Count}, 有效样本: {validLatencies.Count}");
            Debug.Log($"平均延迟: {avgLatency:F4} ms");
            Debug.Log($"最小延迟: {minLatency:F4} ms");
            Debug.Log($"最大延迟: {maxLatency:F4} ms");
            Debug.Log($"标准差: {stdDev:F4} ms");
            Debug.Log("=========================");
        }
    }

    private void OnDestroy()
    {
        // 6. 清理工作
        // Unity 停止播放时，必须优雅地关闭线程和 NetMQ
        _isRunning = false;

        // 输出最终统计
        if (_latencies.Count > 0)
        {
            Debug.Log("\n====== 最终网络延迟统计 ======");
            PrintLatencyStats();
        }

        // 强制清理 NetMQ 上下文，防止 Unity 二次运行时出错
        NetMQConfig.Cleanup();
    }
}
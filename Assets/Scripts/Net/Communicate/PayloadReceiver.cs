using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Threading;
using NetMQ;
using NetMQ.Sockets;
using Proxima;
using RuntimeInspectorNamespace;
using UnityEngine;
using VInspector;
using Debug = UnityEngine.Debug;

/// <summary>
/// 原始负载结构：包含 payload 字节、topic 名称和接收时间戳。
/// </summary>
public readonly struct RawPayload
{
    public byte[] Payload { get; }
    public string Topic { get; }
    public double TimestampMs { get; }

    public RawPayload(byte[] payload, string topic, double timestampMs)
    {
        Payload = payload;
        Topic = topic;
        TimestampMs = timestampMs;
    }
}

/// <summary>
/// 接收条目：每个条目绑定一个 topic 和解码器。
/// </summary>
[Serializable]
public class ReceiverEntry
{
    [Tooltip("订阅 topic 名称")] public string topic = "";
    [Tooltip("解码器实例，负责解析该 topic 的 payload")] public BaseDecoder decoder;
}

/// <summary>
/// Unity 侧多 Topic Payload 接收器。
///
/// 设计目标：
/// - 面向 Inspector 配置：一个 PayloadReceiver 持有多个 ReceiverEntry，
///   每个 Entry 绑定独立的 topic 和解码器。
/// - 统一使用 SUB 模式，订阅所有配置的 topics。
/// - 后台线程接收，主线程按 topic 路由到对应解码器。
/// - 实时性策略：latest-drain，仅保留每个 topic 的最新帧。
/// </summary>
public class PayloadReceiver : MonoBehaviour
{
    private const string ReceiverIPPrefKey = "PayloadReceiver.ServerIP";
    private const string ReceiverPortPrefKey = "PayloadReceiver.ServerPort";
    private const string ReceiveHighWatermarkPrefKey = "PayloadReceiver.ReceiveHighWatermark";
    private const string SocketLingerMsPrefKey = "PayloadReceiver.SocketLingerMs";
    private const string ReceivePollTimeoutMsPrefKey = "PayloadReceiver.ReceivePollTimeoutMs";

    [Header("Network")]
    [SerializeField] private string serverIP = "127.0.0.1";
    [SerializeField] private int serverPort = 5556;
    [SerializeField] private int receiveHighWatermark = 1;
    [SerializeField] private int socketLingerMs = 0;
    [SerializeField] private int receivePollTimeoutMs = 100;

    [Header("Entries")]
    [Tooltip("接收条目列表，每个条目绑定 topic 和解码器")]
    [SerializeField] private List<ReceiverEntry> entries = new List<ReceiverEntry>();

    private SubscriberSocket _socket;
    private Thread _receiveThread;
    private volatile bool _running;
    private readonly Stopwatch _stopwatch = new Stopwatch();

    // 按 topic 缓存最新 payload。
    private readonly object _lock = new object();
    private readonly Dictionary<string, RawPayload> _latestByTopic = new Dictionary<string, RawPayload>();
    private readonly HashSet<string> _newTopics = new HashSet<string>();
    private readonly Dictionary<string, ReceiverEntry> _entriesByTopic = new Dictionary<string, ReceiverEntry>();

    public bool IsConnected => _running && _socket != null;
    public string ServerAddress => $"tcp://{serverIP}:{serverPort}";

    private void Awake()
    {
        LoadConfig();
    }

    [Button("Load Config")]
    [RuntimeInspectorButton("Load Config", false, ButtonVisibility.InitializedObjects)]
    [ProximaButton("Load Config")]
    private void LoadConfig()
    {
        serverIP = PlayerPrefs.GetString(ReceiverIPPrefKey, serverIP);
        serverPort = PlayerPrefs.GetInt(ReceiverPortPrefKey, serverPort);
        receiveHighWatermark = PlayerPrefs.GetInt(ReceiveHighWatermarkPrefKey, receiveHighWatermark);
        socketLingerMs = PlayerPrefs.GetInt(SocketLingerMsPrefKey, socketLingerMs);
        receivePollTimeoutMs = PlayerPrefs.GetInt(ReceivePollTimeoutMsPrefKey, receivePollTimeoutMs);
    }

    [Button("Save Config")]
    [RuntimeInspectorButton("Save Config", false, ButtonVisibility.InitializedObjects)]
    [ProximaButton("Save Config")]
    private void SaveConfig()
    {
        PlayerPrefs.SetString(ReceiverIPPrefKey, serverIP);
        PlayerPrefs.SetInt(ReceiverPortPrefKey, serverPort);
        PlayerPrefs.SetInt(ReceiveHighWatermarkPrefKey, receiveHighWatermark);
        PlayerPrefs.SetInt(SocketLingerMsPrefKey, socketLingerMs);
        PlayerPrefs.SetInt(ReceivePollTimeoutMsPrefKey, receivePollTimeoutMs);
        PlayerPrefs.Save();
    }

    [Button("Reconnect")]
    [RuntimeInspectorButton("Reconnect", false, ButtonVisibility.InitializedObjects)]
    [ProximaButton("Reconnect")]
    private void Reconnect()
    {
        Disconnect();
        Connect();
    }

    private void Start()
    {
        ValidateEntries();

        if (!_stopwatch.IsRunning)
        {
            _stopwatch.Start();
        }

        Connect();
    }

    private void ValidateEntries()
    {
        _entriesByTopic.Clear();

        for (int i = 0; i < entries.Count; i++)
        {
            if (entries[i].decoder == null)
            {
                Debug.LogError($"[PayloadReceiver] Entry[{i}] decoder is null.", this);
            }

            if (string.IsNullOrWhiteSpace(entries[i].topic))
            {
                Debug.LogError($"[PayloadReceiver] Entry[{i}] topic is empty.", this);
                continue;
            }

            if (_entriesByTopic.ContainsKey(entries[i].topic))
            {
                Debug.LogWarning($"[PayloadReceiver] Duplicate topic ignored: {entries[i].topic}", this);
                continue;
            }

            _entriesByTopic.Add(entries[i].topic, entries[i]);
        }
    }

    /// <summary>
    /// 主线程分发：将后台线程缓存的新 payload 路由到对应解码器。
    /// </summary>
    private void Update()
    {
        List<RawPayload> pending;

        lock (_lock)
        {
            if (_newTopics.Count == 0)
            {
                return;
            }

            pending = new List<RawPayload>(_newTopics.Count);
            foreach (string topic in _newTopics)
            {
                if (_latestByTopic.TryGetValue(topic, out RawPayload payload))
                {
                    pending.Add(payload);
                }
            }

            _newTopics.Clear();
        }

        // 路由到对应解码器。
        for (int i = 0; i < pending.Count; i++)
        {
            RawPayload payload = pending[i];
            if (payload.Topic != null &&
                _entriesByTopic.TryGetValue(payload.Topic, out ReceiverEntry entry) &&
                entry.decoder != null)
            {
                entry.decoder.OnPayloadReceived(payload);
            }
        }
    }

    public void Connect()
    {
        if (_running)
        {
            return;
        }

        AsyncIO.ForceDotNet.Force();

        _socket = new SubscriberSocket();
        _socket.Options.ReceiveHighWatermark = receiveHighWatermark;
        _socket.Options.Linger = TimeSpan.FromMilliseconds(socketLingerMs);
        _socket.Connect(ServerAddress);

        // 订阅所有配置的 topics。
        for (int i = 0; i < entries.Count; i++)
        {
            string topic = entries[i].topic ?? string.Empty;
            if (string.IsNullOrWhiteSpace(topic))
            {
                continue;
            }
            _socket.Subscribe(topic);
        }

        _running = true;
        _receiveThread = new Thread(ReceiveLoop) { IsBackground = true };
        _receiveThread.Start();

        string topicList = string.Join(", ", entries.ConvertAll(e => e.topic));
        Debug.Log($"[PayloadReceiver] Connected to {ServerAddress}, topics=[{topicList}]");
    }

    public void Disconnect()
    {
        _running = false;

        if (_receiveThread != null && _receiveThread.IsAlive)
        {
            _receiveThread.Join(1000);
        }

        _receiveThread = null;
        DisconnectSocket();
        Debug.Log("[PayloadReceiver] Disconnected");
    }

    /// <summary>
    /// 从底层 socket 读取一条 SUB 消息，返回 topic + payload。
    /// </summary>
    private bool TryReceiveOnePayload(int timeoutMs, out string topic, out byte[] payload)
    {
        topic = null;
        payload = null;

        if (_socket == null)
        {
            return false;
        }

        TimeSpan timeout = timeoutMs <= 0
            ? TimeSpan.Zero
            : TimeSpan.FromMilliseconds(timeoutMs);

        NetMQMessage message = new NetMQMessage();
        if (!_socket.TryReceiveMultipartMessage(timeout, ref message))
        {
            return false;
        }

        if (message.FrameCount != 2)
        {
            return false;
        }

        topic = message[0].ConvertToString();
        payload = message[1].ToByteArray();
        return payload != null && payload.Length > 0;
    }

    private void ReceiveLoop()
    {
        while (_running)
        {
            try
            {
                if (_socket == null)
                {
                    Thread.Sleep(10);
                    continue;
                }

                // 第一步：按配置超时等待至少一条消息。
                if (!TryReceiveOnePayload(receivePollTimeoutMs, out string topic, out byte[] payload))
                {
                    continue;
                }

                // 将第一条消息存入缓存。
                double firstTs = _stopwatch.Elapsed.TotalMilliseconds;
                lock (_lock)
                {
                    _latestByTopic[topic] = new RawPayload(payload, topic, firstTs);
                    _newTopics.Add(topic);
                }

                // 第二步：非阻塞 drain 队列，每条消息按 topic 分别缓存（而非只保留最后一条）。
                while (TryReceiveOnePayload(0, out string newerTopic, out byte[] newerPayload))
                {
                    double drainTs = _stopwatch.Elapsed.TotalMilliseconds;
                    lock (_lock)
                    {
                        _latestByTopic[newerTopic] = new RawPayload(newerPayload, newerTopic, drainTs);
                        _newTopics.Add(newerTopic);
                    }
                }
            }
            catch (Exception e)
            {
                if (_running)
                {
                    Debug.LogError($"[PayloadReceiver] Error: {e.Message}");
                }
            }
        }
    }

    /// <summary>
    /// 获取指定 topic 的最新 payload（不消耗，仅查询）。
    /// </summary>
    public bool TryGetLatestPayload(string topic, out RawPayload payload)
    {
        lock (_lock)
        {
            return _latestByTopic.TryGetValue(topic, out payload);
        }
    }

    private void DisconnectSocket()
    {
        if (_socket == null)
        {
            return;
        }

        _socket.Close();
        _socket.Dispose();
        _socket = null;
    }

    private void OnDestroy()
    {
        Disconnect();
        NetMQConfig.Cleanup(false);
    }

    private void OnApplicationQuit()
    {
        Disconnect();
    }
}

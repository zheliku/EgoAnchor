using System;
using System.Collections;
using System.Collections.Generic;
using NetMQ;
using NetMQ.Sockets;
using Proxima;
using RuntimeInspectorNamespace;
using UnityEngine;
using VInspector;

/// <summary>
/// 发送条目：每个条目绑定一个编码器、topic 和独立帧率。
/// </summary>
[Serializable]
public class SenderEntry
{
    [Tooltip("编码器实例，负责生成单帧 payload")] public BaseEncoder encoder;
    [Tooltip("PUB 模式的 topic 名称")] public string topic = "default";
    [Tooltip("发送帧率（每秒最大编码+发送次数）")] public int targetFps = 10;

    // 运行时状态（非序列化）。
    [NonSerialized] public double lastSendTime;
    [NonSerialized] public int sentCount;
    [NonSerialized] public int droppedCount;
    [NonSerialized] public double encodeTimeAcc;
}

/// <summary>
/// Unity 侧多 Topic Payload 发送器。
///
/// 设计目标：
/// - 面向 Inspector 配置：一个 PayloadSender 持有多个 SenderEntry，
///   每个 Entry 绑定独立的编码器、topic 和帧率。
/// - 统一使用 PUB 模式，所有 Entry 共享同一个 PublisherSocket。
/// - 每帧遍历所有 Entry，按各自帧率独立编码和发送。
/// - 支持服务器地址持久化与运行中切换。
/// </summary>
public class PayloadSender : MonoBehaviour
{
    private const string SenderIPPrefKey = "PayloadSender.ServerIP";
    private const string SenderPortPrefKey = "PayloadSender.ServerPort";
    private const string SendHighWatermarkPrefKey = "PayloadSender.SendHighWatermark";
    private const string SocketLingerMsPrefKey = "PayloadSender.SocketLingerMs";
    private const string LogIntervalPrefKey = "PayloadSender.LogInterval";

    [Header("Network")]
    [SerializeField] private string serverIP = "127.0.0.1";
    [SerializeField] private int serverPort = 5557;
    [SerializeField] private int sendHighWatermark = 10;
    [SerializeField] private int socketLingerMs = 0;
    [SerializeField] private int logInterval = 60;

    [Header("Entries")]
    [Tooltip("发送条目列表，每个条目绑定编码器、topic 和帧率")]
    [SerializeField] private List<SenderEntry> entries = new List<SenderEntry>();

    private PublisherSocket _socket;
    private Coroutine _sendCoroutine;

    // 全局统计。
    private int _totalSent;
    private int _totalDropped;
    private double _lastStatTime;
    private int _lastStatSent;
    private int _lastStatTotal;

    private string Endpoint => $"tcp://{serverIP}:{serverPort}";

    private void Awake()
    {
        LoadConfig();
    }

    [Button("Load Config")]
    [RuntimeInspectorButton("Load Config", false, ButtonVisibility.InitializedObjects)]
    [ProximaButton("Load Config")]
    private void LoadConfig()
    {
        serverIP = PlayerPrefs.GetString(SenderIPPrefKey, serverIP);
        serverPort = PlayerPrefs.GetInt(SenderPortPrefKey, serverPort);
        sendHighWatermark = PlayerPrefs.GetInt(SendHighWatermarkPrefKey, sendHighWatermark);
        socketLingerMs = PlayerPrefs.GetInt(SocketLingerMsPrefKey, socketLingerMs);
        logInterval = PlayerPrefs.GetInt(LogIntervalPrefKey, logInterval);
    }

    [Button("Save Config")]
    [RuntimeInspectorButton("Save Config", false, ButtonVisibility.InitializedObjects)]
    [ProximaButton("Save Config")]
    private void SaveConfig()
    {
        PlayerPrefs.SetString(SenderIPPrefKey, serverIP);
        PlayerPrefs.SetInt(SenderPortPrefKey, serverPort);
        PlayerPrefs.SetInt(SendHighWatermarkPrefKey, sendHighWatermark);
        PlayerPrefs.SetInt(SocketLingerMsPrefKey, socketLingerMs);
        PlayerPrefs.SetInt(LogIntervalPrefKey, logInterval);
        PlayerPrefs.Save();
    }

    [Button("Reconnect")]
    [RuntimeInspectorButton("Reconnect", false, ButtonVisibility.InitializedObjects)]
    [ProximaButton("Reconnect")]
    private void Reconnect()
    {
        DisconnectSocket();
        Connect();
    }

    private IEnumerator Start()
    {
        // 校验 entries 配置。
        for (int i = 0; i < entries.Count; i++)
        {
            if (entries[i].encoder == null)
            {
                Debug.LogError($"[PayloadSender] Entry[{i}] encoder is null.");
            }

            if (string.IsNullOrWhiteSpace(entries[i].topic))
            {
                Debug.LogError($"[PayloadSender] Entry[{i}] topic is empty.");
            }
        }

        if (sendHighWatermark > 1)
        {
            Debug.LogWarning($"[PayloadSender] sendHighWatermark={sendHighWatermark} (>1) 可能引入排队延迟。", this);
        }

        Connect();
        _lastStatTime = Time.realtimeSinceStartupAsDouble;
        _sendCoroutine = StartCoroutine(SendLoop());
        yield return null;
    }

    private void Connect()
    {
        if (_socket != null)
        {
            return;
        }

        AsyncIO.ForceDotNet.Force();

        _socket = new PublisherSocket();
        _socket.Options.SendHighWatermark = sendHighWatermark;
        _socket.Options.Linger = TimeSpan.FromMilliseconds(socketLingerMs);
        _socket.Connect(Endpoint);

        string entrySummary = string.Join(", ", entries.ConvertAll(e => $"{e.topic}@{e.targetFps}fps"));
        Debug.Log($"[PayloadSender] Connected to {Endpoint}, entries=[{entrySummary}]");
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

    /// <summary>
    /// 固定帧率发送循环：遍历所有 Entry，按各自帧率独立编码并发送。
    /// </summary>
    private IEnumerator SendLoop()
    {
        while (true)
        {
            double now = Time.realtimeSinceStartupAsDouble;

            for (int i = 0; i < entries.Count; i++)
            {
                SenderEntry entry = entries[i];
                if (entry.encoder == null || string.IsNullOrWhiteSpace(entry.topic))
                {
                    continue;
                }

                // 帧率控制：检查是否到达该 Entry 的发送时机。
                float interval = 1f / Mathf.Max(1, entry.targetFps);
                if (now - entry.lastSendTime < interval)
                {
                    continue;
                }

                double encodeStart = Time.realtimeSinceStartupAsDouble;
                bool encoded = entry.encoder.TryEncodePayload(out byte[] payload) &&
                               payload != null && payload.Length > 0;
                entry.encodeTimeAcc += Time.realtimeSinceStartupAsDouble - encodeStart;

                if (!encoded || _socket == null)
                {
                    continue;
                }

                // PUB 模式：发送 multipart [topic, payload]。
                NetMQMessage message = new NetMQMessage();
                message.Append(entry.topic);
                message.Append(payload);
                bool sent = _socket.TrySendMultipartMessage(TimeSpan.Zero, message);

                if (sent)
                {
                    entry.sentCount++;
                    _totalSent++;
                }
                else
                {
                    entry.droppedCount++;
                    _totalDropped++;
                }

                entry.lastSendTime = Time.realtimeSinceStartupAsDouble;
            }

            // 周期日志。
            int total = _totalSent + _totalDropped;
            if (logInterval > 0 && total > 0 && total % logInterval == 0)
            {
                double statNow = Time.realtimeSinceStartupAsDouble;
                double statInterval = statNow - _lastStatTime;
                int deltaTotal = total - _lastStatTotal;
                int deltaSent = _totalSent - _lastStatSent;

                float actualFps = statInterval > 0d ? (float)(deltaSent / statInterval) : 0f;
                float dropRate = deltaTotal > 0 ? (float)(deltaTotal - deltaSent) / deltaTotal : 0f;

                Debug.Log(
                    $"[PayloadSender] Sent={_totalSent}, Dropped={_totalDropped}, " +
                    $"ActualFPS={actualFps:F1}, DropRate={dropRate:P1}, Interval={statInterval:F2}s"
                );

                _lastStatTime = statNow;
                _lastStatTotal = total;
                _lastStatSent = _totalSent;
            }

            yield return null;
        }
    }

    private void Cleanup()
    {
        if (_sendCoroutine != null)
        {
            StopCoroutine(_sendCoroutine);
            _sendCoroutine = null;
        }

        DisconnectSocket();
    }

    private void OnDestroy()
    {
        Cleanup();
        NetMQConfig.Cleanup(false);
    }

    private void OnApplicationQuit()
    {
        Cleanup();
    }
}

using System;
using System.Diagnostics;
using System.Threading;
using NetMQ;
using NetMQ.Sockets;
using Proxima;
using RuntimeInspectorNamespace;
using UnityEngine;
using UnityEngine.Events;
using VInspector;
using Debug = UnityEngine.Debug;

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

[Serializable]
public class RawPayloadEvent : UnityEvent<RawPayload> { }

/// <summary>
/// Unity 侧通用 Payload 接收器。
///
/// 统一协议（与 Python 对齐）：
/// - useTopic=false -> PULL（单帧 payload）
/// - useTopic=true  -> SUB（multipart: [topic, payload]）
///
/// 实时性策略：
/// - 始终采用“latest-drain”：每次先收一帧，再非阻塞清空队列，仅保留最新帧。
/// </summary>
public class PayloadReceiver : MonoBehaviour
{
    private const string ReceiverIPPrefKey = "PayloadReceiver.ServerIP";
    private const string ReceiverPortPrefKey = "PayloadReceiver.ServerPort";
    private const string ReceiverUseTopicPrefKey = "PayloadReceiver.UseTopic";
    private const string ReceiverTopicPrefKey = "PayloadReceiver.Topic";
    private const string ReceiveHighWatermarkPrefKey = "PayloadReceiver.ReceiveHighWatermark";
    private const string SocketLingerMsPrefKey = "PayloadReceiver.SocketLingerMs";
    private const string ReceivePollTimeoutMsPrefKey = "PayloadReceiver.ReceivePollTimeoutMs";

    [SerializeField] private string serverIP = "127.0.0.1";
    [SerializeField] private int serverPort = 5556;
    [SerializeField] private bool useTopic = true;
    [SerializeField] private string topic = "pose";
    [SerializeField] private int receiveHighWatermark = 1;
    [SerializeField] private int socketLingerMs = 0;
    [SerializeField] private int receivePollTimeoutMs = 100;

    private NetMQSocket _socket;
    private Thread _receiveThread;
    private volatile bool _running;
    private readonly Stopwatch _stopwatch = new Stopwatch();

    private readonly object _lock = new object();
    private RawPayload _latestPayload;
    private bool _hasNewPayload;

    public bool IsConnected => _running && _socket != null;
    public string ServerAddress => $"tcp://{serverIP}:{serverPort}";

    [Header("Events")]
    public RawPayloadEvent OnPayloadReceived = new RawPayloadEvent();

    private void Awake()
    {
        if (OnPayloadReceived == null)
        {
            OnPayloadReceived = new RawPayloadEvent();
        }

        LoadConfig();
    }

    [Button("Load Config")]
    [RuntimeInspectorButton("Load Config", false, ButtonVisibility.InitializedObjects)]
    [ProximaButton("Load Config")]
    private void LoadConfig()
    {
        serverIP = PlayerPrefs.GetString(ReceiverIPPrefKey, serverIP);
        serverPort = PlayerPrefs.GetInt(ReceiverPortPrefKey, serverPort);
        useTopic = PlayerPrefs.GetInt(ReceiverUseTopicPrefKey, useTopic ? 1 : 0) != 0;
        topic = PlayerPrefs.GetString(ReceiverTopicPrefKey, topic);
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
        PlayerPrefs.SetInt(ReceiverUseTopicPrefKey, useTopic ? 1 : 0);
        PlayerPrefs.SetString(ReceiverTopicPrefKey, topic);
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
        if (!_stopwatch.IsRunning)
        {
            _stopwatch.Start();
        }

        Connect();
    }

    private void Update()
    {
        RawPayload payload;

        lock (_lock)
        {
            if (!_hasNewPayload)
            {
                return;
            }

            payload = _latestPayload;
            _hasNewPayload = false;
        }

        OnPayloadReceived?.Invoke(payload);
    }

    public void Connect()
    {
        if (_running)
        {
            return;
        }

        AsyncIO.ForceDotNet.Force();

        _socket = useTopic ? new SubscriberSocket() : new PullSocket();
        _socket.Options.ReceiveHighWatermark = receiveHighWatermark;
        _socket.Options.Linger = TimeSpan.FromMilliseconds(socketLingerMs);
        _socket.Connect(ServerAddress);

        if (useTopic && _socket is SubscriberSocket subscriberSocket)
        {
            subscriberSocket.Subscribe(topic ?? string.Empty);
        }

        _running = true;
        _receiveThread = new Thread(ReceiveLoop) { IsBackground = true };
        _receiveThread.Start();

        string modeDesc = useTopic ? $"SUB(topic={topic})" : "PULL";
        Debug.Log($"[PayloadReceiver] Connected to {ServerAddress}, mode={modeDesc}, latest=drain");
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
    /// 从底层 socket 读取一条业务消息。
    ///
    /// timeoutMs 约定：
    /// - >0：阻塞等待给定毫秒
    /// - 0：非阻塞轮询
    /// </summary>
    private bool TryReceiveOnePayload(int timeoutMs, out RawPayload payload)
    {
        payload = default;
        if (_socket == null)
        {
            return false;
        }

        TimeSpan timeout = timeoutMs <= 0
            ? TimeSpan.Zero
            : TimeSpan.FromMilliseconds(timeoutMs);

        if (useTopic)
        {
            NetMQMessage message = new NetMQMessage();
            if (!_socket.TryReceiveMultipartMessage(timeout, ref message))
            {
                return false;
            }

            if (message.FrameCount < 2)
            {
                return false;
            }

            string receivedTopic = message[0].ConvertToString();
            byte[] body = message[1].ToByteArray();
            if (body == null || body.Length == 0)
            {
                return false;
            }

            payload = new RawPayload(body, receivedTopic, _stopwatch.Elapsed.TotalMilliseconds);
            return true;
        }
        else
        {
            if (!_socket.TryReceiveFrameBytes(timeout, out byte[] body))
            {
                return false;
            }

            if (body == null || body.Length == 0)
            {
                return false;
            }

            payload = new RawPayload(body, string.Empty, _stopwatch.Elapsed.TotalMilliseconds);
            return true;
        }
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
                if (!TryReceiveOnePayload(receivePollTimeoutMs, out RawPayload latestPayload))
                {
                    continue;
                }

                // 第二步：非阻塞 drain 队列，始终只保留最后一条（最新）消息。
                while (TryReceiveOnePayload(0, out RawPayload newerPayload))
                {
                    latestPayload = newerPayload;
                }

                lock (_lock)
                {
                    _latestPayload = latestPayload;
                    _hasNewPayload = true;
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

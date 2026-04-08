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
    public byte[][] Parts { get; }
    public string Topic { get; }
    public double TimestampMs { get; }

    public RawPayload(byte[][] parts, string topic, double timestampMs)
    {
        Parts = parts;
        Topic = topic;
        TimestampMs = timestampMs;
    }
}

[Serializable]
public class RawPayloadEvent : UnityEvent<RawPayload> { }

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
    [SerializeField] private string topic = "payload";
    [SerializeField] private int receiveHighWatermark = 1;
    [SerializeField] private int socketLingerMs = 0;
    [SerializeField] private int receivePollTimeoutMs = 100;

    private SubscriberSocket _socket;
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

        _socket = new SubscriberSocket();
        _socket.Options.ReceiveHighWatermark = receiveHighWatermark;
        _socket.Options.Linger = TimeSpan.FromMilliseconds(socketLingerMs);
        _socket.Connect(ServerAddress);
        _socket.Subscribe(useTopic ? topic : string.Empty);

        _running = true;
        _receiveThread = new Thread(ReceiveLoop) { IsBackground = true };
        _receiveThread.Start();

        string subscribeDesc = useTopic ? $"topic: {topic}" : "topic: <none>";
        Debug.Log($"[PayloadReceiver] Connected to {ServerAddress}, {subscribeDesc}");
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

                NetMQMessage message = new NetMQMessage();
                if (!_socket.TryReceiveMultipartMessage(TimeSpan.FromMilliseconds(receivePollTimeoutMs), ref message))
                {
                    continue;
                }

                int minFrames = useTopic ? 2 : 1;
                if (message.FrameCount < minFrames)
                {
                    continue;
                }

                int startFrame = useTopic ? 1 : 0;
                string receivedTopic = useTopic ? message[0].ConvertToString() : string.Empty;

                int payloadCount = message.FrameCount - startFrame;
                byte[][] payloadParts = new byte[payloadCount][];
                for (int i = 0; i < payloadCount; i++)
                {
                    payloadParts[i] = message[startFrame + i].ToByteArray();
                }

                double timestampMs = _stopwatch.Elapsed.TotalMilliseconds;
                lock (_lock)
                {
                    _latestPayload = new RawPayload(payloadParts, receivedTopic, timestampMs);
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

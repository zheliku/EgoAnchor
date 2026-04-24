using System;
using System.Collections;
using NetMQ;
using NetMQ.Sockets;
using Proxima;
using RuntimeInspectorNamespace;
using UnityEngine;
using VInspector;

/// <summary>
/// Unity 侧通用 Payload 发送器。
///
/// 设计目标：
/// - 将业务编码（Encoder）与网络发送（Sender）解耦。
/// - 以固定帧率循环发送，网络拥塞时允许丢帧，优先实时性。
/// - 支持服务器地址持久化与运行中切换。
/// </summary>
public class PayloadSender : MonoBehaviour
{
    private const string SenderIPPrefKey = "PayloadSender.ServerIP";
    private const string SenderPortPrefKey = "PayloadSender.ServerPort";
    private const string SenderSendTopicPrefKey = "PayloadSender.SendTopic";
    private const string SenderUseTopicLegacyPrefKey = "PayloadSender.UseTopic";
    private const string SenderDefaultTopicPrefKey = "PayloadSender.DefaultTopic";
    private const string TargetFpsPrefKey = "PayloadSender.TargetFps";
    private const string LogIntervalPrefKey = "PayloadSender.LogInterval";
    private const string SendHighWatermarkPrefKey = "PayloadSender.SendHighWatermark";
    private const string SocketLingerMsPrefKey = "PayloadSender.SocketLingerMs";

    [SerializeField] private BaseEncoder payloadEncoder;
    [SerializeField] private string serverIP = "127.0.0.1";
    [SerializeField] private int serverPort = 5557;
    [SerializeField] private bool sendTopic = false;
    [SerializeField] private string defaultTopic = "quest_stereo";
    [SerializeField] private int targetFps = 60;
    [SerializeField] private int logInterval = 30;
    [SerializeField] private int sendHighWatermark = 1;
    [SerializeField] private int socketLingerMs = 0;

    private NetMQSocket _socket;
    private Coroutine _sendCoroutine;
    private bool _hasWarnedTopicEmpty;

    private int _sentFrameCount;
    private int _droppedFrameCount;
    private int _lastStatTotal;
    private int _lastStatSent;
    private double _lastStatTime;
    private double _encodeTimeAcc;
    private double _sendTimeAcc;

    private string Endpoint => $"tcp://{serverIP}:{serverPort}";

    /// <summary>
    /// 初始化事件并自动查找同对象编码器。
    /// </summary>
    private void Awake()
    {
        if (payloadEncoder == null)
        {
            payloadEncoder = GetComponent<BaseEncoder>();
        }

        LoadConfig();
    }

    [Button("Load Config")]
    [RuntimeInspectorButton("Load Config", false, ButtonVisibility.InitializedObjects)]
    [ProximaButton("Load Config")]
    private void LoadConfig()
    {
        serverIP = PlayerPrefs.GetString(SenderIPPrefKey, serverIP);
        serverPort = PlayerPrefs.GetInt(SenderPortPrefKey, serverPort);
        if (PlayerPrefs.HasKey(SenderSendTopicPrefKey))
        {
            sendTopic = PlayerPrefs.GetInt(SenderSendTopicPrefKey, sendTopic ? 1 : 0) != 0;
        }
        else
        {
            // 兼容历史配置键名（PayloadSender.UseTopic）。
            sendTopic = PlayerPrefs.GetInt(SenderUseTopicLegacyPrefKey, sendTopic ? 1 : 0) != 0;
        }
        defaultTopic = PlayerPrefs.GetString(SenderDefaultTopicPrefKey, defaultTopic);
        targetFps = PlayerPrefs.GetInt(TargetFpsPrefKey, targetFps);
        logInterval = PlayerPrefs.GetInt(LogIntervalPrefKey, logInterval);
        sendHighWatermark = PlayerPrefs.GetInt(SendHighWatermarkPrefKey, sendHighWatermark);
        socketLingerMs = PlayerPrefs.GetInt(SocketLingerMsPrefKey, socketLingerMs);
    }

    [Button("Save Config")]
    [RuntimeInspectorButton("Save Config", false, ButtonVisibility.InitializedObjects)]
    [ProximaButton("Save Config")]
    private void SaveConfig()
    {
        PlayerPrefs.SetString(SenderIPPrefKey, serverIP);
        PlayerPrefs.SetInt(SenderPortPrefKey, serverPort);
        PlayerPrefs.SetInt(SenderSendTopicPrefKey, sendTopic ? 1 : 0);
        PlayerPrefs.SetString(SenderDefaultTopicPrefKey, defaultTopic);
        PlayerPrefs.SetInt(TargetFpsPrefKey, targetFps);
        PlayerPrefs.SetInt(LogIntervalPrefKey, logInterval);
        PlayerPrefs.SetInt(SendHighWatermarkPrefKey, sendHighWatermark);
        PlayerPrefs.SetInt(SocketLingerMsPrefKey, socketLingerMs);
        PlayerPrefs.Save();
    }

    /// <summary>
    /// 地址变更时的重连入口。
    /// </summary>
    [Button("Reconnect")]
    [RuntimeInspectorButton("Reconnect", false, ButtonVisibility.InitializedObjects)]
    [ProximaButton("Reconnect")]
    private void Reconnect()
    {
        DisconnectSocket();
        Connect();
    }

    /// <summary>
    /// 启动发送循环。
    /// 若未配置编码器则中止，并打印错误。
    /// </summary>
    private IEnumerator Start()
    {
        if (payloadEncoder == null)
        {
            Debug.LogError("[PayloadSender] Payload encoder is not assigned.");
            yield break;
        }

        string modeDesc = sendTopic ? $"PUB(topic={defaultTopic})" : "PUSH";
        Debug.Log($"[PayloadSender] RuntimeConfig endpoint={Endpoint}, mode={modeDesc}, targetFps={targetFps}, sendHWM={sendHighWatermark}, lingerMs={socketLingerMs}, encoder={(payloadEncoder != null ? payloadEncoder.GetType().Name : "null")}");
        if (sendHighWatermark > 1)
        {
            Debug.LogWarning($"[PayloadSender] sendHighWatermark={sendHighWatermark} (>1) 可能引入排队延迟。低延迟链路建议设置为 1。", this);
        }
        if (targetFps > 20)
        {
            Debug.LogWarning($"[PayloadSender] targetFps={targetFps} 偏高。若下游仅 6~10 FPS，建议把发送帧率降到 8~12 以避免排队和陈旧帧。", this);
        }

        Connect();
        _lastStatTime = Time.realtimeSinceStartupAsDouble;
        _sendCoroutine = StartCoroutine(SendLoop());
    }

    /// <summary>
    /// 建立发送连接（PUSH 或 PUB）。
    /// HWM=1：仅保留极少积压，降低延迟尾部。
    /// </summary>
    private void Connect()
    {
        if (_socket != null)
        {
            return;
        }

        AsyncIO.ForceDotNet.Force();

        // 统一协议：
        // - sendTopic=false -> PUSH（单帧）
        // - sendTopic=true  -> PUB（multipart: [topic, payload]）
        _socket = sendTopic ? new PublisherSocket() : new PushSocket();
        _socket.Options.SendHighWatermark = sendHighWatermark;
        _socket.Options.Linger = TimeSpan.FromMilliseconds(socketLingerMs);
        _socket.Connect(Endpoint);

        string modeDesc = sendTopic ? $"PUB(topic={defaultTopic})" : "PUSH";
        Debug.Log($"[PayloadSender] Connected to {Endpoint}, mode={modeDesc}");
    }

    /// <summary>
    /// 关闭并释放 socket。
    /// </summary>
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
    /// 固定帧率发送循环。
    ///
    /// 流程：
    /// 1) 从 Encoder 拉取单帧 payload。
    /// 2) 非阻塞发送单帧。
    /// 3) 成功计数 sent，失败计数 dropped。
    ///
    /// 说明：失败（TrySend 返回 false）通常表示网络拥塞。
    /// 此处选择丢帧，不回退重试，以维持实时感。
    /// </summary>
    private IEnumerator SendLoop()
    {
        while (true)
        {
            double frameStart = Time.realtimeSinceStartupAsDouble;

            if (payloadEncoder == null)
            {
                yield return null;
                continue;
            }

            double encodeStart = Time.realtimeSinceStartupAsDouble;
            bool encoded = payloadEncoder.TryEncodePayload(out byte[] payload) &&
                           payload != null && payload.Length > 0;
            _encodeTimeAcc += Time.realtimeSinceStartupAsDouble - encodeStart;

            if (encoded && _socket != null)
            {
                double sendStart = Time.realtimeSinceStartupAsDouble;
                bool sent;
                if (sendTopic)
                {
                    // topic 模式下使用 multipart。若 topic 为空则丢帧并告警，避免发出不可筛选的脏数据。
                    if (string.IsNullOrWhiteSpace(defaultTopic))
                    {
                        if (!_hasWarnedTopicEmpty)
                        {
                            _hasWarnedTopicEmpty = true;
                            Debug.LogWarning("[PayloadSender] sendTopic=true 但 defaultTopic 为空，当前帧已丢弃。", this);
                        }
                        sent = false;
                    }
                    else
                    {
                        NetMQMessage message = new NetMQMessage();
                        message.Append(defaultTopic);
                        message.Append(payload);
                        sent = _socket.TrySendMultipartMessage(TimeSpan.Zero, message);
                    }
                }
                else
                {
                    sent = _socket.TrySendFrame(TimeSpan.Zero, payload);
                }
                _sendTimeAcc += Time.realtimeSinceStartupAsDouble - sendStart;

                if (sent)
                {
                    _sentFrameCount++;
                }
                else
                {
                    _droppedFrameCount++;
                }

                int total = _sentFrameCount + _droppedFrameCount;
                if (logInterval > 0 && total > 0 && total % logInterval == 0)
                {
                    double now = Time.realtimeSinceStartupAsDouble;
                    double intervalSec = now - _lastStatTime;
                    int deltaTotal = total - _lastStatTotal;
                    int deltaSent = _sentFrameCount - _lastStatSent;

                    float actualFps = intervalSec > 0d ? (float)(deltaSent / intervalSec) : 0f;
                    float dropRate = deltaTotal > 0 ? (float)(deltaTotal - deltaSent) / deltaTotal : 0f;
                    float avgEncodeMs = deltaTotal > 0 ? (float)(_encodeTimeAcc / deltaTotal * 1000d) : 0f;
                    float avgSendMs = deltaTotal > 0 ? (float)(_sendTimeAcc / deltaTotal * 1000d) : 0f;

                    Debug.Log($"[PayloadSender] Sent={_sentFrameCount}, Dropped={_droppedFrameCount}, ActualFPS={actualFps:F1}, DropRate={dropRate:P1}, Encode={avgEncodeMs:F2}ms, NetSend={avgSendMs:F3}ms, Interval={intervalSec:F2}s");

                    _lastStatTime = now;
                    _lastStatTotal = total;
                    _lastStatSent = _sentFrameCount;
                    _encodeTimeAcc = 0d;
                    _sendTimeAcc = 0d;
                }
            }

            float targetIntervalSeconds = 1f / Mathf.Max(1, targetFps);
            float elapsedSeconds = (float)(Time.realtimeSinceStartupAsDouble - frameStart);
            float remainingSeconds = targetIntervalSeconds - elapsedSeconds;

            if (remainingSeconds > 0f)
            {
                yield return new WaitForSecondsRealtime(remainingSeconds);
            }
            else
            {
                yield return null;
            }
        }
    }

    /// <summary>
    /// 统一回收协程与网络资源。
    /// </summary>
    private void Cleanup()
    {
        if (_sendCoroutine != null)
        {
            StopCoroutine(_sendCoroutine);
            _sendCoroutine = null;
        }

        if (_socket != null)
        {
            DisconnectSocket();
        }
    }

    /// <summary>
    /// 对象销毁时清理网络资源。
    /// </summary>
    private void OnDestroy()
    {
        Cleanup();
        NetMQConfig.Cleanup(false);
    }

    /// <summary>
    /// 应用退出时清理网络资源。
    /// </summary>
    private void OnApplicationQuit()
    {
        Cleanup();
    }
}

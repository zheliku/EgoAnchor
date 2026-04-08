using System;
using UnityEngine;
using UnityEngine.Events;

/// <summary>
/// 原始字节数据
/// 可用于图像、深度或任何字节流数据
/// </summary>
[Serializable]
public struct RawData
{
    [SerializeField] private byte[] data;
    [SerializeField] private double timestampMs;

    public byte[] Data => data;
    public double TimestampMs => timestampMs;

    public RawData(byte[] data, double timestampMs)
    {
        this.data = data;
        this.timestampMs = timestampMs;
    }
}

/// <summary>
/// 原始字节数据事件（图像、深度通用）
/// </summary>
[Serializable]
public class RawDataEvent : UnityEvent<RawData> { }

/// <summary>
/// RGBD 协议解码器。
///
/// 输入协议：
/// - parts[0] = color_jpg
/// - parts[1] = depth_png
///
/// 使用方式：
/// - 在 PayloadReceiver 的 OnPayloadReceived 事件中，绑定本类 OnPayloadReceived。
/// - 本类再对外发出 OnImageReceived / OnDepthReceived。
/// </summary>
public class RGBDDecoder : BaseDecoder
{
    [Header("Events")]
    [Tooltip("当收到图像数据时触发")]
    public RawDataEvent OnImageReceived = new RawDataEvent();

    [Tooltip("当收到深度数据时触发")]
    public RawDataEvent OnDepthReceived = new RawDataEvent();

    /// <summary>
    /// 初始化事件实例，避免序列化异常导致空引用。
    /// </summary>
    private void Awake()
    {
        if (OnImageReceived == null)
            OnImageReceived = new RawDataEvent();
        if (OnDepthReceived == null)
            OnDepthReceived = new RawDataEvent();
    }

    /// <summary>
    /// Receiver 事件回调入口：解析 payload 并派发图像/深度事件。
    /// </summary>
    public override void OnPayloadReceived(RawPayload payload)
    {
        byte[][] parts = payload.Parts;
        if (parts == null || parts.Length != 2)
        {
            return;
        }

        OnImageReceived?.Invoke(new RawData(parts[0], payload.TimestampMs));
        OnDepthReceived?.Invoke(new RawData(parts[1], payload.TimestampMs));
    }
}

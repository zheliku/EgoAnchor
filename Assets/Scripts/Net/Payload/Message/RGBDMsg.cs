using System;
using UnityEngine;
using UnityEngine.Events;

/// <summary>
/// RGBD 完整消息：单条消息同时包含彩色图与深度图。
/// </summary>
[Serializable]
public struct RGBDMsg
{
    [SerializeField] private byte[] colorImage; // 彩色图编码字节（通常为 JPG）。
    [SerializeField] private byte[] depthImage; // 深度图编码字节（通常为 PNG）。
    [SerializeField] private double timestampMs; // 该条消息对应的接收时间戳（毫秒）。

    public byte[] ColorImage => colorImage; // 彩色图数据。
    public byte[] DepthImage => depthImage; // 深度图数据。
    public double TimestampMs => timestampMs; // 时间戳（毫秒）。

    public RGBDMsg(byte[] colorImage, byte[] depthImage, double timestampMs)
    {
        this.colorImage = colorImage;
        this.depthImage = depthImage;
        this.timestampMs = timestampMs;
    }
}

/// <summary>
/// RGBDMsg 对外事件类型。
/// </summary>
[Serializable]
public class RGBDMsgEvent : UnityEvent<RGBDMsg> { }

using System;
using MessagePack;
using UnityEngine;
using UnityEngine.Events;

/// <summary>
/// RGBD MessagePack 消息：单条消息同时包含彩色图与深度图。
/// </summary>
[Serializable]
[MessagePackObject]
public class RGBDMsg
{
    [Key("color_image")]
    [SerializeField] public byte[] color_image; // 彩色图编码字节（通常为 JPG）。

    [Key("depth_image")]
    [SerializeField] public byte[] depth_image; // 深度图编码字节（通常为 PNG）。

    [Key("timestamp_ms")]
    [SerializeField] public double timestamp_ms; // 该条消息对应的时间戳（毫秒）。

    public RGBDMsg()
    {
    }

    public RGBDMsg(byte[] colorImage, byte[] depthImage, double timestampMs)
    {
        color_image = colorImage;
        depth_image = depthImage;
        timestamp_ms = timestampMs;
    }

    public byte[] Serialize()
    {
        if (color_image == null || depth_image == null)
        {
            return null;
        }

        return MessagePackSerializer.Serialize(this);
    }

    public static RGBDMsg Deserialize(byte[] payload)
    {
        if (payload == null || payload.Length == 0)
        {
            return null;
        }

        try
        {
            RGBDMsg message = MessagePackSerializer.Deserialize<RGBDMsg>(payload);
            if (message == null || message.color_image == null || message.depth_image == null)
            {
                return null;
            }

            return message;
        }
        catch
        {
            return null;
        }
    }
}

/// <summary>
/// RGBDMsg 对外事件类型。
/// </summary>
[Serializable]
public class RGBDMsgEvent : UnityEvent<RGBDMsg> { }

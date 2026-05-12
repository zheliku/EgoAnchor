using System;
using MessagePack;

/// <summary>
/// Quest 双目 MessagePack 传输消息。
///
/// C# 侧使用 PascalCase 属性保持本地代码风格；[Key("...")] 中的 snake_case
/// 是真实网络协议字段名，必须与 Python QuestStereoMsg 和 protocol_contract.json 保持一致。
/// </summary>
[Serializable]
[MessagePackObject]
public class QuestStereoMsg
{
    [Key("left_image_jpeg")]
    public byte[] LeftImageJpeg { get; set; } // 左目 JPEG 图像字节。

    [Key("right_image_jpeg")]
    public byte[] RightImageJpeg { get; set; } // 右目 JPEG 图像字节。

    [Key("frame_id")]
    public long FrameId { get; set; } // 发送端帧号（用于检测丢帧与延迟）。
    [Key("sender_mono_ms")]
    public double SenderMonoMs { get; set; } // 发送端单调时钟（毫秒）。
    [Key("unity_frame")]
    public int UnityFrame { get; set; } // Unity 的 Time.frameCount。

    // 将消息序列化为 MessagePack 负载。
    public byte[] Serialize()
    {
        // 新协议要求左右图都存在，避免接收侧出现“半帧”状态。
        if (LeftImageJpeg == null || LeftImageJpeg.Length == 0)
        {
            return null;
        }

        if (RightImageJpeg == null || RightImageJpeg.Length == 0)
        {
            return null;
        }
        return MessagePackSerializer.Serialize(this);
    }

    // 反序列化 MessagePack 负载。
    public static QuestStereoMsg Deserialize(byte[] payload)
    {
        if (payload == null || payload.Length == 0)
        {
            return null;
        }

        try
        {
            QuestStereoMsg message = MessagePackSerializer.Deserialize<QuestStereoMsg>(payload);
            if (message == null)
            {
                return null;
            }

            if (message.LeftImageJpeg == null || message.LeftImageJpeg.Length == 0)
            {
                return null;
            }

            if (message.RightImageJpeg == null || message.RightImageJpeg.Length == 0)
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

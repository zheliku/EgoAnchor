using System;
using MessagePack;

/// <summary>
/// Quest 双目 MessagePack 传输消息。
/// </summary>
[Serializable]
[MessagePackObject]
public class QuestStereoMsg
{
    [Key("image_jpeg")]
    public byte[] image_jpeg; // 左右拼接后的单张 JPEG 图像字节。

    [Key("frame_id")]
    public long frame_id; // 发送端帧号（用于检测丢帧与延迟）。
    [Key("sender_mono_ms")]
    public double sender_mono_ms; // 发送端单调时钟（毫秒）。
    [Key("unity_frame")]
    public int unity_frame; // Unity 的 Time.frameCount。

    // 将消息序列化为 MessagePack 负载。
    public byte[] Serialize()
    {
        if (image_jpeg == null || image_jpeg.Length == 0)
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
            if (message == null || message.image_jpeg == null || message.image_jpeg.Length == 0)
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

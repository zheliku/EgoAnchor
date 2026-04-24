using System;
using MessagePack;

/// <summary>
/// Quest 双目 MessagePack 传输消息。
/// </summary>
[Serializable]
[MessagePackObject]
public class QuestStereoMsg
{
    [Key("left_image_jpeg")]
    public byte[] left_image_jpeg; // 左目 JPEG 图像字节。

    [Key("right_image_jpeg")]
    public byte[] right_image_jpeg; // 右目 JPEG 图像字节。

    [Key("frame_id")]
    public long frame_id; // 发送端帧号（用于检测丢帧与延迟）。
    [Key("sender_mono_ms")]
    public double sender_mono_ms; // 发送端单调时钟（毫秒）。
    [Key("unity_frame")]
    public int unity_frame; // Unity 的 Time.frameCount。

    // 将消息序列化为 MessagePack 负载。
    public byte[] Serialize()
    {
        // 新协议要求左右图都存在，避免接收侧出现“半帧”状态。
        if (left_image_jpeg == null || left_image_jpeg.Length == 0)
        {
            return null;
        }

        if (right_image_jpeg == null || right_image_jpeg.Length == 0)
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

            if (message.left_image_jpeg == null || message.left_image_jpeg.Length == 0)
            {
                return null;
            }

            if (message.right_image_jpeg == null || message.right_image_jpeg.Length == 0)
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

using System;
using System.Globalization;
using System.Text;

/// <summary>
/// Quest 双目传输消息：包含完整发送内容（图像 + 元数据）。
/// </summary>
[Serializable]
public class QuestStereoMsg
{
    public byte[] left_image; // 左目编码图像字节（Dual 模式使用）。
    public byte[] right_image; // 右目编码图像字节（Dual 模式使用）。
    public byte[] packed_image; // 左右拼接后的编码图像字节（Packed 模式使用）。
    public bool is_packed; // 是否为 Packed 发送模式。

    public long frame_id; // 发送端帧号（用于检测丢帧与延迟）。
    public double sender_mono_ms; // 发送端单调时钟（毫秒）。
    public int unity_frame; // Unity 的 Time.frameCount。

    // 将完整消息转换为发送 payload 的 multipart 数组。
    public byte[][] ToPayloadParts(bool includeMetadata)
    {
        if (is_packed)
        {
            if (packed_image == null || packed_image.Length == 0)
            {
                return null;
            }

            if (!includeMetadata)
            {
                return new[] { packed_image };
            }

            return new[] { packed_image, ToMetadataJsonBytes() };
        }

        if (left_image == null || right_image == null || left_image.Length == 0 || right_image.Length == 0)
        {
            return null;
        }

        if (!includeMetadata)
        {
            return new[] { left_image, right_image };
        }

        return new[] { left_image, right_image, ToMetadataJsonBytes() };
    }

    // 将元数据编码为 JSON 字节（UTF-8）。
    public byte[] ToMetadataJsonBytes()
    {
        string json = "{"
            + "\"frame_id\":" + frame_id.ToString(CultureInfo.InvariantCulture) + ","
            + "\"sender_mono_ms\":" + sender_mono_ms.ToString(CultureInfo.InvariantCulture) + ","
            + "\"unity_frame\":" + unity_frame.ToString(CultureInfo.InvariantCulture)
            + "}";

        return Encoding.UTF8.GetBytes(json);
    }
}

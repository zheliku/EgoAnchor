using System;
using MessagePack;

/// <summary>
/// Quest 相机静态信息 MessagePack 传输消息。
///
/// 包含左右目全部标定参数，由 Unity 端低频发送，Python 端缓存后长期使用。
/// C# 属性使用 PascalCase；[Key("...")] 中的 snake_case 才是网络字段名，
/// 必须与 Python 侧 QuestCameraInfoMsg 和 protocol_contract.json 严格一致。
/// </summary>
[Serializable]
[MessagePackObject]
public class QuestCameraInfoMsg
{
    // 设备支持状态。
    [Key("is_supported")] public bool IsSupported { get; set; }

    // 左目内参。
    [Key("left_fx")] public double LeftFx { get; set; }
    [Key("left_fy")] public double LeftFy { get; set; }
    [Key("left_cx")] public double LeftCx { get; set; }
    [Key("left_cy")] public double LeftCy { get; set; }

    // 右目内参。
    [Key("right_fx")] public double RightFx { get; set; }
    [Key("right_fy")] public double RightFy { get; set; }
    [Key("right_cx")] public double RightCx { get; set; }
    [Key("right_cy")] public double RightCy { get; set; }

    // 畸变系数（Quest 通常为空）。
    [Key("left_distortion")] public float[] LeftDistortion { get; set; }
    [Key("right_distortion")] public float[] RightDistortion { get; set; }

    // 双目基线。
    [Key("baseline_m")] public double BaselineM { get; set; }

    // 传感器分辨率。
    [Key("sensor_width")] public int SensorWidth { get; set; }
    [Key("sensor_height")] public int SensorHeight { get; set; }

    // 有效阵列区域（activeArraySize）。
    [Key("active_left")] public int ActiveLeft { get; set; }
    [Key("active_top")] public int ActiveTop { get; set; }
    [Key("active_right")] public int ActiveRight { get; set; }
    [Key("active_bottom")] public int ActiveBottom { get; set; }

    // 请求分辨率（RequestedResolution，Unity 侧配置）。
    [Key("left_requested_width")] public int LeftRequestedWidth { get; set; }
    [Key("left_requested_height")] public int LeftRequestedHeight { get; set; }
    [Key("right_requested_width")] public int RightRequestedWidth { get; set; }
    [Key("right_requested_height")] public int RightRequestedHeight { get; set; }

    // 当前运行分辨率（CurrentResolution，实际输出）。
    [Key("current_width")] public int CurrentWidth { get; set; }
    [Key("current_height")] public int CurrentHeight { get; set; }

    // 帧率。
    [Key("max_framerate")] public int MaxFramerate { get; set; }

    // 左目镜头偏移（Intrinsics.LensOffset）。
    [Key("left_lens_offset_px")] public double LeftLensOffsetPx { get; set; }
    [Key("left_lens_offset_py")] public double LeftLensOffsetPy { get; set; }
    [Key("left_lens_offset_pz")] public double LeftLensOffsetPz { get; set; }
    [Key("left_lens_offset_qx")] public double LeftLensOffsetQx { get; set; }
    [Key("left_lens_offset_qy")] public double LeftLensOffsetQy { get; set; }
    [Key("left_lens_offset_qz")] public double LeftLensOffsetQz { get; set; }
    [Key("left_lens_offset_qw")] public double LeftLensOffsetQw { get; set; }

    // 右目镜头偏移。
    [Key("right_lens_offset_px")] public double RightLensOffsetPx { get; set; }
    [Key("right_lens_offset_py")] public double RightLensOffsetPy { get; set; }
    [Key("right_lens_offset_pz")] public double RightLensOffsetPz { get; set; }
    [Key("right_lens_offset_qx")] public double RightLensOffsetQx { get; set; }
    [Key("right_lens_offset_qy")] public double RightLensOffsetQy { get; set; }
    [Key("right_lens_offset_qz")] public double RightLensOffsetQz { get; set; }
    [Key("right_lens_offset_qw")] public double RightLensOffsetQw { get; set; }

    // 发送端时间戳。
    [Key("sender_mono_ms")] public double SenderMonoMs { get; set; }

    /// <summary>
    /// 序列化为 MessagePack 字节。
    /// </summary>
    public byte[] Serialize()
    {
        return MessagePackSerializer.Serialize(this);
    }

    /// <summary>
    /// 从 MessagePack 字节反序列化。
    /// </summary>
    public static QuestCameraInfoMsg Deserialize(byte[] payload)
    {
        if (payload == null || payload.Length == 0)
        {
            return null;
        }

        try
        {
            return MessagePackSerializer.Deserialize<QuestCameraInfoMsg>(payload);
        }
        catch
        {
            return null;
        }
    }
}

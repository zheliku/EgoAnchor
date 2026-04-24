using System;
using MessagePack;

/// <summary>
/// Quest 相机静态信息 MessagePack 传输消息。
///
/// 包含左右目全部标定参数，由 Unity 端低频发送，Python 端缓存后长期使用。
/// 字段命名与 Python 侧 QuestCameraInfoMsg 严格一致。
/// </summary>
[Serializable]
[MessagePackObject]
public class QuestCameraInfoMsg
{
    // 设备支持状态。
    [Key("is_supported")] public bool is_supported;

    // 左目内参。
    [Key("left_fx")] public double left_fx;
    [Key("left_fy")] public double left_fy;
    [Key("left_cx")] public double left_cx;
    [Key("left_cy")] public double left_cy;

    // 右目内参。
    [Key("right_fx")] public double right_fx;
    [Key("right_fy")] public double right_fy;
    [Key("right_cx")] public double right_cx;
    [Key("right_cy")] public double right_cy;

    // 畸变系数（Quest 通常为空）。
    [Key("left_distortion")] public float[] left_distortion;
    [Key("right_distortion")] public float[] right_distortion;

    // 双目基线。
    [Key("baseline_m")] public double baseline_m;

    // 传感器分辨率。
    [Key("sensor_width")] public int sensor_width;
    [Key("sensor_height")] public int sensor_height;

    // 有效阵列区域（activeArraySize）。
    [Key("active_left")] public int active_left;
    [Key("active_top")] public int active_top;
    [Key("active_right")] public int active_right;
    [Key("active_bottom")] public int active_bottom;

    // 请求分辨率（RequestedResolution，Unity 侧配置）。
    [Key("left_requested_width")] public int left_requested_width;
    [Key("left_requested_height")] public int left_requested_height;
    [Key("right_requested_width")] public int right_requested_width;
    [Key("right_requested_height")] public int right_requested_height;

    // 当前运行分辨率（CurrentResolution，实际输出）。
    [Key("current_width")] public int current_width;
    [Key("current_height")] public int current_height;

    // 帧率。
    [Key("max_framerate")] public int max_framerate;

    // 左目镜头偏移（Intrinsics.LensOffset）。
    [Key("left_lens_offset_px")] public double left_lens_offset_px;
    [Key("left_lens_offset_py")] public double left_lens_offset_py;
    [Key("left_lens_offset_pz")] public double left_lens_offset_pz;
    [Key("left_lens_offset_qx")] public double left_lens_offset_qx;
    [Key("left_lens_offset_qy")] public double left_lens_offset_qy;
    [Key("left_lens_offset_qz")] public double left_lens_offset_qz;
    [Key("left_lens_offset_qw")] public double left_lens_offset_qw;

    // 右目镜头偏移。
    [Key("right_lens_offset_px")] public double right_lens_offset_px;
    [Key("right_lens_offset_py")] public double right_lens_offset_py;
    [Key("right_lens_offset_pz")] public double right_lens_offset_pz;
    [Key("right_lens_offset_qx")] public double right_lens_offset_qx;
    [Key("right_lens_offset_qy")] public double right_lens_offset_qy;
    [Key("right_lens_offset_qz")] public double right_lens_offset_qz;
    [Key("right_lens_offset_qw")] public double right_lens_offset_qw;

    // 发送端时间戳。
    [Key("sender_mono_ms")] public double sender_mono_ms;

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

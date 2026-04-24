using Meta.XR;
using UnityEngine;

/// <summary>
/// Quest 相机静态信息编码器。
///
/// 输入：左右 PassthroughCameraAccess。
/// 输出：单帧 payload（MessagePack，包含 QuestCameraInfoMsg 全部字段）。
///
/// 特性：
/// - 仅当相机信息发生变化时重新编码，避免无谓序列化开销。
/// - 相机静态信息通常不变，因此绝大部分帧复用缓存 payload。
/// </summary>
public class QuestCameraInfoEncoder : BaseEncoder
{
    [SerializeField] private PassthroughCameraAccess leftCameraAccess;
    [SerializeField] private PassthroughCameraAccess rightCameraAccess;

    // 缓存上次编码的 payload 和消息摘要，避免重复编码。
    private byte[] _cachedPayload;
    private string _cachedDigest;

    /// <summary>
    /// 从 Quest 左右相机读取静态信息并编码为单帧 payload。
    /// </summary>
    public override bool TryEncodePayload(out byte[] payload)
    {
        payload = null;

        if (leftCameraAccess == null || rightCameraAccess == null)
        {
            return false;
        }

        if (!leftCameraAccess.IsPlaying || !rightCameraAccess.IsPlaying)
        {
            return false;
        }

        // 构造消息并生成摘要，仅在内容变化时重新编码。
        QuestCameraInfoMsg msg = BuildMessage();
        string digest = ComputeDigest(msg);

        if (digest == _cachedDigest && _cachedPayload != null)
        {
            payload = _cachedPayload;
            return true;
        }

        payload = msg.Serialize();
        if (payload == null || payload.Length == 0)
        {
            return false;
        }

        _cachedDigest = digest;
        _cachedPayload = payload;
        return true;
    }

    /// <summary>
    /// 从 PassthroughCameraAccess 构造 QuestCameraInfoMsg。
    /// </summary>
    private QuestCameraInfoMsg BuildMessage()
    {
        PassthroughCameraAccess.CameraIntrinsics leftIntr = leftCameraAccess.Intrinsics;
        PassthroughCameraAccess.CameraIntrinsics rightIntr = rightCameraAccess.Intrinsics;
        Vector2Int leftRes = leftCameraAccess.CurrentResolution;
        Vector2Int rightRes = rightCameraAccess.CurrentResolution;

        // 使用左目传感器分辨率作为传感器尺寸基准。
        // Quest 左右目传感器分辨率通常一致。
        int sWidth = leftIntr.SensorResolution.x;
        int sHeight = leftIntr.SensorResolution.y;

        // 基线：左右镜头偏移位置之间的距离。
        float baseline = Vector3.Distance(
            leftIntr.LensOffset.position,
            rightIntr.LensOffset.position
        );

        return new QuestCameraInfoMsg
        {
            is_supported = PassthroughCameraAccess.IsSupported,
            left_fx = leftIntr.FocalLength.x,
            left_fy = leftIntr.FocalLength.y,
            left_cx = leftIntr.PrincipalPoint.x,
            left_cy = leftIntr.PrincipalPoint.y,
            right_fx = rightIntr.FocalLength.x,
            right_fy = rightIntr.FocalLength.y,
            right_cx = rightIntr.PrincipalPoint.x,
            right_cy = rightIntr.PrincipalPoint.y,
            left_distortion = new float[0],
            right_distortion = new float[0],
            baseline_m = baseline,
            sensor_width = sWidth,
            sensor_height = sHeight,
            // activeArraySize：当前使用 SensorResolution 作为有效区域（Quest 通常无裁剪）。
            active_left = 0,
            active_top = 0,
            active_right = sWidth,
            active_bottom = sHeight,
            left_requested_width = leftCameraAccess.RequestedResolution.x,
            left_requested_height = leftCameraAccess.RequestedResolution.y,
            right_requested_width = rightCameraAccess.RequestedResolution.x,
            right_requested_height = rightCameraAccess.RequestedResolution.y,
            current_width = leftRes.x,
            current_height = leftRes.y,
            max_framerate = leftCameraAccess.MaxFramerate,
            // 左目镜头偏移。
            left_lens_offset_px = leftIntr.LensOffset.position.x,
            left_lens_offset_py = leftIntr.LensOffset.position.y,
            left_lens_offset_pz = leftIntr.LensOffset.position.z,
            left_lens_offset_qx = leftIntr.LensOffset.rotation.x,
            left_lens_offset_qy = leftIntr.LensOffset.rotation.y,
            left_lens_offset_qz = leftIntr.LensOffset.rotation.z,
            left_lens_offset_qw = leftIntr.LensOffset.rotation.w,
            // 右目镜头偏移。
            right_lens_offset_px = rightIntr.LensOffset.position.x,
            right_lens_offset_py = rightIntr.LensOffset.position.y,
            right_lens_offset_pz = rightIntr.LensOffset.position.z,
            right_lens_offset_qx = rightIntr.LensOffset.rotation.x,
            right_lens_offset_qy = rightIntr.LensOffset.rotation.y,
            right_lens_offset_qz = rightIntr.LensOffset.rotation.z,
            right_lens_offset_qw = rightIntr.LensOffset.rotation.w,
            sender_mono_ms = Time.realtimeSinceStartupAsDouble * 1000.0,
        };
    }

    /// <summary>
    /// 计算消息摘要，用于判断相机信息是否变化。
    /// 仅使用关键数值字段拼接，避免全字段序列化开销。
    /// </summary>
    private static string ComputeDigest(QuestCameraInfoMsg msg)
    {
        return $"{msg.left_fx:F2}_{msg.left_fy:F2}_{msg.left_cx:F2}_{msg.left_cy:F2}_"
             + $"{msg.right_fx:F2}_{msg.right_fy:F2}_{msg.right_cx:F2}_{msg.right_cy:F2}_"
             + $"{msg.baseline_m:F6}_{msg.sensor_width}_{msg.sensor_height}_"
             + $"{msg.left_requested_width}x{msg.left_requested_height}_"
             + $"{msg.current_width}_{msg.current_height}_{msg.max_framerate}";
    }
}

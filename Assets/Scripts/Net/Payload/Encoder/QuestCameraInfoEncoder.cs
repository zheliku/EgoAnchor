using Meta.XR;
using UnityEngine;

/// <summary>
/// Quest 相机静态信息编码器。
///
/// 输入：左右 PassthroughCameraAccess。
/// 输出：单帧 payload（MessagePack，包含 QuestCameraInfoMsg 全部字段）。
///
/// 特性：
/// - 每次发送都会刷新 sender_mono_ms，保证 Python 侧收到的是本次发送时间戳。
/// - 相机静态信息本身通常不变，发送频率由 PayloadSender 的 targetFps 控制。
/// </summary>
public class QuestCameraInfoEncoder : PayloadEncoder
{
    [SerializeField] private PassthroughCameraAccess leftCameraAccess;
    [SerializeField] private PassthroughCameraAccess rightCameraAccess;

    /// <summary>
    /// 从 Quest 左右相机读取静态信息并编码为单帧 payload。
    /// </summary>
    public override bool TryEncode(out byte[] payload)
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

        QuestCameraInfoMsg msg = BuildMessage();
        payload = msg.Serialize();
        if (payload == null || payload.Length == 0)
        {
            return false;
        }

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
}


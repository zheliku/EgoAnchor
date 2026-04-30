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

    // camera_info 是低频静态消息，但启动阶段引用/播放状态异常很常见；
    // 这里保留限频统计，方便定位“Python 一直等标定”的问题，同时避免日志刷屏。
    private int _failCamNullCount;
    private int _failNotPlayingCount;
    private int _failSerializeNullCount;
    private float _lastFailLogTime;

    /// <summary>
    /// 从 Quest 左右相机读取静态信息并编码为单帧 payload。
    /// </summary>
    public override bool TryEncode(out byte[] payload)
    {
        payload = null;

        if (leftCameraAccess == null || rightCameraAccess == null)
        {
            _failCamNullCount++;
            MaybeLogFailure();
            return false;
        }

        if (!leftCameraAccess.IsPlaying || !rightCameraAccess.IsPlaying)
        {
            _failNotPlayingCount++;
            MaybeLogFailure();
            return false;
        }

        QuestCameraInfoMsg msg = BuildMessage();
        payload = msg.Serialize();
        if (payload == null || payload.Length == 0)
        {
            _failSerializeNullCount++;
            MaybeLogFailure();
            return false;
        }

        return true;
    }

    private void MaybeLogFailure()
    {
        float now = Time.realtimeSinceStartup;
        if (now - _lastFailLogTime < 2.0f)
        {
            return;
        }

        _lastFailLogTime = now;
        Debug.LogWarning(
            $"[QuestCameraInfoEncoder] TryEncode failures in last 2s: " +
            $"CamNull={_failCamNullCount}, NotPlaying={_failNotPlayingCount}, " +
            $"SerializeNull={_failSerializeNullCount}. " +
            $"LeftPlaying={(leftCameraAccess != null && leftCameraAccess.IsPlaying)}, " +
            $"RightPlaying={(rightCameraAccess != null && rightCameraAccess.IsPlaying)}.",
            this
        );
        _failCamNullCount = 0;
        _failNotPlayingCount = 0;
        _failSerializeNullCount = 0;
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
            IsSupported = PassthroughCameraAccess.IsSupported,
            LeftFx = leftIntr.FocalLength.x,
            LeftFy = leftIntr.FocalLength.y,
            LeftCx = leftIntr.PrincipalPoint.x,
            LeftCy = leftIntr.PrincipalPoint.y,
            RightFx = rightIntr.FocalLength.x,
            RightFy = rightIntr.FocalLength.y,
            RightCx = rightIntr.PrincipalPoint.x,
            RightCy = rightIntr.PrincipalPoint.y,
            LeftDistortion = new float[0],
            RightDistortion = new float[0],
            BaselineM = baseline,
            SensorWidth = sWidth,
            SensorHeight = sHeight,
            // activeArraySize：当前使用 SensorResolution 作为有效区域（Quest 通常无裁剪）。
            ActiveLeft = 0,
            ActiveTop = 0,
            ActiveRight = sWidth,
            ActiveBottom = sHeight,
            LeftRequestedWidth = leftCameraAccess.RequestedResolution.x,
            LeftRequestedHeight = leftCameraAccess.RequestedResolution.y,
            RightRequestedWidth = rightCameraAccess.RequestedResolution.x,
            RightRequestedHeight = rightCameraAccess.RequestedResolution.y,
            CurrentWidth = leftRes.x,
            CurrentHeight = leftRes.y,
            MaxFramerate = leftCameraAccess.MaxFramerate,
            // 左目镜头偏移。
            LeftLensOffsetPx = leftIntr.LensOffset.position.x,
            LeftLensOffsetPy = leftIntr.LensOffset.position.y,
            LeftLensOffsetPz = leftIntr.LensOffset.position.z,
            LeftLensOffsetQx = leftIntr.LensOffset.rotation.x,
            LeftLensOffsetQy = leftIntr.LensOffset.rotation.y,
            LeftLensOffsetQz = leftIntr.LensOffset.rotation.z,
            LeftLensOffsetQw = leftIntr.LensOffset.rotation.w,
            // 右目镜头偏移。
            RightLensOffsetPx = rightIntr.LensOffset.position.x,
            RightLensOffsetPy = rightIntr.LensOffset.position.y,
            RightLensOffsetPz = rightIntr.LensOffset.position.z,
            RightLensOffsetQx = rightIntr.LensOffset.rotation.x,
            RightLensOffsetQy = rightIntr.LensOffset.rotation.y,
            RightLensOffsetQz = rightIntr.LensOffset.rotation.z,
            RightLensOffsetQw = rightIntr.LensOffset.rotation.w,
            SenderMonoMs = Time.realtimeSinceStartupAsDouble * 1000.0,
        };
    }
}


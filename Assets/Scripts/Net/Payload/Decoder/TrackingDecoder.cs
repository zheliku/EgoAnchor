using System;
using System.Globalization;
using UnityEngine;
using UnityEngine.Events;
using Debug = UnityEngine.Debug;

/// <summary>
/// Tracking 阶段枚举。
/// </summary>
public enum TrackingPhase
{
    Detecting = 0,
    Tracking = 1
}

/// <summary>
/// Tracking 协议解码器。
///
/// 输入协议：
/// - parts[0] = phase_byte (0/1)
/// - parts[1] = color_jpg
/// - parts[2] = pose_json（可空）
///
/// 输出事件：
/// - OnImageReceived: 每帧图像
/// - OnPoseReceived: 仅在 pose 有效时触发
/// - OnTrackingStarted / OnTrackingLost: 阶段切换事件
/// </summary>
public class TrackingDecoder : BaseDecoder
{
    [Header("Events")]
    [Tooltip("当收到图像数据时触发")]
    public RawDataEvent OnImageReceived = new RawDataEvent();

    [Tooltip("当收到位姿数据时触发")]
    public PoseDataEvent OnPoseReceived = new PoseDataEvent();

    [Tooltip("当从检测切换到追踪时触发")]
    public UnityEvent OnTrackingStarted = new UnityEvent();

    [Tooltip("当追踪丢失时触发")]
    public UnityEvent OnTrackingLost = new UnityEvent();

    private TrackingPhase _lastPhase = TrackingPhase.Detecting;

    public TrackingPhase CurrentPhase => _lastPhase;

    /// <summary>
    /// 初始化事件实例，避免序列化异常导致空引用。
    /// </summary>
    private void Awake()
    {
        if (OnImageReceived == null)
            OnImageReceived = new RawDataEvent();
        if (OnPoseReceived == null)
            OnPoseReceived = new PoseDataEvent();
        if (OnTrackingStarted == null)
            OnTrackingStarted = new UnityEvent();
        if (OnTrackingLost == null)
            OnTrackingLost = new UnityEvent();
    }

    /// <summary>
    /// Receiver 事件回调入口：解析 tracking payload 并按业务语义派发。
    /// </summary>
    public override void OnPayloadReceived(RawPayload payload)
    {
        byte[][] payloadParts = payload.Parts;

        if (payloadParts == null || payloadParts.Length != 3)
        {
            return;
        }

        TrackingPhase phase = payloadParts[0].Length > 0 && payloadParts[0][0] == 1
            ? TrackingPhase.Tracking
            : TrackingPhase.Detecting;

        byte[] colorData = payloadParts[1];
        byte[] poseData = payloadParts[2];

        Matrix4x4? poseMatrix = null;
        if (poseData != null && poseData.Length > 0)
        {
            string poseJson = System.Text.Encoding.UTF8.GetString(poseData);
            if (!string.IsNullOrWhiteSpace(poseJson))
            {
                poseMatrix = ParsePoseMatrix(poseJson);
                if (poseMatrix == null)
                {
                    return;
                }
            }
        }

        if (_lastPhase == TrackingPhase.Detecting && phase == TrackingPhase.Tracking)
        {
            OnTrackingStarted?.Invoke();
        }
        else if (_lastPhase == TrackingPhase.Tracking && phase == TrackingPhase.Detecting)
        {
            OnTrackingLost?.Invoke();
        }

        _lastPhase = phase;

        OnImageReceived?.Invoke(new RawData(colorData, payload.TimestampMs));

        PoseData pose = new PoseData(poseMatrix);
        if (pose.HasPose)
        {
            OnPoseReceived?.Invoke(pose);
        }
    }

    /// <summary>
    /// 从 pose JSON 中提取 4x4 矩阵。
    /// 解析失败返回 null（调用方会跳过该帧）。
    /// </summary>
    private static Matrix4x4? ParsePoseMatrix(string json)
    {
        try
        {
            int matrixStart = json.IndexOf("[[", StringComparison.Ordinal);
            int matrixEnd = json.LastIndexOf("]]", StringComparison.Ordinal);
            if (matrixStart == -1 || matrixEnd == -1)
            {
                return null;
            }

            string matrixStr = json.Substring(matrixStart + 1, matrixEnd - matrixStart);
            string[] rows = matrixStr.Split(new[] { "], [", "],[" }, StringSplitOptions.None);
            if (rows.Length != 4)
            {
                return null;
            }

            Matrix4x4 matrix = new Matrix4x4();
            for (int row = 0; row < 4; row++)
            {
                string rowStr = rows[row].Trim('[', ']', ' ');
                string[] values = rowStr.Split(',');
                if (values.Length != 4)
                {
                    return null;
                }

                for (int col = 0; col < 4; col++)
                {
                    if (!float.TryParse(
                        values[col].Trim(),
                        NumberStyles.Float,
                        CultureInfo.InvariantCulture,
                        out float val))
                    {
                        return null;
                    }

                    matrix[row, col] = val;
                }
            }

            return matrix;
        }
        catch (Exception e)
        {
            Debug.LogWarning($"[TrackingDecoder] Failed to parse pose matrix: {e.Message}");
            return null;
        }
    }
}

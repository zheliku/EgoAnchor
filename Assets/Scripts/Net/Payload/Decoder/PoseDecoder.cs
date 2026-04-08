using System;
using System.Globalization;
using System.Text;
using UnityEngine;
using UnityEngine.Events;

/// <summary>
/// 位姿数据
/// </summary>
[Serializable]
public struct PoseData
{
    [SerializeField] private Matrix4x4 poseMatrix;
    [SerializeField] private bool hasPose;

    public Matrix4x4? PoseMatrix => hasPose ? poseMatrix : null;
    public bool HasPose => hasPose;

    public PoseData(Matrix4x4? matrix)
    {
        if (matrix.HasValue)
        {
            poseMatrix = matrix.Value;
            hasPose = true;
        }
        else
        {
            poseMatrix = Matrix4x4.identity;
            hasPose = false;
        }
    }
}

/// <summary>
/// 位姿数据事件
/// </summary>
[Serializable]
public class PoseDataEvent : UnityEvent<PoseData> { }

/// <summary>
/// Pose JSON 协议解码器。
///
/// 输入协议（topic 后第 1 帧）：
/// {
///   "has_pose": true/false,
///   "pose_matrix": [[...4x4...]]
/// }
///
/// 输出事件：
/// - OnPoseReceived：当 pose 有效时触发。
/// </summary>
public class PoseDecoder : BaseDecoder
{
    [Header("Events")]
    public PoseDataEvent OnPoseReceived = new PoseDataEvent();

    private void Awake()
    {
        if (OnPoseReceived == null)
        {
            OnPoseReceived = new PoseDataEvent();
        }
    }

    public override void OnPayloadReceived(RawPayload payload)
    {
        if (payload.Parts == null || payload.Parts.Length < 1 || payload.Parts[0] == null)
        {
            return;
        }

        string json = Encoding.UTF8.GetString(payload.Parts[0]);
        if (string.IsNullOrWhiteSpace(json))
        {
            return;
        }

        if (!TryReadHasPose(json, out bool hasPose) || !hasPose)
        {
            return;
        }

        if (!TryParsePoseMatrix(json, out Matrix4x4 poseMatrix))
        {
            return;
        }

        OnPoseReceived?.Invoke(new PoseData(poseMatrix));
    }

    private static bool TryReadHasPose(string json, out bool hasPose)
    {
        hasPose = false;
        int keyIndex = json.IndexOf("\"has_pose\"", StringComparison.Ordinal);
        if (keyIndex < 0)
        {
            return false;
        }

        int colonIndex = json.IndexOf(':', keyIndex);
        if (colonIndex < 0)
        {
            return false;
        }

        int valueStart = colonIndex + 1;
        while (valueStart < json.Length && char.IsWhiteSpace(json[valueStart]))
        {
            valueStart++;
        }

        if (valueStart + 4 <= json.Length &&
            string.Compare(json, valueStart, "true", 0, 4, StringComparison.OrdinalIgnoreCase) == 0)
        {
            hasPose = true;
            return true;
        }

        if (valueStart + 5 <= json.Length &&
            string.Compare(json, valueStart, "false", 0, 5, StringComparison.OrdinalIgnoreCase) == 0)
        {
            hasPose = false;
            return true;
        }

        return false;
    }

    private static bool TryParsePoseMatrix(string json, out Matrix4x4 matrix)
    {
        matrix = Matrix4x4.identity;

        int keyIndex = json.IndexOf("\"pose_matrix\"", StringComparison.Ordinal);
        if (keyIndex < 0)
        {
            return false;
        }

        int matrixStart = json.IndexOf("[[", keyIndex, StringComparison.Ordinal);
        int matrixEnd = json.IndexOf("]]", matrixStart, StringComparison.Ordinal);
        if (matrixStart < 0 || matrixEnd < 0)
        {
            return false;
        }

        string matrixText = json.Substring(matrixStart + 1, matrixEnd - matrixStart);
        string[] rows = matrixText.Split(new[] { "], [", "],[" }, StringSplitOptions.None);
        if (rows.Length != 4)
        {
            return false;
        }

        for (int row = 0; row < 4; row++)
        {
            string[] values = rows[row].Trim('[', ']', ' ').Split(',');
            if (values.Length != 4)
            {
                return false;
            }

            for (int col = 0; col < 4; col++)
            {
                if (!float.TryParse(values[col].Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out float value))
                {
                    return false;
                }

                matrix[row, col] = value;
            }
        }

        return true;
    }
}

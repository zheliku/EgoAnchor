using System;
using UnityEngine;
using UnityEngine.Events;

/// <summary>
/// 运行时位姿业务结构：用于场景内组件传递，不属于网络传输 schema。
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
/// PoseData 对外事件类型。
/// </summary>
[Serializable]
public class PoseDataEvent : UnityEvent<PoseData> { }

/// <summary>
/// Pose 协议解码器。
///
/// 输入 MessagePack 至少包含：
/// - "has_pose": bool
/// - "pose_matrix_flat": 长度 16 的位姿矩阵展平数组（当 has_pose=true 时）
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
        if (payload.Payload == null || payload.Payload.Length == 0)
        {
            return;
        }

        PoseMsg message = PoseMsg.Deserialize(payload.Payload);
        if (message == null || !message.has_pose)
        {
            return;
        }

        if (!message.TryGetPoseMatrix(out Matrix4x4 poseMatrix))
        {
            return;
        }

        OnPoseReceived?.Invoke(new PoseData(poseMatrix));
    }
}

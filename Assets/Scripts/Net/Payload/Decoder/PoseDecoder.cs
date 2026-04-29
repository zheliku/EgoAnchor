using System;
using UnityEngine;
using UnityEngine.Events;

/// <summary>
/// Pose 对外事件类型。
/// </summary>
[Serializable]
public class PoseReceivedEvent : UnityEvent<Pose, long> { }

/// <summary>
/// Pose 协议解码器。
///
/// 输入 MessagePack 至少包含：
/// - "has_pose": bool
/// - "pose_matrix_flat": 长度 16 的位姿矩阵展平数组（当 has_pose=true 时）
///
/// 输出事件：
/// - OnPoseReceived：当 pose 有效时触发（参数：pose, frame_id）。
/// </summary>
public class PoseDecoder : PayloadDecoder
{
    [Header("Coordinate Mapping")]
    [Tooltip("输入位姿若来自 OpenCV 相机坐标（x右/y下/z前），勾选后自动转换到 Unity 坐标（x右/y上/z前）。")]
    [SerializeField] private bool convertFromOpenCvCamera = true;

    [Header("Events")]
    public PoseReceivedEvent OnPoseReceived = new PoseReceivedEvent();

    private void Awake()
    {
        if (OnPoseReceived == null)
        {
            OnPoseReceived = new PoseReceivedEvent();
        }
    }

    public override void HandlePayload(RawPayload payload)
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

        if (!message.TryGetPose(out Pose pose))
        {
            return;
        }

        if (convertFromOpenCvCamera)
        {
            if (!TryConvertOpenCvPoseToUnity(pose, out Pose convertedPose))
            {
                return;
            }

            pose = convertedPose;
        }

        OnPoseReceived?.Invoke(pose, message.frame_id);
    }

    private static bool TryConvertOpenCvPoseToUnity(Pose inputPose, out Pose outputPose)
    {
        Vector3 forwardInput = inputPose.rotation * Vector3.forward;
        Vector3 forward = new Vector3(forwardInput.x, -forwardInput.y, forwardInput.z);
        // 等价于 M * R * M（M=diag(1,-1,1)）中的右乘 M 对 up 轴的影响。
        Vector3 upInput = inputPose.rotation * Vector3.down;
        Vector3 up = new Vector3(upInput.x, -upInput.y, upInput.z);
        if (forward.sqrMagnitude < 1e-12f || up.sqrMagnitude < 1e-12f)
        {
            outputPose = Pose.identity;
            return false;
        }

        Vector3 position = inputPose.position;
        outputPose = new Pose(
            new Vector3(position.x, -position.y, position.z),
            Quaternion.LookRotation(forward, up)
        );
        return true;
    }
}


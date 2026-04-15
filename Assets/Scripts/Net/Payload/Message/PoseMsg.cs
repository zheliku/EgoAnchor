using System;
using MessagePack;
using UnityEngine;

/// <summary>
/// Pose MessagePack 传输结构（Unity/Python 共享字段约定）。
///
/// 规范：
/// - 消息类统一以 Msg 结尾。
/// - 每个消息只保留一个类型定义，不再拆分出独立 timing 类型。
/// </summary>
[Serializable]
[MessagePackObject]
public class PoseMsg
{
    [Key("timestamp_ms")]
    public double timestamp_ms; // 该条位姿消息的时间戳（毫秒）。
    [Key("frame_id")]
    public long frame_id; // 对应输入双目帧号（用于 Unity 本地对齐发送时参考位姿）。
    [Key("stage")]
    public int stage; // Pipeline 阶段编号。
    [Key("phase")]
    public string phase; // 阶段名称（例如 REGISTER / TRACK）。
    [Key("det_count")]
    public int det_count; // 检测目标数量。
    [Key("depth_valid_ratio")]
    public float depth_valid_ratio; // 深度有效像素占比（0~1）。
    [Key("fps")]
    public float fps; // 实时帧率。

    [Key("has_pose")]
    public bool has_pose; // 是否有可用位姿。
    [Key("pose_matrix_flat")]
    public float[] pose_matrix_flat; // 位姿矩阵展平后的 16 个元素（行优先）。

    [Key("yolo_ms")]
    public float yolo_ms; // YOLO 阶段耗时（毫秒）。
    [Key("depth_ms")]
    public float depth_ms; // 深度估计阶段耗时（毫秒）。
    [Key("cutie_ms")]
    public float cutie_ms; // Cutie 阶段耗时（毫秒）。
    [Key("pose_ms")]
    public float pose_ms; // 位姿估计阶段耗时（毫秒）。

    public byte[] Serialize()
    {
        return MessagePackSerializer.Serialize(this);
    }

    public static PoseMsg Deserialize(byte[] payload)
    {
        if (payload == null || payload.Length == 0)
        {
            return null;
        }

        try
        {
            PoseMsg message = MessagePackSerializer.Deserialize<PoseMsg>(payload);
            if (message == null)
            {
                return null;
            }

            if (message.has_pose && (message.pose_matrix_flat == null || message.pose_matrix_flat.Length != 16))
            {
                return null;
            }

            return message;
        }
        catch
        {
            return null;
        }
    }

    public bool TryGetPose(out Pose pose)
    {
        pose = Pose.identity;
        if (!has_pose)
        {
            return false;
        }

        if (pose_matrix_flat == null || pose_matrix_flat.Length != 16)
        {
            return false;
        }

        Vector3 forward = new Vector3(
            pose_matrix_flat[2],
            pose_matrix_flat[6],
            pose_matrix_flat[10]
        );
        Vector3 up = new Vector3(
            pose_matrix_flat[1],
            pose_matrix_flat[5],
            pose_matrix_flat[9]
        );
        if (forward.sqrMagnitude < 1e-12f || up.sqrMagnitude < 1e-12f)
        {
            return false;
        }

        pose = new Pose(
            new Vector3(
                pose_matrix_flat[3],
                pose_matrix_flat[7],
                pose_matrix_flat[11]
            ),
            Quaternion.LookRotation(forward, up)
        );
        return true;
    }
}

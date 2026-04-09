using System;
using UnityEngine;

/// <summary>
/// Pose JSON 传输结构（Unity/Python 共享字段约定）。
///
/// 规范：
/// - 消息类统一以 Msg 结尾。
/// - 每个消息只保留一个类型定义，不再拆分出独立 timing 类型。
///
/// 兼容：
/// - 位姿优先使用 pose_matrix_flat（长度 16，行优先）。
/// - timing 字段使用扁平字段 yolo_ms/depth_ms/cutie_ms/pose_ms。
/// </summary>
[Serializable]
public class PoseMsg
{
    public double timestamp_ms; // 该条位姿消息的时间戳（毫秒）。
    public int stage; // Pipeline 阶段编号。
    public string phase; // 阶段名称（例如 REGISTER / TRACK）。
    public int det_count; // 检测目标数量。
    public float depth_valid_ratio; // 深度有效像素占比（0~1）。
    public float fps; // 实时帧率。

    public bool has_pose; // 是否有可用位姿。
    public float[] pose_matrix_flat; // 位姿矩阵展平后的 16 个元素（行优先）。

    public float yolo_ms; // YOLO 阶段耗时（毫秒）。
    public float depth_ms; // 深度估计阶段耗时（毫秒）。
    public float cutie_ms; // Cutie 阶段耗时（毫秒）。
    public float pose_ms; // 位姿估计阶段耗时（毫秒）。

    public bool TryGetPoseMatrix(out Matrix4x4 matrix)
    {
        matrix = Matrix4x4.identity;
        if (!has_pose)
        {
            return false;
        }

        if (pose_matrix_flat == null || pose_matrix_flat.Length != 16)
        {
            return false;
        }

        matrix.m00 = pose_matrix_flat[0];
        matrix.m01 = pose_matrix_flat[1];
        matrix.m02 = pose_matrix_flat[2];
        matrix.m03 = pose_matrix_flat[3];
        matrix.m10 = pose_matrix_flat[4];
        matrix.m11 = pose_matrix_flat[5];
        matrix.m12 = pose_matrix_flat[6];
        matrix.m13 = pose_matrix_flat[7];
        matrix.m20 = pose_matrix_flat[8];
        matrix.m21 = pose_matrix_flat[9];
        matrix.m22 = pose_matrix_flat[10];
        matrix.m23 = pose_matrix_flat[11];
        matrix.m30 = pose_matrix_flat[12];
        matrix.m31 = pose_matrix_flat[13];
        matrix.m32 = pose_matrix_flat[14];
        matrix.m33 = pose_matrix_flat[15];
        return true;
    }
}

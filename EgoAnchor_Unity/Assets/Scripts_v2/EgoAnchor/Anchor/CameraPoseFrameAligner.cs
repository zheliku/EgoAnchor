using EgoAnchor.Protocol.V1;
using EgoAnchor.V2.Quest;
using UnityEngine;
using ProtoMatrix4x4 = EgoAnchor.Protocol.V1.Matrix4x4;

namespace EgoAnchor.V2.Anchor
{
    /// <summary>
    /// camera-space pose -> Unity world anchor pose 的 frame-aligned 转换器。
    ///
    /// 后续将从 Quest.FramePoseHistory 中按 frame_id 查找“采集该帧时”的左目 camera world pose，
    /// 再把 Python 输出的 OpenCV camera pose（x 右、y 下、z 前）转换为 Unity camera-local pose（x 右、y 上、z 前），
    /// 最后映射到 Unity world raw anchor pose。
    ///
    /// 这相当于把旧链路中的 PoseDecoder + FrameAlignedObjectAnchor 的关键逻辑正式拆分出来，
    /// 是 v2 frame-aligned real-object anchoring 的核心模块。
    /// </summary>
    public sealed class CameraPoseFrameAligner
    {
        private readonly FramePoseHistory _framePoseHistory;

        /// <summary>
        /// 构造 frame aligner。FramePoseHistory 由 Quest stereo 发送侧维护。
        /// </summary>
        public CameraPoseFrameAligner(FramePoseHistory framePoseHistory)
        {
            _framePoseHistory = framePoseHistory;
        }

        /// <summary>
        /// 按 frame_id 对齐并输出 world pose。
        /// </summary>
        public bool TryAlign(PoseResult poseResult, out Pose worldPose)
        {
            worldPose = default;
            if (poseResult == null || poseResult.Header == null || !poseResult.HasPose)
            {
                return false;
            }

            if (!TryReadOpenCvCameraPose(poseResult.PoseMatrixCvCamera, out Pose cvCameraPose))
            {
                return false;
            }

            return TryAlign(poseResult.Header.FrameId, cvCameraPose, out worldPose);
        }

        /// <summary>
        /// 已解出 camera-local pose 时，按 frame_id 对齐到 Unity world。
        /// </summary>
        public bool TryAlign(long frameId, Pose cvCameraPose, out Pose worldPose)
        {
            worldPose = default;
            if (_framePoseHistory == null)
            {
                return false;
            }

            if (!_framePoseHistory.TryGet(frameId, out FramePoseHistory.Entry entry))
            {
                return false;
            }

            if (!TryConvertOpenCvPoseToUnityCamera(cvCameraPose, out Pose unityCameraLocalPose))
            {
                return false;
            }

            Pose cameraWorldPose = entry.CameraPose;
            worldPose = new Pose(
                cameraWorldPose.position + cameraWorldPose.rotation * unityCameraLocalPose.position,
                cameraWorldPose.rotation * unityCameraLocalPose.rotation
            );
            return true;
        }

        /// <summary>
        /// 从 Protobuf Matrix4x4 读取 OpenCV camera-local pose。
        ///
        /// Python 侧使用 row-major 展平的 4x4 矩阵：
        /// - translation = [3, 7, 11]
        /// - forward     = [2, 6, 10]
        /// - up          = [1, 5, 9]
        /// </summary>
        public static bool TryReadOpenCvCameraPose(ProtoMatrix4x4 matrix, out Pose pose)
        {
            pose = Pose.identity;
            if (matrix == null || matrix.Values == null || matrix.Values.Count != 16)
            {
                return false;
            }

            Vector3 forward = new Vector3(
                (float)matrix.Values[2],
                (float)matrix.Values[6],
                (float)matrix.Values[10]
            );
            Vector3 up = new Vector3(
                (float)matrix.Values[1],
                (float)matrix.Values[5],
                (float)matrix.Values[9]
            );
            if (forward.sqrMagnitude < 1e-12f || up.sqrMagnitude < 1e-12f)
            {
                return false;
            }

            pose = new Pose(
                new Vector3(
                    (float)matrix.Values[3],
                    (float)matrix.Values[7],
                    (float)matrix.Values[11]
                ),
                Quaternion.LookRotation(forward, up)
            );
            return true;
        }

        /// <summary>
        /// OpenCV camera 坐标 -> Unity camera-local 坐标。
        ///
        /// OpenCV: x 右、y 下、z 前；Unity camera local: x 右、y 上、z 前。
        /// 对 position 是 y 取反；对 rotation 等价于 M * R * M，其中 M=diag(1,-1,1)。
        /// 这里用 forward/up 重建 Quaternion，避免直接手写矩阵乘法导致 handedness 错误。
        /// </summary>
        public static bool TryConvertOpenCvPoseToUnityCamera(Pose cvCameraPose, out Pose unityCameraPose)
        {
            Vector3 forwardInput = cvCameraPose.rotation * Vector3.forward;
            Vector3 forward = new Vector3(forwardInput.x, -forwardInput.y, forwardInput.z);

            // 右乘 M 后，Unity 的 up 轴对应 OpenCV pose 中的 down 轴。
            Vector3 upInput = cvCameraPose.rotation * Vector3.down;
            Vector3 up = new Vector3(upInput.x, -upInput.y, upInput.z);
            if (forward.sqrMagnitude < 1e-12f || up.sqrMagnitude < 1e-12f)
            {
                unityCameraPose = Pose.identity;
                return false;
            }

            Vector3 position = cvCameraPose.position;
            unityCameraPose = new Pose(
                new Vector3(position.x, -position.y, position.z),
                Quaternion.LookRotation(forward, up)
            );
            return true;
        }
    }
}

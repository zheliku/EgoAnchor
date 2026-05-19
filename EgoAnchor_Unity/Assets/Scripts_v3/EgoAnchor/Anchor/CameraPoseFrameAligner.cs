using EgoAnchor.V3.Protocol.Generated;
using EgoAnchor.V3.Quest;
using UnityEngine;
using ProtoMatrix4x4 = EgoAnchor.V3.Protocol.Generated.Matrix4x4;

namespace EgoAnchor.V3.Anchor
{
    /// <summary>
    /// camera-space pose -> Unity world anchor pose 的 frame-aligned 转换器。
    ///
    /// Python 发布的是 OpenCV camera 坐标系下的物体 4x4 pose：x 右、y 下、z 前。
    /// Unity 侧必须按 PoseResult.header.frame_id 回查“采集该帧时”的左目 camera world pose，
    /// 再把 OpenCV camera-local pose 转为 Unity camera-local pose，最终映射到 Unity world。
    ///
    /// 本类不订阅网络、不做平滑、不修改 Transform；它只负责可测试的坐标与 frame 对齐逻辑。
    /// </summary>
    public sealed class CameraPoseFrameAligner
    {
        /// <summary>frame_id -> 采集时刻左目 camera world pose 缓存。</summary>
        private readonly FramePoseHistory framePoseHistory;

        /// <summary>
        /// 构造 frame aligner。FramePoseHistory 由 StereoFrameSource 在发送 stereo 时维护。
        /// </summary>
        /// <param name="framePoseHistory">frame_id 到 capture-time camera pose 的环形缓存。</param>
        public CameraPoseFrameAligner(FramePoseHistory framePoseHistory)
        {
            this.framePoseHistory = framePoseHistory;
        }

        /// <summary>
        /// 从 PoseResult 读取 camera-space pose，并按 frame_id 对齐到 Unity world。
        /// </summary>
        /// <param name="poseResult">Python 发布的 camera-space PoseResult。</param>
        /// <param name="worldPose">成功时输出 Unity world pose。</param>
        /// <returns>是否成功得到 world pose。</returns>
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
        /// <param name="frameId">PoseResult 对应的 stereo frame_id。</param>
        /// <param name="cvCameraPose">OpenCV camera 坐标系下的 object pose。</param>
        /// <param name="worldPose">成功时输出 Unity world pose。</param>
        /// <returns>是否成功查询历史 camera pose 并完成坐标转换。</returns>
        public bool TryAlign(long frameId, Pose cvCameraPose, out Pose worldPose)
        {
            worldPose = default;
            if (framePoseHistory == null)
            {
                return false;
            }

            if (!framePoseHistory.TryGet(frameId, out FramePoseRecord record))
            {
                return false;
            }

            if (!TryConvertOpenCvPoseToUnityCamera(cvCameraPose, out Pose unityCameraLocalPose))
            {
                return false;
            }

            Pose cameraWorldPose = record.CameraPose;
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
        /// <param name="matrix">Protobuf 4x4 矩阵。</param>
        /// <param name="pose">成功时输出 OpenCV camera-local pose。</param>
        /// <returns>矩阵是否有效。</returns>
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
        /// <param name="cvCameraPose">OpenCV camera 坐标系下的 object pose。</param>
        /// <param name="unityCameraPose">成功时输出 Unity camera-local pose。</param>
        /// <returns>旋转向量是否有效。</returns>
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

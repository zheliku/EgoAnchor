using EgoAnchor.Protocol.Generated;
using UnityEngine;
using ProtoMatrix4x4 = EgoAnchor.Protocol.Generated.Matrix4x4;

namespace EgoAnchor.Alignment
{
    /// <summary>
    /// camera-space pose -> Unity world anchor pose 的 frame-aligned 转换器。
    ///
    /// Python 发布的是 OpenCV camera 坐标系下的物体 4x4 pose：x 右、y 下、z 前。
    /// Unity 侧必须按 PoseResult.header.frame_id 回查“采集该帧时”的参考 camera world pose，
    /// 再按 AnchorPoseTransform 中配置的 X/Y/Z 轴翻转转换 camera-local pose，最终映射到 Unity world。
    ///
    /// 本类不订阅网络、不做平滑、不修改 Transform；它只负责可测试的坐标与 frame 对齐逻辑。
    /// </summary>
    public sealed class CameraPoseFrameAligner
    {
        /// <summary>frame_id -> 采集时刻 left/right/center camera world pose 缓存。</summary>
        private readonly FramePoseHistory framePoseHistory;

        /// <summary>Inspector/调用方指定的对齐参考相机。</summary>
        private readonly CameraReference alignmentReference;

        /// <summary>camera-local 坐标转换和三路 pose 补偿配置。</summary>
        private readonly AnchorPoseTransform poseTransform;

        /// <summary>
        /// 构造 frame aligner。FramePoseHistory 由 StereoFrameSource 在发送 stereo 时维护。
        /// </summary>
        /// <param name="framePoseHistory">frame_id 到 capture-time left/right/center camera pose 的环形缓存。</param>
        /// <param name="alignmentReference">Unity 本地选择的对齐参考相机。</param>
        /// <param name="poseTransform">camera-local 轴翻转和 camera/anchor/world 三路 pose 补偿配置。</param>
        public CameraPoseFrameAligner(
            FramePoseHistory framePoseHistory,
            CameraReference alignmentReference = CameraReference.Left,
            AnchorPoseTransform? poseTransform = null)
        {
            this.framePoseHistory = framePoseHistory;
            this.alignmentReference = alignmentReference;
            this.poseTransform = poseTransform ?? AnchorPoseTransform.OpenCvToUnityDefault;
        }

        /// <summary>
        /// 从 PoseResult 读取 camera-space pose，并按 frame_id 对齐到 Unity world。
        /// </summary>
        /// <param name="poseResult">Python 发布的 camera-space PoseResult。</param>
        /// <param name="worldPose">成功时输出 Unity world pose。</param>
        /// <returns>是否成功得到 world pose。</returns>
        public bool TryAlign(PoseResult poseResult, out Pose worldPose)
        {
            return TryAlign(poseResult, out worldPose, out _);
        }

        /// <summary>
        /// 从 PoseResult 读取 camera-space pose，并按 frame_id 对齐到 Unity world，同时返回实际使用的参考相机。
        /// </summary>
        /// <param name="poseResult">Python 发布的 camera-space PoseResult。</param>
        /// <param name="worldPose">成功时输出 Unity world pose。</param>
        /// <param name="usedReference">本次用于组合 camera-local pose 的参考相机。</param>
        /// <returns>是否成功得到 world pose。</returns>
        public bool TryAlign(PoseResult poseResult, out Pose worldPose, out CameraReference usedReference)
        {
            worldPose = default;
            usedReference = alignmentReference;
            if (poseResult == null || poseResult.Header == null || !poseResult.HasPose)
            {
                return false;
            }

            if (!TryReadOpenCvCameraPose(poseResult.PoseMatrixCvCamera, out Pose cvCameraPose))
            {
                return false;
            }

            return TryAlign(poseResult.Header.FrameId, cvCameraPose, usedReference, out worldPose);
        }

        /// <summary>
        /// 从 PoseResult 读取 camera-space pose，并使用当前最新 camera pose 做 arrival-time 对照映射。
        /// 该方法只用于 RQ2 时空对齐消融诊断；正式 anchor 仍应使用 TryAlign(frame_id, ...) 的 capture-time 对齐。
        /// </summary>
        /// <param name="poseResult">Python 发布的 camera-space PoseResult。</param>
        /// <param name="worldPose">成功时输出 arrival-time raw world pose。</param>
        /// <param name="usedReference">本次用于组合 camera-local pose 的参考相机。</param>
        /// <param name="cameraRecord">本次使用的最新 camera pose 记录。</param>
        /// <returns>是否成功得到 arrival-time raw world pose。</returns>
        public bool TryAlignWithLatestCameraPose(
            PoseResult poseResult,
            out Pose worldPose,
            out CameraReference usedReference,
            out FramePoseRecord cameraRecord)
        {
            worldPose = default;
            usedReference = alignmentReference;
            cameraRecord = default;
            if (poseResult == null || !poseResult.HasPose)
            {
                return false;
            }

            if (!TryReadOpenCvCameraPose(poseResult.PoseMatrixCvCamera, out Pose cvCameraPose))
            {
                return false;
            }

            if (usedReference == CameraReference.None)
            {
                return TryAlignWithCameraPose(cvCameraPose, Pose.identity, usedReference, out worldPose);
            }

            if (framePoseHistory == null || !framePoseHistory.TryGetLatest(out cameraRecord))
            {
                return false;
            }

            return cameraRecord.TryGetCameraPose(usedReference, out Pose cameraWorldPose)
                && TryAlignWithCameraPose(cvCameraPose, cameraWorldPose, usedReference, out worldPose);
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
            return TryAlign(frameId, cvCameraPose, alignmentReference, out worldPose);
        }

        /// <summary>
        /// 已解出 camera-local pose 时，按指定参考相机和 frame_id 对齐到 Unity world。
        /// </summary>
        /// <param name="frameId">PoseResult 对应的 stereo frame_id。</param>
        /// <param name="cvCameraPose">OpenCV camera 坐标系下的 object pose。</param>
        /// <param name="reference">用于组合 camera-local pose 的采集时刻参考相机。</param>
        /// <param name="worldPose">成功时输出 Unity world pose。</param>
        /// <returns>是否成功完成坐标转换和 frame 对齐。</returns>
        public bool TryAlign(long frameId, Pose cvCameraPose, CameraReference reference, out Pose worldPose)
        {
            worldPose = default;

            if (!poseTransform.TryApplyAxisFlip(cvCameraPose, out Pose unityCameraLocalPose))
            {
                return false;
            }

            unityCameraLocalPose = poseTransform.ApplyCameraLocalOffsets(unityCameraLocalPose);

            if (reference == CameraReference.None)
            {
                worldPose = poseTransform.ApplyFrameAlignedOffsets(unityCameraLocalPose);
                return true;
            }

            if (framePoseHistory == null)
            {
                return false;
            }

            if (!framePoseHistory.TryGet(frameId, out FramePoseRecord record) || !record.TryGetCameraPose(reference, out Pose cameraWorldPose))
            {
                return false;
            }

            Pose alignedWorldPose = new Pose(
                cameraWorldPose.position + cameraWorldPose.rotation * unityCameraLocalPose.position,
                cameraWorldPose.rotation * unityCameraLocalPose.rotation
            );
            worldPose = poseTransform.ApplyFrameAlignedOffsets(alignedWorldPose);
            return true;
        }

        /// <summary>
        /// 已解出 camera-local pose 时，直接使用调用方提供的 camera world pose 组合到 Unity world。
        /// 该方法给 arrival-time raw 诊断复用同一套轴翻转和 offset 逻辑。
        /// </summary>
        /// <param name="cvCameraPose">OpenCV camera 坐标系下的 object pose。</param>
        /// <param name="cameraWorldPose">arrival-time 参考相机 world pose。</param>
        /// <param name="reference">用于诊断记录的参考相机。</param>
        /// <param name="worldPose">成功时输出 Unity world pose。</param>
        /// <returns>是否成功完成坐标转换。</returns>
        public bool TryAlignWithCameraPose(Pose cvCameraPose, Pose cameraWorldPose, CameraReference reference, out Pose worldPose)
        {
            worldPose = default;

            if (!poseTransform.TryApplyAxisFlip(cvCameraPose, out Pose unityCameraLocalPose))
            {
                return false;
            }

            unityCameraLocalPose = poseTransform.ApplyCameraLocalOffsets(unityCameraLocalPose);
            if (reference == CameraReference.None)
            {
                worldPose = poseTransform.ApplyFrameAlignedOffsets(unityCameraLocalPose);
                return true;
            }

            Pose alignedWorldPose = new Pose(
                cameraWorldPose.position + cameraWorldPose.rotation * unityCameraLocalPose.position,
                cameraWorldPose.rotation * unityCameraLocalPose.rotation
            );
            worldPose = poseTransform.ApplyFrameAlignedOffsets(alignedWorldPose);
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
            return AnchorPoseTransform.OpenCvToUnityDefault.TryApplyAxisFlip(cvCameraPose, out unityCameraPose);
        }
    }
}

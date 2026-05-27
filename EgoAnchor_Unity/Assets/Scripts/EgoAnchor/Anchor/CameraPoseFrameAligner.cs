using EgoAnchor.Protocol.Generated;
using EgoAnchor.Quest;
using UnityEngine;
using ProtoMatrix4x4 = EgoAnchor.Protocol.Generated.Matrix4x4;

namespace EgoAnchor.Anchor
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

        /// <summary>camera-local 坐标转换和 frame-aligned 后固定偏移配置。</summary>
        private readonly AnchorPoseTransform poseTransform;

        /// <summary>
        /// 构造 frame aligner。FramePoseHistory 由 StereoFrameSource 在发送 stereo 时维护。
        /// </summary>
        /// <param name="framePoseHistory">frame_id 到 capture-time left/right/center camera pose 的环形缓存。</param>
        /// <param name="alignmentReference">Unity 本地选择的对齐参考相机。</param>
        /// <param name="poseTransform">camera-local 轴翻转和本地固定偏移配置。</param>
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

            usedReference = alignmentReference;
            return TryAlign(poseResult.Header.FrameId, cvCameraPose, usedReference, out worldPose);
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

            if (reference == CameraReference.None)
            {
                worldPose = poseTransform.ApplyFixedOffset(unityCameraLocalPose);
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
            worldPose = poseTransform.ApplyFixedOffset(alignedWorldPose);
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

    /// <summary>
    /// Anchor pose 的本地变换配置。
    ///
    /// 该结构把两类 Unity 侧实验性修正集中到一个 Inspector 区块：
    /// 1. camera-local pose 的 X/Y/Z 轴翻转，用于适配 Python pose 矩阵与 Unity camera-local 约定差异；
    /// 2. frame 对齐后的固定位置/旋转偏移，用于补偿参考相机、模型原点或临时调试误差。
    ///
    /// 结构本身不访问网络、不查询 frame history，只处理单个 Pose 的数学变换，便于复用和测试。
    /// </summary>
    [System.Serializable]
    public struct AnchorPoseTransform
    {
        /// <summary>是否翻转 camera-local X 轴。</summary>
        [Header("Camera Axis Flip")]
        [Tooltip("是否翻转 camera-local X 轴。开启后 position.x 取反，rotation 按 F*R*F 同步变换。")]
        [SerializeField] private bool flipX;

        /// <summary>是否翻转 camera-local Y 轴。</summary>
        [Tooltip("是否翻转 camera-local Y 轴。旧 OpenCV->Unity 默认需要开启；若测试发现不需要 y 翻转，可在运行时取消勾选。")]
        [SerializeField] private bool flipY;

        /// <summary>是否翻转 camera-local Z 轴。</summary>
        [Tooltip("是否翻转 camera-local Z 轴。通常保持关闭，仅用于排查 Python/Unity 前向轴约定不一致。")]
        [SerializeField] private bool flipZ;

        /// <summary>是否应用 frame-aligned 后的固定偏移。</summary>
        [Header("Local Offset")]
        [Tooltip("是否在 frame 对齐后应用固定偏移。关闭时 positionOffset/rotationOffsetEuler 不参与输出。")]
        [SerializeField] private bool applyOffset;

        /// <summary>固定位置偏移，单位米。</summary>
        [Tooltip("固定位置偏移，单位米。offsetInAnchorLocal=true 时按 anchor 局部轴解释；否则按 Unity world 轴解释。")]
        [SerializeField] private Vector3 positionOffset;

        /// <summary>固定旋转偏移，欧拉角度。</summary>
        [Tooltip("固定旋转偏移，欧拉角度。offsetInAnchorLocal=true 时右乘到 anchor rotation；否则左乘到 world rotation。")]
        [SerializeField] private Vector3 rotationOffsetEuler;

        /// <summary>固定偏移是否按 anchor 局部坐标解释。</summary>
        [Tooltip("固定偏移是否按 anchor 局部坐标解释。开启时位置偏移随物体旋转；关闭时按 Unity world 坐标直接平移。")]
        [SerializeField] private bool offsetInAnchorLocal;

        /// <summary>兼容旧 OpenCV camera pose 的默认设置：只翻转 Y 轴，并让偏移默认按 anchor 局部坐标解释。</summary>
        public static AnchorPoseTransform OpenCvToUnityDefault
        {
            get
            {
                AnchorPoseTransform transform = new AnchorPoseTransform
                {
                    flipY = true,
                    offsetInAnchorLocal = true,
                };
                return transform;
            }
        }

        /// <summary>是否翻转 camera-local X 轴。</summary>
        public bool FlipX => flipX;

        /// <summary>是否翻转 camera-local Y 轴。</summary>
        public bool FlipY => flipY;

        /// <summary>是否翻转 camera-local Z 轴。</summary>
        public bool FlipZ => flipZ;

        /// <summary>是否应用 frame-aligned 后的固定偏移。</summary>
        public bool ApplyOffsetEnabled => applyOffset;

        /// <summary>固定位置偏移，单位米。</summary>
        public Vector3 PositionOffset => positionOffset;

        /// <summary>固定旋转偏移，欧拉角度。</summary>
        public Vector3 RotationOffsetEuler => rotationOffsetEuler;

        /// <summary>固定偏移是否按 anchor 局部坐标解释。</summary>
        public bool OffsetInAnchorLocal => offsetInAnchorLocal;

        /// <summary>
        /// 把 legacy 的分散偏移字段迁移到统一结构中。
        /// </summary>
        /// <param name="enabled">是否启用固定偏移。</param>
        /// <param name="position">固定位置偏移，单位米。</param>
        /// <param name="rotationEuler">固定旋转偏移，欧拉角度。</param>
        /// <param name="inAnchorLocal">是否按 anchor 局部坐标解释偏移。</param>
        public void SetOffset(bool enabled, Vector3 position, Vector3 rotationEuler, bool inAnchorLocal)
        {
            applyOffset = enabled;
            positionOffset = position;
            rotationOffsetEuler = rotationEuler;
            offsetInAnchorLocal = inAnchorLocal;
        }

        /// <summary>
        /// 对 camera-local pose 应用 X/Y/Z 轴翻转。
        ///
        /// position 直接按轴符号相乘；rotation 使用 F * R * F 形式，确保翻转父坐标轴和物体局部轴后仍得到合法 Quaternion。
        /// 当 flipY=true、flipX/flipZ=false 时，该方法等价于旧版 OpenCV y-down -> Unity y-up 转换。
        /// </summary>
        /// <param name="inputPose">输入 camera-local pose。</param>
        /// <param name="outputPose">应用轴翻转后的 camera-local pose。</param>
        /// <returns>forward/up 是否足以重建有效旋转。</returns>
        public bool TryApplyAxisFlip(Pose inputPose, out Pose outputPose)
        {
            Vector3 signs = AxisSigns();
            Vector3 forward = Scale(inputPose.rotation * new Vector3(0f, 0f, signs.z), signs);
            Vector3 up = Scale(inputPose.rotation * new Vector3(0f, signs.y, 0f), signs);
            if (forward.sqrMagnitude < 1e-12f || up.sqrMagnitude < 1e-12f)
            {
                outputPose = Pose.identity;
                return false;
            }

            outputPose = new Pose(
                Scale(inputPose.position, signs),
                Quaternion.LookRotation(forward, up)
            );
            return true;
        }

        /// <summary>
        /// 对 frame-aligned Unity world pose 应用固定位置/旋转偏移。
        /// </summary>
        /// <param name="inputPose">frame 对齐后的 Unity world pose。</param>
        /// <returns>应用固定偏移后的 Unity world pose。</returns>
        public Pose ApplyFixedOffset(Pose inputPose)
        {
            if (!applyOffset)
            {
                return inputPose;
            }

            Quaternion offsetRotation = Quaternion.Euler(rotationOffsetEuler);
            if (offsetInAnchorLocal)
            {
                return new Pose(
                    inputPose.position + inputPose.rotation * positionOffset,
                    inputPose.rotation * offsetRotation
                );
            }

            return new Pose(
                inputPose.position + positionOffset,
                offsetRotation * inputPose.rotation
            );
        }

        /// <summary>
        /// 根据 flipX/flipY/flipZ 生成每个轴的符号。
        /// </summary>
        /// <returns>X/Y/Z 轴符号，未翻转为 +1，翻转为 -1。</returns>
        private Vector3 AxisSigns()
        {
            return new Vector3(
                flipX ? -1f : 1f,
                flipY ? -1f : 1f,
                flipZ ? -1f : 1f
            );
        }

        /// <summary>
        /// 按轴符号缩放向量。
        /// </summary>
        /// <param name="value">输入向量。</param>
        /// <param name="signs">X/Y/Z 轴符号。</param>
        /// <returns>逐轴乘以符号后的向量。</returns>
        private static Vector3 Scale(Vector3 value, Vector3 signs)
        {
            return new Vector3(value.x * signs.x, value.y * signs.y, value.z * signs.z);
        }
    }
}


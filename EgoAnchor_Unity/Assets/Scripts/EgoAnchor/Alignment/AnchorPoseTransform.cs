using UnityEngine;

namespace EgoAnchor.Alignment
{
    /// <summary>
    /// Anchor pose 的本地变换配置。
    ///
    /// 该结构把两类 Unity 侧实验性修正集中到一个 Inspector 区块：
    /// 1. camera-local pose 的 X/Y/Z 轴翻转，用于适配 Python pose 矩阵与 Unity camera-local 约定差异；
    /// 2. 三路并行 position/rotation offset，用于分别补偿相机系偏差、anchor 自身 pivot/姿态偏差和 world 固定偏差。
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

        /// <summary>相机局部位置补偿，单位米。</summary>
        [Header("Position Offsets")]
        [Tooltip("相机局部位置补偿，单位米。在 frame alignment 前加到 Unity camera-local pose 上；x 右、y 上、z 前。适合深度或相机系 translation bias。")]
        [SerializeField] private Vector3 cameraLocalPositionOffset;

        /// <summary>anchor 自身局部位置补偿，单位米。</summary>
        [Tooltip("anchor 自身局部位置补偿，单位米。在 frame alignment 后按 anchor rotation 旋转到 world 再相加；会随物体姿态变化。")]
        [SerializeField] private Vector3 anchorLocalPositionOffset;

        /// <summary>Unity world 位置补偿，单位米。</summary>
        [Tooltip("Unity world 位置补偿，单位米。在 frame alignment 后直接按 world xyz 相加；不随头显或物体旋转。")]
        [SerializeField] private Vector3 worldPositionOffset;

        /// <summary>相机局部旋转补偿，欧拉角度。</summary>
        [Header("Rotation Offsets")]
        [Tooltip("相机局部旋转补偿，欧拉角度。在 frame alignment 前左乘到 Unity camera-local rotation；适合相机系姿态 bias。")]
        [SerializeField] private Vector3 cameraLocalRotationOffsetEuler;

        /// <summary>anchor 自身局部旋转补偿，欧拉角度。</summary>
        [Tooltip("anchor 自身局部旋转补偿，欧拉角度。在 frame alignment 后右乘到 anchor rotation；会随物体姿态变化。")]
        [SerializeField] private Vector3 anchorLocalRotationOffsetEuler;

        /// <summary>Unity world 旋转补偿，欧拉角度。</summary>
        [Tooltip("Unity world 旋转补偿，欧拉角度。在 frame alignment 后左乘到 world rotation；不随头显或物体旋转。")]
        [SerializeField] private Vector3 worldRotationOffsetEuler;

        /// <summary>OpenCV camera pose 到 Unity camera-local pose 的默认设置：只翻转 Y 轴。</summary>
        public static AnchorPoseTransform OpenCvToUnityDefault
        {
            get
            {
                AnchorPoseTransform transform = new AnchorPoseTransform
                {
                    flipY = true,
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

        /// <summary>相机局部位置补偿，单位米。</summary>
        public Vector3 CameraLocalPositionOffset => cameraLocalPositionOffset;

        /// <summary>anchor 自身局部位置补偿，单位米。</summary>
        public Vector3 AnchorLocalPositionOffset => anchorLocalPositionOffset;

        /// <summary>Unity world 位置补偿，单位米。</summary>
        public Vector3 WorldPositionOffset => worldPositionOffset;

        /// <summary>相机局部旋转补偿，欧拉角度。</summary>
        public Vector3 CameraLocalRotationOffsetEuler => cameraLocalRotationOffsetEuler;

        /// <summary>anchor 自身局部旋转补偿，欧拉角度。</summary>
        public Vector3 AnchorLocalRotationOffsetEuler => anchorLocalRotationOffsetEuler;

        /// <summary>Unity world 旋转补偿，欧拉角度。</summary>
        public Vector3 WorldRotationOffsetEuler => worldRotationOffsetEuler;

        /// <summary>
        /// 设置三种并行位置补偿。
        /// </summary>
        /// <param name="cameraLocal">相机局部位置补偿，单位米；在 frame alignment 前应用。</param>
        /// <param name="anchorLocal">anchor 自身局部位置补偿，单位米；在 frame alignment 后随物体旋转应用。</param>
        /// <param name="world">Unity world 位置补偿，单位米；在 frame alignment 后直接相加。</param>
        public void SetPositionOffsets(Vector3 cameraLocal, Vector3 anchorLocal, Vector3 world)
        {
            cameraLocalPositionOffset = cameraLocal;
            anchorLocalPositionOffset = anchorLocal;
            worldPositionOffset = world;
        }

        /// <summary>
        /// 设置三种并行旋转补偿。
        /// </summary>
        /// <param name="cameraLocalEuler">相机局部旋转补偿，欧拉角度；在 frame alignment 前左乘。</param>
        /// <param name="anchorLocalEuler">anchor 自身局部旋转补偿，欧拉角度；在 frame alignment 后右乘。</param>
        /// <param name="worldEuler">Unity world 旋转补偿，欧拉角度；在 frame alignment 后左乘。</param>
        public void SetRotationOffsets(Vector3 cameraLocalEuler, Vector3 anchorLocalEuler, Vector3 worldEuler)
        {
            cameraLocalRotationOffsetEuler = cameraLocalEuler;
            anchorLocalRotationOffsetEuler = anchorLocalEuler;
            worldRotationOffsetEuler = worldEuler;
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
        /// 对 Unity camera-local pose 应用相机局部位置和旋转补偿。
        /// </summary>
        /// <param name="inputPose">已完成 OpenCV->Unity 轴转换的 camera-local pose。</param>
        /// <returns>加上 camera-local offset 后的 pose。</returns>
        public Pose ApplyCameraLocalOffsets(Pose inputPose)
        {
            if (cameraLocalPositionOffset == Vector3.zero && cameraLocalRotationOffsetEuler == Vector3.zero)
            {
                return inputPose;
            }

            Quaternion outputRotation = inputPose.rotation;
            if (cameraLocalRotationOffsetEuler != Vector3.zero)
            {
                outputRotation = Multiply(EulerZxy(cameraLocalRotationOffsetEuler), outputRotation);
            }

            return new Pose(inputPose.position + cameraLocalPositionOffset, outputRotation);
        }

        /// <summary>
        /// 对 frame-aligned Unity world pose 应用 anchor-local 和 world 位置/旋转补偿。
        /// </summary>
        /// <param name="inputPose">frame 对齐后的 Unity world pose。</param>
        /// <returns>应用补偿后的 Unity world pose。</returns>
        public Pose ApplyFrameAlignedOffsets(Pose inputPose)
        {
            Vector3 outputPosition = inputPose.position;
            Quaternion outputRotation = inputPose.rotation;
            if (anchorLocalPositionOffset != Vector3.zero)
            {
                outputPosition += inputPose.rotation * anchorLocalPositionOffset;
            }

            if (worldPositionOffset != Vector3.zero)
            {
                outputPosition += worldPositionOffset;
            }

            if (anchorLocalRotationOffsetEuler != Vector3.zero)
            {
                outputRotation = Multiply(outputRotation, EulerZxy(anchorLocalRotationOffsetEuler));
            }

            if (worldRotationOffsetEuler != Vector3.zero)
            {
                outputRotation = Multiply(EulerZxy(worldRotationOffsetEuler), outputRotation);
            }

            return new Pose(outputPosition, outputRotation);
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

        /// <summary>
        /// 按 Unity Quaternion.Euler 语义生成旋转：依次应用 Z、X、Y 轴欧拉角。
        /// </summary>
        /// <param name="eulerDeg">欧拉角度，单位度。</param>
        /// <returns>与 Unity Euler 顺序一致的 Quaternion。</returns>
        private static Quaternion EulerZxy(Vector3 eulerDeg)
        {
            Quaternion z = AxisAngle(new Vector3(0f, 0f, 1f), eulerDeg.z);
            Quaternion x = AxisAngle(new Vector3(1f, 0f, 0f), eulerDeg.x);
            Quaternion y = AxisAngle(new Vector3(0f, 1f, 0f), eulerDeg.y);
            return Normalize(Multiply(y, Multiply(x, z)));
        }

        /// <summary>
        /// 用纯托管数学构造 axis-angle 旋转，避免外部 smoke 调用 Unity ECall。
        /// </summary>
        /// <param name="axis">单位旋转轴。</param>
        /// <param name="degrees">旋转角度，单位度。</param>
        /// <returns>axis-angle 对应的 Quaternion。</returns>
        private static Quaternion AxisAngle(Vector3 axis, float degrees)
        {
            double halfRad = degrees * System.Math.PI / 360.0;
            float sin = (float)System.Math.Sin(halfRad);
            float cos = (float)System.Math.Cos(halfRad);
            return new Quaternion(axis.x * sin, axis.y * sin, axis.z * sin, cos);
        }

        /// <summary>
        /// Quaternion 乘法，顺序与 Unity 的 lhs * rhs 一致。
        /// </summary>
        /// <param name="lhs">左侧旋转。</param>
        /// <param name="rhs">右侧旋转。</param>
        /// <returns>组合后的旋转。</returns>
        private static Quaternion Multiply(Quaternion lhs, Quaternion rhs)
        {
            return new Quaternion(
                lhs.w * rhs.x + lhs.x * rhs.w + lhs.y * rhs.z - lhs.z * rhs.y,
                lhs.w * rhs.y - lhs.x * rhs.z + lhs.y * rhs.w + lhs.z * rhs.x,
                lhs.w * rhs.z + lhs.x * rhs.y - lhs.y * rhs.x + lhs.z * rhs.w,
                lhs.w * rhs.w - lhs.x * rhs.x - lhs.y * rhs.y - lhs.z * rhs.z
            );
        }

        /// <summary>
        /// 归一化 Quaternion，防止多次乘法后累积微小数值误差。
        /// </summary>
        /// <param name="value">待归一化旋转。</param>
        /// <returns>单位 Quaternion。</returns>
        private static Quaternion Normalize(Quaternion value)
        {
            double norm = System.Math.Sqrt(value.x * value.x + value.y * value.y + value.z * value.z + value.w * value.w);
            if (norm <= 1e-12)
            {
                return Quaternion.identity;
            }

            float inv = (float)(1.0 / norm);
            return new Quaternion(value.x * inv, value.y * inv, value.z * inv, value.w * inv);
        }
    }
}

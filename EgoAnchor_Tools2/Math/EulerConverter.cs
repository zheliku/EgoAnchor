namespace EgoAnchor.Tools2.Math
{
    /// <summary>
    /// 四元数到欧拉角 (度) 的转换工具,用于绘图与诊断。
    ///
    /// 仅用于可视化对比,不进入滤波器主路径 (主路径统一用切空间 Log/Exp)。
    /// 采用 ZYX 顺序 (Unity 约定),与 unity_output.jsonl 中的 euler_deg 字段对齐,
    /// 这样画出的 roll/pitch/yaw 曲线可与 Unity 录制值直接对比。
    /// </summary>
    public static class EulerConverter
    {
        /// <summary>
        /// 把归一化四元数转换为 (roll, pitch, yaw) 欧拉角,单位度,范围 [-180, 180]。
        /// 顺序对应 Unity 的 ZXY 内禀旋转。
        /// </summary>
        public static (float roll, float pitch, float yaw) ToEulerDegrees(QuaternionM q)
        {
            QuaternionM n = AnchorMath.Normalize(q);
            float x = n.X, y = n.Y, z = n.Z, w = n.W;

            // roll (x 轴旋转)
            float sinRoll = 2.0f * (w * x + y * z);
            float cosRoll = 1.0f - 2.0f * (x * x + y * y);
            float roll = (float)System.Math.Atan2(sinRoll, cosRoll);

            // pitch (y 轴旋转),处理 gimbal flip
            float sinPitch = 2.0f * (w * y - z * x);
            if (sinPitch > 1.0f) sinPitch = 1.0f;
            else if (sinPitch < -1.0f) sinPitch = -1.0f;
            float pitch = (float)System.Math.Asin(sinPitch);

            // yaw (z 轴旋转)
            float sinYaw = 2.0f * (w * z + x * y);
            float cosYaw = 1.0f - 2.0f * (y * y + z * z);
            float yaw = (float)System.Math.Atan2(sinYaw, cosYaw);

            return (roll * AnchorMath.Rad2Deg, pitch * AnchorMath.Rad2Deg, yaw * AnchorMath.Rad2Deg);
        }
    }
}

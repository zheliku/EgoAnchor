using System;

namespace EgoAnchor.Tools3.Core
{
    /// <summary>
    /// 旋转的可视化表示。
    ///
    /// 关键决定: 录制文件里的 *_euler_deg 用的是 Unity 内部 ZXY 提取, 手工复现会有几度误差,
    /// 且欧拉角本身有 gimbal-lock 跳变, 不适合判断"旋转是否平滑"。
    ///
    /// 因此本工具默认用 **旋转向量 (rotation vector)** 作为旋转曲线:
    ///   rotvec(q) = 2 * Log(q)  (单位: 弧度的轴角向量, 这里转成度)
    /// 它与四元数一一对应 (在 ±180° 内), 无 gimbal lock, 平滑当且仅当旋转平滑,
    /// 正是各 estimator 在切空间里滤波/外推的量。三个分量记为 RotVecX/Y/Z。
    ///
    /// 同时也提供标准 ZXY 欧拉角 (度, [0,360)) 作为参考视图。
    /// </summary>
    public static class Rotation
    {
        private const double Rad2Deg = 180.0 / Math.PI;

        /// <summary>
        /// 旋转向量 (度)。= 轴 * 角度。相对单位四元数, 范围 (-180,180] 每分量。
        /// 注意 Quat.Log 返回半角向量, 所以这里 *2 还原成全角轴角。
        /// </summary>
        public static (double x, double y, double z) ToRotationVectorDegrees(Quat q)
        {
            // 取到与 identity 同半球, 保证连续 (避免 q 与 -q 表示同一旋转却差一个符号)
            Quat aligned = Quat.AlignHemisphere(Quat.Identity, q.Normalized());
            Vec3 half = Quat.Log(aligned); // 半角向量
            return (half.X * 2.0 * Rad2Deg, half.Y * 2.0 * Rad2Deg, half.Z * 2.0 * Rad2Deg);
        }

        /// <summary>
        /// 标准 ZXY 内禀欧拉角 (度, 归一到 [0,360))。仅作参考视图;
        /// 与 Unity Quaternion.eulerAngles 数值可能差几度 (Unity 内部实现差异)。
        /// 返回 (x=pitch, y=yaw, z=roll), 与 Unity 字段顺序一致。
        /// </summary>
        public static (double x, double y, double z) ToEulerZxyDegrees(Quat q)
        {
            Quat n = q.Normalized();
            double x = n.X, y = n.Y, z = n.Z, w = n.W;
            double xx = x * x, yy = y * y, zz = z * z;
            double xy = x * y, xz = x * z, yz = y * z;
            double wx = w * x, wy = w * y, wz = w * z;

            // 旋转矩阵元素 (右手, 列向量约定)
            double m12 = 2 * (xy - wz);
            double m22 = 1 - 2 * (xx + zz);
            double m31 = 2 * (xz - wy);
            double m32 = 2 * (yz + wx);
            double m33 = 1 - 2 * (xx + yy);

            double ex, ey, ez;
            double sinPitch = Math.Min(1.0, Math.Max(-1.0, m32));
            ex = Math.Asin(sinPitch);
            if (Math.Abs(m32) < 0.9999999)
            {
                ey = Math.Atan2(-m31, m33);
                ez = Math.Atan2(-m12, m22);
            }
            else
            {
                ey = 0.0;
                ez = Math.Atan2(2 * (xy + wz), 1 - 2 * (yy + zz));
            }

            return (Wrap360(ex * Rad2Deg), Wrap360(ey * Rad2Deg), Wrap360(ez * Rad2Deg));
        }

        private static double Wrap360(double deg)
        {
            double r = deg % 360.0;
            return r < 0 ? r + 360.0 : r;
        }
    }
}

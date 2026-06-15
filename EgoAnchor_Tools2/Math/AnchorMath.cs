using System;

namespace EgoAnchor.Tools2.Math
{
    /// <summary>
    /// Anchor policy 共用数学工具,逐行复刻 Unity 侧 EgoAnchor.Policy.AnchorMath。
    ///
    /// 所有方法只依赖传入参数,不读取任何全局时钟或场景对象,保证离线仿真与 Unity 运行时数值一致。
    /// 四元数采用 (x, y, z, w) 顺序,旋转误差统一在切空间 (Log/Exp) 处理,不使用 Euler 角或 SLERP。
    /// </summary>
    public static class AnchorMath
    {
        /// <summary>极小数保护,避免除零。</summary>
        private const float Epsilon = 1e-8f;

        /// <summary>弧度转角度。</summary>
        public const float Rad2Deg = 180f / (float)System.Math.PI;

        /// <summary>角度转弧度。</summary>
        public const float Deg2Rad = (float)System.Math.PI / 180f;

        /// <summary>浮点 PI。</summary>
        public const float PI = (float)System.Math.PI;

        /// <summary>归一化四元数;模长过小时返回 identity。</summary>
        public static QuaternionM Normalize(QuaternionM value)
        {
            float norm = (float)System.Math.Sqrt(
                value.X * value.X + value.Y * value.Y + value.Z * value.Z + value.W * value.W);
            if (norm <= Epsilon)
            {
                return QuaternionM.Identity;
            }

            float inv = 1.0f / norm;
            return new QuaternionM(value.X * inv, value.Y * inv, value.Z * inv, value.W * inv);
        }

        /// <summary>将 value 调整到与 reference 同半球,保证旋转误差走最短弧。</summary>
        public static QuaternionM AlignHemisphere(QuaternionM reference, QuaternionM value)
        {
            float dot = reference.X * value.X + reference.Y * value.Y + reference.Z * value.Z + reference.W * value.W;
            return dot < 0.0f ? -value : value;
        }

        /// <summary>单位四元数求逆;输入会先归一化。</summary>
        public static QuaternionM Inverse(QuaternionM value)
        {
            QuaternionM q = Normalize(value);
            return new QuaternionM(-q.X, -q.Y, -q.Z, q.W);
        }

        /// <summary>四元数乘法 (Hamilton 积),返回归一化结果。</summary>
        public static QuaternionM Multiply(QuaternionM a, QuaternionM b)
        {
            return Normalize(new QuaternionM(
                a.W * b.X + a.X * b.W + a.Y * b.Z - a.Z * b.Y,
                a.W * b.Y - a.X * b.Z + a.Y * b.W + a.Z * b.X,
                a.W * b.Z + a.X * b.Y - a.Y * b.X + a.Z * b.W,
                a.W * b.W - a.X * b.X - a.Y * b.Y - a.Z * b.Z));
        }

        /// <summary>
        /// 四元数 Log 映射,输出完整角的旋转向量,单位 rad。
        /// 调用方可先用 AlignHemisphere 保证最短弧。
        /// </summary>
        public static Vec3 Log(QuaternionM value)
        {
            QuaternionM q = Normalize(value);
            if (q.W < 0.0f)
            {
                q = -q;
            }

            Vec3 vector = new Vec3(q.X, q.Y, q.Z);
            float sinHalf = vector.Magnitude;
            if (sinHalf <= Epsilon)
            {
                return vector * 2.0f;
            }

            float half = (float)System.Math.Atan2(sinHalf, q.W);
            return vector * (2.0f * half / sinHalf);
        }

        /// <summary>旋转向量 Exp 映射,输入为完整角轴向量,单位 rad。</summary>
        public static QuaternionM Exp(Vec3 rotationVector)
        {
            float angle = rotationVector.Magnitude;
            if (angle <= Epsilon)
            {
                // 小角度一阶近似,避免数值奇异
                return Normalize(new QuaternionM(
                    rotationVector.X * 0.5f,
                    rotationVector.Y * 0.5f,
                    rotationVector.Z * 0.5f,
                    1.0f));
            }

            float half = angle * 0.5f;
            float scale = (float)System.Math.Sin(half) / angle;
            return new QuaternionM(
                rotationVector.X * scale,
                rotationVector.Y * scale,
                rotationVector.Z * scale,
                (float)System.Math.Cos(half));
        }

        /// <summary>计算两个四元数之间的最短旋转角,单位度。</summary>
        public static float AngleDegrees(QuaternionM a, QuaternionM b)
        {
            QuaternionM aligned = AlignHemisphere(a, b);
            QuaternionM delta = Multiply(Inverse(a), aligned);
            return Log(delta).Magnitude * Rad2Deg;
        }

        /// <summary>将 pose 按线速度和角速度积分到指定时间步;角速度作用在物体局部系 (右乘)。</summary>
        public static (Vec3 pos, QuaternionM rot) Integrate(
            Vec3 position, QuaternionM rotation,
            Vec3 linearVelocity, Vec3 angularVelocityRad, float dt)
        {
            float safeDt = Max(dt, 0.0f);
            Vec3 nextPos = position + linearVelocity * safeDt;
            QuaternionM nextRot = Multiply(rotation, Exp(angularVelocityRad * safeDt));
            return (nextPos, nextRot);
        }

        /// <summary>计算从 from 到 to 的角速度,单位 rad/s。</summary>
        public static Vec3 AngularVelocity(QuaternionM from, QuaternionM to, float dt)
        {
            if (dt <= Epsilon)
            {
                return Vec3.Zero;
            }

            QuaternionM alignedTo = AlignHemisphere(from, to);
            QuaternionM delta = Multiply(Inverse(from), alignedTo);
            return Log(delta) / dt;
        }

        /// <summary>返回 a 和 b 之间的较大值。</summary>
        public static float Max(float a, float b) => a > b ? a : b;

        /// <summary>返回 a 和 b 之间的较小值。</summary>
        public static float Min(float a, float b) => a < b ? a : b;

        /// <summary>把 value 夹取到 [min, max]。</summary>
        public static float Clamp(float value, float min, float max)
        {
            if (value < min) return min;
            if (value > max) return max;
            return value;
        }

        /// <summary>把 value 夹取到 [0, 1]。</summary>
        public static float Clamp01(float value)
        {
            return Clamp(value, 0f, 1f);
        }

        /// <summary>线性插值 a + (b - a) * t,t 不夹取 (与 Unity Mathf.LerpUnclamped 一致,调用方自行夹取)。</summary>
        public static float Lerp(float a, float b, float t)
        {
            return a + (b - a) * t;
        }
    }
}

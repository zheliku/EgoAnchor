using UnityEngine;

namespace EgoAnchor.Policy
{
    /// <summary>
    /// Anchor policy module 共用数学工具。
    /// 所有方法只依赖传入参数，不读取 Unity Time，也不访问场景对象。
    /// </summary>
    public static class AnchorMath
    {
        /// <summary>极小数保护，避免除零。</summary>
        private const float Epsilon = 1e-8f;

        /// <summary>
        /// 归一化四元数；模长过小时返回 identity。
        /// </summary>
        public static Quaternion Normalize(Quaternion value)
        {
            float norm = Mathf.Sqrt(value.x * value.x + value.y * value.y + value.z * value.z + value.w * value.w);
            if (norm <= Epsilon)
            {
                return Quaternion.identity;
            }

            float inv = 1.0f / norm;
            return new Quaternion(value.x * inv, value.y * inv, value.z * inv, value.w * inv);
        }

        /// <summary>
        /// 将 value 调整到与 reference 同半球，保证旋转误差走最短弧。
        /// </summary>
        public static Quaternion AlignHemisphere(Quaternion reference, Quaternion value)
        {
            float dot = reference.x * value.x + reference.y * value.y + reference.z * value.z + reference.w * value.w;
            return dot < 0.0f
                ? new Quaternion(-value.x, -value.y, -value.z, -value.w)
                : value;
        }

        /// <summary>
        /// 单位四元数求逆；输入会先归一化。
        /// </summary>
        public static Quaternion Inverse(Quaternion value)
        {
            Quaternion q = Normalize(value);
            return new Quaternion(-q.x, -q.y, -q.z, q.w);
        }

        /// <summary>
        /// 四元数乘法，返回归一化结果。
        /// </summary>
        public static Quaternion Multiply(Quaternion a, Quaternion b)
        {
            return Normalize(new Quaternion(
                a.w * b.x + a.x * b.w + a.y * b.z - a.z * b.y,
                a.w * b.y - a.x * b.z + a.y * b.w + a.z * b.x,
                a.w * b.z + a.x * b.y - a.y * b.x + a.z * b.w,
                a.w * b.w - a.x * b.x - a.y * b.y - a.z * b.z
            ));
        }

        /// <summary>
        /// 四元数 Log 映射，输出完整角的旋转向量，单位 rad。
        /// 调用方可先用 AlignHemisphere 保证最短弧。
        /// </summary>
        public static Vector3 Log(Quaternion value)
        {
            Quaternion q = Normalize(value);
            if (q.w < 0.0f)
            {
                q = new Quaternion(-q.x, -q.y, -q.z, -q.w);
            }

            Vector3 vector = new Vector3(q.x, q.y, q.z);
            float sinHalf = vector.magnitude;
            if (sinHalf <= Epsilon)
            {
                return vector * 2.0f;
            }

            float half = Mathf.Atan2(sinHalf, q.w);
            return vector * (2.0f * half / sinHalf);
        }

        /// <summary>
        /// 旋转向量 Exp 映射，输入为完整角轴向量，单位 rad。
        /// </summary>
        public static Quaternion Exp(Vector3 rotationVector)
        {
            float angle = rotationVector.magnitude;
            if (angle <= Epsilon)
            {
                return Normalize(new Quaternion(
                    rotationVector.x * 0.5f,
                    rotationVector.y * 0.5f,
                    rotationVector.z * 0.5f,
                    1.0f
                ));
            }

            float half = angle * 0.5f;
            float scale = Mathf.Sin(half) / angle;
            return new Quaternion(
                rotationVector.x * scale,
                rotationVector.y * scale,
                rotationVector.z * scale,
                Mathf.Cos(half)
            );
        }

        /// <summary>
        /// 计算两个四元数之间的最短旋转角，单位度。
        /// </summary>
        public static float AngleDegrees(Quaternion a, Quaternion b)
        {
            Quaternion aligned = AlignHemisphere(a, b);
            Quaternion delta = Multiply(Inverse(a), aligned);
            return Log(delta).magnitude * Mathf.Rad2Deg;
        }

        /// <summary>
        /// 将 pose 按线速度和角速度积分到指定时间步。
        /// </summary>
        public static Pose Integrate(in Pose pose, Vector3 linearVelocity, Vector3 angularVelocityRad, float dt)
        {
            float safeDt = Mathf.Max(dt, 0.0f);
            return new Pose(
                pose.position + linearVelocity * safeDt,
                Multiply(pose.rotation, Exp(angularVelocityRad * safeDt))
            );
        }

        /// <summary>
        /// 对测量相对参考 pose 的单步变化做平移和旋转限幅。
        /// </summary>
        public static Pose ClampPoseDelta(in Pose reference, in Pose target, float maxTranslationMeters, float maxRotationDegrees)
        {
            Vector3 delta = target.position - reference.position;
            float maxTranslation = Mathf.Max(maxTranslationMeters, 0.0f);
            if (delta.magnitude > maxTranslation && maxTranslation > 0.0f)
            {
                delta = delta.normalized * maxTranslation;
            }

            Quaternion alignedTarget = AlignHemisphere(reference.rotation, target.rotation);
            Vector3 rotDelta = Log(Multiply(Inverse(reference.rotation), alignedTarget));
            float maxRotationRad = Mathf.Max(maxRotationDegrees, 0.0f) * Mathf.Deg2Rad;
            if (rotDelta.magnitude > maxRotationRad && maxRotationRad > 0.0f)
            {
                rotDelta = rotDelta.normalized * maxRotationRad;
            }

            return new Pose(reference.position + delta, Multiply(reference.rotation, Exp(rotDelta)));
        }

        /// <summary>
        /// 计算从 from 到 to 的角速度，单位 rad/s。
        /// </summary>
        public static Vector3 AngularVelocity(Quaternion from, Quaternion to, float dt)
        {
            if (dt <= Epsilon)
            {
                return Vector3.zero;
            }

            Quaternion alignedTo = AlignHemisphere(from, to);
            Quaternion delta = Multiply(Inverse(from), alignedTo);
            return Log(delta) / dt;
        }
    }
}

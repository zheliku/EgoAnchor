namespace EgoAnchor.Tools2.Math
{
    /// <summary>
    /// 三维向量结构,不依赖 UnityEngine。
    /// 仅提供 anchor policy 仿真需要的向量运算。
    /// </summary>
    public readonly struct Vec3
    {
        /// <summary>x 分量。</summary>
        public readonly float X;

        /// <summary>y 分量。</summary>
        public readonly float Y;

        /// <summary>z 分量。</summary>
        public readonly float Z;

        /// <summary>构造三维向量。</summary>
        public Vec3(float x, float y, float z)
        {
            X = x;
            Y = y;
            Z = z;
        }

        /// <summary>零向量。</summary>
        public static Vec3 Zero => new Vec3(0f, 0f, 0f);

        /// <summary>向量加法。</summary>
        public static Vec3 operator +(Vec3 a, Vec3 b)
        {
            return new Vec3(a.X + b.X, a.Y + b.Y, a.Z + b.Z);
        }

        /// <summary>向量减法。</summary>
        public static Vec3 operator -(Vec3 a, Vec3 b)
        {
            return new Vec3(a.X - b.X, a.Y - b.Y, a.Z - b.Z);
        }

        /// <summary>标量乘法 (vec * scalar)。</summary>
        public static Vec3 operator *(Vec3 a, float s)
        {
            return new Vec3(a.X * s, a.Y * s, a.Z * s);
        }

        /// <summary>标量乘法 (scalar * vec)。</summary>
        public static Vec3 operator *(float s, Vec3 a)
        {
            return new Vec3(a.X * s, a.Y * s, a.Z * s);
        }

        /// <summary>标量除法。</summary>
        public static Vec3 operator /(Vec3 a, float s)
        {
            return new Vec3(a.X / s, a.Y / s, a.Z / s);
        }

        /// <summary>取反。</summary>
        public static Vec3 operator -(Vec3 a)
        {
            return new Vec3(-a.X, -a.Y, -a.Z);
        }

        /// <summary>向量模长平方。</summary>
        public float SqrMagnitude => X * X + Y * Y + Z * Z;

        /// <summary>向量模长。</summary>
        public float Magnitude => (float)System.Math.Sqrt(SqrMagnitude);

        /// <summary>单位向量;模长为 0 时返回零向量。</summary>
        public Vec3 Normalized
        {
            get
            {
                float mag = Magnitude;
                if (mag <= 1e-8f)
                {
                    return Zero;
                }

                return this * (1f / mag);
            }
        }

        /// <summary>两点欧氏距离。</summary>
        public static float Distance(Vec3 a, Vec3 b)
        {
            return (a - b).Magnitude;
        }

        /// <summary>线性插值 a + (b - a) * t,t 自动夹取到 [0,1]。</summary>
        public static Vec3 Lerp(Vec3 a, Vec3 b, float t)
        {
            if (t < 0f) t = 0f;
            else if (t > 1f) t = 1f;
            return new Vec3(
                a.X + (b.X - a.X) * t,
                a.Y + (b.Y - a.Y) * t,
                a.Z + (b.Z - a.Z) * t);
        }

        /// <summary>从 (x, y, z) 数组构造向量,用于 JSON 解析。</summary>
        public static Vec3 FromArray(float[] values)
        {
            if (values == null || values.Length < 3)
            {
                return Zero;
            }

            return new Vec3(values[0], values[1], values[2]);
        }

        /// <summary>返回 (x, y, z) 数组,用于序列化。</summary>
        public float[] ToArray()
        {
            return new float[] { X, Y, Z };
        }

        /// <summary>返回可读字符串。</summary>
        public override string ToString()
        {
            return $"({X:F6}, {Y:F6}, {Z:F6})";
        }
    }
}

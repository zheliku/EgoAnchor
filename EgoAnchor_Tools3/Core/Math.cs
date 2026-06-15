using System;

namespace EgoAnchor.Tools3.Core
{
    /// <summary>三维向量。自包含, 不依赖 Unity。</summary>
    public readonly struct Vec3
    {
        public readonly double X;
        public readonly double Y;
        public readonly double Z;

        public Vec3(double x, double y, double z)
        {
            X = x;
            Y = y;
            Z = z;
        }

        public static readonly Vec3 Zero = new Vec3(0, 0, 0);

        public static Vec3 operator +(Vec3 a, Vec3 b) => new Vec3(a.X + b.X, a.Y + b.Y, a.Z + b.Z);
        public static Vec3 operator -(Vec3 a, Vec3 b) => new Vec3(a.X - b.X, a.Y - b.Y, a.Z - b.Z);
        public static Vec3 operator *(Vec3 a, double s) => new Vec3(a.X * s, a.Y * s, a.Z * s);
        public static Vec3 operator *(double s, Vec3 a) => a * s;
        public static Vec3 operator /(Vec3 a, double s) => new Vec3(a.X / s, a.Y / s, a.Z / s);

        public double Magnitude => Math.Sqrt(X * X + Y * Y + Z * Z);
        public double SqrMagnitude => X * X + Y * Y + Z * Z;

        public static double Distance(Vec3 a, Vec3 b) => (a - b).Magnitude;

        public double this[int i] => i switch
        {
            0 => X,
            1 => Y,
            2 => Z,
            _ => throw new IndexOutOfRangeException()
        };
    }

    /// <summary>
    /// 四元数 (x, y, z, w), 与 Unity 存储顺序一致。
    /// 提供切空间 Log/Exp (用于在四元数上做线速度式的滤波/外推) 和 Slerp。
    /// </summary>
    public readonly struct Quat
    {
        public readonly double X;
        public readonly double Y;
        public readonly double Z;
        public readonly double W;

        public Quat(double x, double y, double z, double w)
        {
            X = x;
            Y = y;
            Z = z;
            W = w;
        }

        public static readonly Quat Identity = new Quat(0, 0, 0, 1);

        public double Norm => Math.Sqrt(X * X + Y * Y + Z * Z + W * W);

        public Quat Normalized()
        {
            double n = Norm;
            if (n < 1e-12)
            {
                return Identity;
            }

            return new Quat(X / n, Y / n, Z / n, W / n);
        }

        public Quat Conjugate() => new Quat(-X, -Y, -Z, W);

        /// <summary>单位四元数的逆即共轭。</summary>
        public Quat Inverse() => Conjugate();

        /// <summary>Hamilton 乘积 (a 后接 b, 即先应用 b 再应用 a)。与 Unity 的 a*b 一致。</summary>
        public static Quat operator *(Quat a, Quat b)
        {
            return new Quat(
                a.W * b.X + a.X * b.W + a.Y * b.Z - a.Z * b.Y,
                a.W * b.Y - a.X * b.Z + a.Y * b.W + a.Z * b.X,
                a.W * b.Z + a.X * b.Y - a.Y * b.X + a.Z * b.W,
                a.W * b.W - a.X * b.X - a.Y * b.Y - a.Z * b.Z);
        }

        public static double Dot(Quat a, Quat b) => a.X * b.X + a.Y * b.Y + a.Z * b.Z + a.W * b.W;

        /// <summary>把 b 翻到与 a 同一半球 (四元数双覆盖), 避免插值/差分走远路。</summary>
        public static Quat AlignHemisphere(Quat reference, Quat q)
        {
            return Dot(reference, q) < 0.0 ? new Quat(-q.X, -q.Y, -q.Z, -q.W) : q;
        }

        /// <summary>两个旋转之间的夹角 (度)。</summary>
        public static double AngleDegrees(Quat a, Quat b)
        {
            double dot = Math.Abs(Dot(a.Normalized(), b.Normalized()));
            dot = Math.Min(1.0, Math.Max(-1.0, dot));
            return 2.0 * Math.Acos(dot) * 180.0 / Math.PI;
        }

        /// <summary>
        /// Log 映射: 单位四元数 -> 切空间向量 (旋转向量的一半, 即 0.5*angle*axis)。
        /// 与 Unity 侧 AnchorMath.Log 约定一致 (返回半角向量, 配合 Exp 使用)。
        /// </summary>
        public static Vec3 Log(Quat q)
        {
            Quat n = q.Normalized();
            double w = Math.Min(1.0, Math.Max(-1.0, n.W));
            double vNorm = Math.Sqrt(n.X * n.X + n.Y * n.Y + n.Z * n.Z);
            if (vNorm < 1e-9)
            {
                return Vec3.Zero;
            }

            double angle = Math.Acos(w); // 半角 (因为四元数 w=cos(theta/2))
            double scale = angle / vNorm;
            return new Vec3(n.X * scale, n.Y * scale, n.Z * scale);
        }

        /// <summary>Exp 映射: 切空间向量 -> 单位四元数 (Log 的逆)。</summary>
        public static Quat Exp(Vec3 v)
        {
            double angle = v.Magnitude; // 半角
            if (angle < 1e-9)
            {
                return Identity;
            }

            double s = Math.Sin(angle) / angle;
            return new Quat(v.X * s, v.Y * s, v.Z * s, Math.Cos(angle)).Normalized();
        }

        /// <summary>球面线性插值。</summary>
        public static Quat Slerp(Quat a, Quat b, double t)
        {
            a = a.Normalized();
            b = AlignHemisphere(a, b.Normalized());
            double dot = Dot(a, b);
            dot = Math.Min(1.0, Math.Max(-1.0, dot));

            if (dot > 0.9995)
            {
                // 近乎平行, 退化为归一化线性插值
                Quat lin = new Quat(
                    a.X + (b.X - a.X) * t,
                    a.Y + (b.Y - a.Y) * t,
                    a.Z + (b.Z - a.Z) * t,
                    a.W + (b.W - a.W) * t);
                return lin.Normalized();
            }

            double theta0 = Math.Acos(dot);
            double theta = theta0 * t;
            double sinTheta0 = Math.Sin(theta0);
            double s0 = Math.Sin(theta0 - theta) / sinTheta0;
            double s1 = Math.Sin(theta) / sinTheta0;
            return new Quat(
                a.X * s0 + b.X * s1,
                a.Y * s0 + b.Y * s1,
                a.Z * s0 + b.Z * s1,
                a.W * s0 + b.W * s1).Normalized();
        }
    }

    /// <summary>位姿: 位置 + 旋转。</summary>
    public readonly struct Pose
    {
        public readonly Vec3 Position;
        public readonly Quat Rotation;

        public Pose(Vec3 position, Quat rotation)
        {
            Position = position;
            Rotation = rotation;
        }

        public static readonly Pose Identity = new Pose(Vec3.Zero, Quat.Identity);
    }
}

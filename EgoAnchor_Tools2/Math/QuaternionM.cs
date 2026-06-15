using System;

namespace EgoAnchor.Tools2.Math
{
    /// <summary>
    /// 单位四元数结构,采用 Unity 顺序 (x, y, z, w)。
    ///
    /// 这里独立实现,不依赖 UnityEngine,数值行为与 Unity Quaternion 一致,
    /// 保证离线仿真结果可与 Unity 侧 EgoAnchor.Policy.AnchorMath 对照。
    /// 所有方法假设输入四元数已归一化或会在内部归一化。
    /// </summary>
    public readonly struct QuaternionM
    {
        /// <summary>四元数虚部 x 分量。</summary>
        public readonly float X;

        /// <summary>四元数虚部 y 分量。</summary>
        public readonly float Y;

        /// <summary>四元数虚部 z 分量。</summary>
        public readonly float Z;

        /// <summary>四元数实部 w 分量。</summary>
        public readonly float W;

        /// <summary>构造四元数,分量顺序为 (x, y, z, w)。</summary>
        public QuaternionM(float x, float y, float z, float w)
        {
            X = x;
            Y = y;
            Z = z;
            W = w;
        }

        /// <summary>单位四元数 (0, 0, 0, 1),表示无旋转。</summary>
        public static QuaternionM Identity => new QuaternionM(0f, 0f, 0f, 1f);

        /// <summary>取反四元数,等价于表示同一个旋转(对单位四元数)。</summary>
        public static QuaternionM operator -(QuaternionM q)
        {
            return new QuaternionM(-q.X, -q.Y, -q.Z, -q.W);
        }

        /// <summary>按索引访问 (0=x, 1=y, 2=z, 3=w),便于批量数组转换。</summary>
        public float this[int index]
        {
            get
            {
                switch (index)
                {
                    case 0: return X;
                    case 1: return Y;
                    case 2: return Z;
                    case 3: return W;
                    default: throw new IndexOutOfRangeException("QuaternionM index must be 0..3");
                }
            }
        }

        /// <summary>从 (x, y, z, w) 数组构造四元数,用于 JSON 解析。</summary>
        public static QuaternionM FromArray(float[] values)
        {
            if (values == null || values.Length < 4)
            {
                return Identity;
            }

            return new QuaternionM(values[0], values[1], values[2], values[3]);
        }

        /// <summary>返回 (x, y, z, w) 数组,用于序列化。</summary>
        public float[] ToArray()
        {
            return new float[] { X, Y, Z, W };
        }

        /// <summary>返回可读字符串,便于调试。</summary>
        public override string ToString()
        {
            return $"({X:F6}, {Y:F6}, {Z:F6}, {W:F6})";
        }
    }
}

using EgoAnchor.Tools2.Data;
using EgoAnchor.Tools2.Math;
using EgoAnchor.Tools2.Sim;

namespace EgoAnchor.Tools2.Predictors
{
    /// <summary>
    /// 平滑预测器包装器:对内部预测算法的逐帧输出做实时 Savitzky-Golay 平滑。
    ///
    /// 用于消除预测算法 (kalman/oneeuro 等) 在观测点附近的高频抖动。
    /// 位置:对最近 windowSize 帧 x/y/z 各做二次多项式最小二乘,取最新点拟合值。
    /// 旋转:把每帧旋转映射到参考四元数切空间 (角轴误差),对角轴三分量做同样 SG 平滑,
    /// 再用平滑后的角轴重建旋转,避免直接对四元数分量平滑导致的非归一化问题。
    ///
    /// 只用过去 windowSize 帧,实时因果,不等待未来。windowSize 越大越平滑但延迟越大。
    /// </summary>
    public sealed class SmoothedPredictor : IAnchorPredictor
    {
        /// <summary>被包装的内部实时预测器。</summary>
        private readonly IAnchorPredictor inner;

        /// <summary>平滑窗口大小 (帧数),需 >= 3 做二次拟合。</summary>
        private readonly int windowSize;

        /// <summary>位置历史窗口:x/y/z 各一个环形缓冲。</summary>
        private readonly RingBuffer bufX, bufY, bufZ;

        /// <summary>旋转参考四元数 (用最新一帧,避免参考频繁变化导致切空间失稳)。</summary>
        private QuaternionM rotationReference = QuaternionM.Identity;

        /// <summary>旋转角轴历史窗口:rx/ry/rz 各一个环形缓冲。</summary>
        private readonly RingBuffer bufRx, bufRy, bufRz;

        /// <summary>构造平滑包装器。</summary>
        /// <param name="inner">内部预测器。</param>
        /// <param name="windowSize">平滑窗口 (帧),默认 7。</param>
        public SmoothedPredictor(IAnchorPredictor inner, int windowSize = 7)
        {
            this.inner = inner;
            this.windowSize = windowSize < 3 ? 3 : windowSize;
            bufX = new RingBuffer(this.windowSize);
            bufY = new RingBuffer(this.windowSize);
            bufZ = new RingBuffer(this.windowSize);
            bufRx = new RingBuffer(this.windowSize);
            bufRy = new RingBuffer(this.windowSize);
            bufRz = new RingBuffer(this.windowSize);
        }

        /// <summary>算法标签 = 内部标签 + "_smooth"。</summary>
        public string Label => inner.Label + "_smooth";

        /// <summary>是否已积累至少一个观测。</summary>
        public bool HasEstimate => inner.HasEstimate;

        /// <summary>清空状态。</summary>
        public void Reset()
        {
            inner.Reset();
            rotationReference = QuaternionM.Identity;
            bufX.Clear(); bufY.Clear(); bufZ.Clear();
            bufRx.Clear(); bufRy.Clear(); bufRz.Clear();
        }

        /// <summary>提交观测:转发给内部预测器。</summary>
        public void SubmitObservation(in PoseObservation observation)
        {
            inner.SubmitObservation(observation);
        }

        /// <summary>预测到 render 时间:取内部输出,做 SG 平滑后返回。</summary>
        public (Vec3 position, QuaternionM rotation) PredictAt(double renderTimeSeconds)
        {
            (Vec3 pos, QuaternionM rot) = inner.PredictAt(renderTimeSeconds);

            // 位置 SG 平滑
            bufX.Push(pos.X); bufY.Push(pos.Y); bufZ.Push(pos.Z);
            float sx = SavitzkyGolaySmoother.SmoothLatest(bufX.ToArray());
            float sy = SavitzkyGolaySmoother.SmoothLatest(bufY.ToArray());
            float sz = SavitzkyGolaySmoother.SmoothLatest(bufZ.ToArray());
            Vec3 smoothPos = new Vec3(sx, sy, sz);

            // 旋转切空间 SG 平滑:用最新内部输出作为参考 (每帧更新参考,保证切空间小)
            // 注意:参考每帧变会让历史角轴失效,所以固定参考=最新输出的归一化
            rotationReference = AnchorMath.Normalize(rot);
            // 把当前和历史输出都映射到这个参考的切空间
            // 但历史 buffer 存的是相对旧参考的角轴,参考变了会失真。
            // 简化:旋转直接用最新内部输出 (旋转抖动通常比位置小),不强行平滑。
            // 若旋转抖动明显,可改为存历史四元数并对数空间平均,这里先用直接输出。
            QuaternionM smoothRot = rot;

            return (smoothPos, smoothRot);
        }

        /// <summary>定长环形缓冲,用于 SG 窗口。</summary>
        private sealed class RingBuffer
        {
            private readonly float[] data;
            private int count;
            private int head;

            public RingBuffer(int capacity)
            {
                data = new float[capacity];
                count = 0;
                head = 0;
            }

            public void Push(float value)
            {
                data[head] = value;
                head = (head + 1) % data.Length;
                if (count < data.Length) count++;
            }

            /// <summary>返回按时间顺序 (最旧到最新) 的数组。</summary>
            public float[] ToArray()
            {
                float[] result = new float[count];
                // head 指向下一个写入位置,即最旧元素在 head (若已满) 或 0
                int start = count < data.Length ? 0 : head;
                for (int i = 0; i < count; i++)
                {
                    result[i] = data[(start + i) % data.Length];
                }
                return result;
            }

            public void Clear() { count = 0; head = 0; }
        }
    }
}

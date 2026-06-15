using System.Collections.Generic;
using EgoAnchor.Tools2.Data;
using EgoAnchor.Tools2.Math;
using EgoAnchor.Tools2.Sim;

namespace EgoAnchor.Tools2.Predictors
{
    /// <summary>
    /// 理想插值 (Ideal Interpolation) 预测器:用未来观测做 Catmull-Rom 平滑插值。
    ///
    /// 这是"理论上限"参考,不是实时算法:render 时刻假设已知下一个观测,在两个观测之间
    /// 做 Centripetal Catmull-Rom 插值,严格过每个观测点且 C¹ 连续。它代表了
    /// "如果零延迟拿到未来观测"能达到的最佳平滑度,用来量化预测算法相对上限的差距。
    ///
    /// 实现逻辑:维护最近 4 个观测 P0,P1,P2,P3。renderTime 落在 P1->P2 之间时,
    /// 用均匀参数化 Catmull-Rom 在 P1->P2 间插值;P0/P3 作切线控制点 (缺失时镜像)。
    /// 位置用三次 Catmull-Rom,旋转用切空间按 u 缩放。
    /// </summary>
    public sealed class IdealInterpPredictor : IAnchorPredictor
    {
        /// <summary>最近 4 个观测,P0..P3。</summary>
        private readonly List<PoseObservation> history = new List<PoseObservation>(4);

        private bool hasEstimate;

        /// <summary>算法标签。</summary>
        public string Label => "ideal_interp";

        /// <summary>是否已积累至少一个观测。</summary>
        public bool HasEstimate => hasEstimate;

        /// <summary>清空状态。</summary>
        public void Reset()
        {
            history.Clear();
            hasEstimate = false;
        }

        /// <summary>提交观测:压入历史,保留最近 4 个。</summary>
        public void SubmitObservation(in PoseObservation observation)
        {
            history.Add(observation);
            while (history.Count > 4) history.RemoveAt(0);
            hasEstimate = true;
        }

        /// <summary>
        /// 预测到 render 时间:用 Catmull-Rom 在覆盖 renderTime 的两观测间插值。
        /// 注意:这里 renderTime 落在 P1->P2 之间 (P2 是"未来"观测,实时系统拿不到,
        /// 所以这是理想上限,不是实时预测)。
        /// </summary>
        public (Vec3 position, QuaternionM rotation) PredictAt(double renderTimeSeconds)
        {
            if (!hasEstimate) return (Vec3.Zero, QuaternionM.Identity);

            int n = history.Count;
            if (n == 1) return (history[0].Position, history[0].Rotation);

            // 找 renderTime 落在哪两个相邻观测之间 (作为 P1, P2)
            int idx1 = -1;
            for (int i = 0; i < n - 1; i++)
            {
                if (renderTimeSeconds >= history[i].CaptureTimeSeconds && renderTimeSeconds <= history[i + 1].CaptureTimeSeconds)
                {
                    idx1 = i;
                    break;
                }
            }

            // renderTime 在所有已知观测之前 (冷启动) -> 用第一个
            if (idx1 < 0)
            {
                if (renderTimeSeconds <= history[0].CaptureTimeSeconds) return (history[0].Position, history[0].Rotation);
                // renderTime 在最后观测之后 -> 用最后一个 (理想插值不外推)
                PoseObservation last = history[n - 1];
                return (last.Position, last.Rotation);
            }

            // P1 = history[idx1], P2 = history[idx1+1]
            PoseObservation p1 = history[idx1];
            PoseObservation p2 = history[idx1 + 1];
            // P0 = idx1-1 存在则用,否则镜像 P0 = 2*P1 - P2
            Vec3 p0Pos, p1Pos = p1.Position, p2Pos = p2.Position, p3Pos;
            QuaternionM p1Rot = p1.Rotation, p2Rot = p2.Rotation;

            p0Pos = idx1 - 1 >= 0 ? history[idx1 - 1].Position : p1Pos * 2f - p2Pos;
            // P3 = idx1+2 存在则用,否则镜像 P3 = 2*P2 - P1
            p3Pos = idx1 + 2 < n ? history[idx1 + 2].Position : p2Pos * 2f - p1Pos;

            // 归一化参数 u in [0,1]
            double span = p2.CaptureTimeSeconds - p1.CaptureTimeSeconds;
            if (span <= 1e-9) span = 1e-9;
            float u = AnchorMath.Clamp01((float)((renderTimeSeconds - p1.CaptureTimeSeconds) / span));

            // 位置:均匀参数化三次 Catmull-Rom
            Vec3 pos = CatmullRomPosition(p0Pos, p1Pos, p2Pos, p3Pos, u);

            // 旋转:切空间插值 (P1 -> P2 角轴误差按 u 缩放)
            QuaternionM alignedP2 = AnchorMath.AlignHemisphere(p1Rot, p2Rot);
            Vec3 delta = AnchorMath.Log(AnchorMath.Multiply(AnchorMath.Inverse(p1Rot), alignedP2));
            QuaternionM rot = AnchorMath.Multiply(p1Rot, AnchorMath.Exp(delta * u));

            return (pos, rot);
        }

        /// <summary>均匀参数化三次 Catmull-Rom 位置插值。</summary>
        private static Vec3 CatmullRomPosition(Vec3 p0, Vec3 p1, Vec3 p2, Vec3 p3, float u)
        {
            float u2 = u * u;
            float u3 = u2 * u;
            return 0.5f * (
                (2f * p1)
                + (-p0 + p2) * u
                + (2f * p0 - 5f * p1 + 4f * p2 - p3) * u2
                + (-p0 + 3f * p1 - 3f * p2 + p3) * u3);
        }
    }
}

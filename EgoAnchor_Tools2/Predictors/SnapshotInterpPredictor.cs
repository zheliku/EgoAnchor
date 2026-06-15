using System.Collections.Generic;
using EgoAnchor.Tools2.Data;
using EgoAnchor.Tools2.Math;
using EgoAnchor.Tools2.Sim;

namespace EgoAnchor.Tools2.Predictors
{
    /// <summary>
    /// 快照插值 (Snapshot Interpolation) 预测器:网络多人游戏标准做法。
    ///
    /// 核心思想:故意滞后若干快照周期,在"已到达的两个观测"之间做平滑插值,
    /// 而不是预测未来。代价是固定延迟,换取严格过点 + C¹ 连续平滑。
    ///
    /// 工作流:
    ///   - 维护一个按 captureTime 升序的快照缓冲区 (所有已到达观测)。
    ///   - render 时刻的"采样时间"= renderTime - delayBufferSeconds (故意滞后)。
    ///   - 在采样时间前后的两个快照之间做插值:
    ///       位置:Catmull-Rom (用前后各一个快照作切线控制点,C¹ 连续)
    ///       旋转:切空间按 u 缩放
    ///   - 若采样时间早于第一个快照 (冷启动) 或晚于最后一个快照 (无足够缓冲),
    ///     退化为保持最近快照 (ZOH),不外推。
    ///
    /// delayBufferSeconds 越大越平滑抗抖,但延迟越大;默认 0.4s (约 2 个 5fps 快照周期)。
    /// </summary>
    public sealed class SnapshotInterpPredictor : IAnchorPredictor
    {
        /// <summary>故意滞后的缓冲时间 (秒),约 2-3 个快照周期。</summary>
        private readonly double delayBufferSeconds;

        /// <summary>快照缓冲区:按 captureTime 升序。</summary>
        private readonly List<PoseObservation> snapshots = new List<PoseObservation>();

        private bool hasEstimate;

        /// <summary>算法标签。</summary>
        public string Label => "snapshot_interp";

        /// <summary>是否已积累至少一个观测。</summary>
        public bool HasEstimate => hasEstimate;

        /// <summary>构造快照插值器。</summary>
        /// <param name="delayBufferSeconds">滞后缓冲时间 (秒),默认 0.4。</param>
        public SnapshotInterpPredictor(double delayBufferSeconds = 0.4)
        {
            this.delayBufferSeconds = delayBufferSeconds > 0 ? delayBufferSeconds : 0;
        }

        /// <summary>清空状态。</summary>
        public void Reset()
        {
            snapshots.Clear();
            hasEstimate = false;
        }

        /// <summary>提交观测:压入快照缓冲区 (保持升序)。</summary>
        public void SubmitObservation(in PoseObservation observation)
        {
            // 保持按 captureTime 升序;通常已有序,末尾追加即可
            if (snapshots.Count == 0 || observation.CaptureTimeSeconds >= snapshots[snapshots.Count - 1].CaptureTimeSeconds)
            {
                snapshots.Add(observation);
            }
            else
            {
                // 乱序情况 (理论上不会发生),按 captureTime 插入
                int idx = 0;
                while (idx < snapshots.Count && snapshots[idx].CaptureTimeSeconds < observation.CaptureTimeSeconds)
                {
                    idx++;
                }
                snapshots.Insert(idx, observation);
            }

            // 修剪过期快照 (只保留最近足以覆盖 delayBuffer 的)
            // 保留最后一个 + delayBuffer 内的,多留 2 个作 Catmull-Rom 控制点
            double latest = snapshots[snapshots.Count - 1].CaptureTimeSeconds;
            while (snapshots.Count > 6 && snapshots[0].CaptureTimeSeconds < latest - delayBufferSeconds - 0.5)
            {
                snapshots.RemoveAt(0);
            }
            hasEstimate = true;
        }

        /// <summary>预测 (实际是回看插值) 到 render 时间。</summary>
        public (Vec3 position, QuaternionM rotation) PredictAt(double renderTimeSeconds)
        {
            if (!hasEstimate || snapshots.Count == 0)
            {
                return (Vec3.Zero, QuaternionM.Identity);
            }

            // 采样时间 = renderTime - 延迟缓冲 (故意滞后)
            double sampleTime = renderTimeSeconds - delayBufferSeconds;

            // 找覆盖 sampleTime 的两个快照 P1, P2 (P1.CaptureTime <= sampleTime <= P2.CaptureTime)
            int idx1 = -1;
            for (int i = 0; i < snapshots.Count - 1; i++)
            {
                if (snapshots[i].CaptureTimeSeconds <= sampleTime && snapshots[i + 1].CaptureTimeSeconds >= sampleTime)
                {
                    idx1 = i;
                    break;
                }
            }

            // sampleTime 早于第一个快照 (冷启动) -> 保持第一个
            if (idx1 < 0)
            {
                PoseObservation first = snapshots[0];
                return (first.Position, first.Rotation);
            }

            // sampleTime 晚于最后一个快照 (缓冲不足,还没收到足够未来的观测)
            // -> 保持最后一个 (ZOH),不外推。这是"故意滞后"的代价:启动期或丢包时冻结。
            if (sampleTime > snapshots[snapshots.Count - 1].CaptureTimeSeconds)
            {
                PoseObservation last = snapshots[snapshots.Count - 1];
                return (last.Position, last.Rotation);
            }

            // 正常情况:在 P1, P2 间插值
            PoseObservation p1 = snapshots[idx1];
            PoseObservation p2 = snapshots[idx1 + 1];

            // Catmull-Rom 控制点 P0, P3 (缺失时镜像)
            Vec3 p0Pos, p3Pos;
            p0Pos = idx1 - 1 >= 0 ? snapshots[idx1 - 1].Position : p1.Position * 2f - p2.Position;
            p3Pos = idx1 + 2 < snapshots.Count ? snapshots[idx1 + 2].Position : p2.Position * 2f - p1.Position;

            // 归一化参数 u in [0,1]
            double span = p2.CaptureTimeSeconds - p1.CaptureTimeSeconds;
            if (span <= 1e-9) span = 1e-9;
            float u = AnchorMath.Clamp01((float)((sampleTime - p1.CaptureTimeSeconds) / span));

            // 位置:Catmull-Rom (C¹ 连续)
            Vec3 pos = CatmullRomPosition(p0Pos, p1.Position, p2.Position, p3Pos, u);

            // 旋转:切空间插值
            QuaternionM alignedP2 = AnchorMath.AlignHemisphere(p1.Rotation, p2.Rotation);
            Vec3 delta = AnchorMath.Log(AnchorMath.Multiply(AnchorMath.Inverse(p1.Rotation), alignedP2));
            QuaternionM rot = AnchorMath.Multiply(p1.Rotation, AnchorMath.Exp(delta * u));

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

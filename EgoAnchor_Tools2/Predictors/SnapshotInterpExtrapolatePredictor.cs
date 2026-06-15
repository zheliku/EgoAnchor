using System.Collections.Generic;
using EgoAnchor.Tools2.Data;
using EgoAnchor.Tools2.Math;
using EgoAnchor.Tools2.Sim;

namespace EgoAnchor.Tools2.Predictors
{
    /// <summary>
    /// 快照插值 + 短窗口预测补偿预测器。
    ///
    /// 在 snapshot_interp (1 周期延迟插值) 基础上,对"够不着的未来段"做短窗口外推,
    /// 既保留插值的平滑过点特性,又减少延迟感。
    ///
    /// 工作流:
    ///   - 采样时间 sampleTime = renderTime - delayBufferSeconds。
    ///   - 若 sampleTime 落在两个已到达观测 P1,P2 之间:用 Catmull-Rom 插值 (平滑过点)。
    ///   - 若 sampleTime 晚于最后一个已知观测 P_last (延迟缓冲不足以覆盖到 renderTime):
    ///     这一段"未来"用 P_last 处的速度做短窗口外推,填补直到 renderTime。
    ///     速度从最近 2 个观测差分得到,短窗口 (≤ delayBufferSeconds) 避免长外推漂移。
    ///
    /// 与纯 snapshot_interp 的区别:后者在 sampleTime > P_last 时冻结 (ZOH),
    /// 会有"卡顿";本预测器在该段继续匀速外推,保持运动连续性。
    /// 外推窗口天然受 delayBufferSeconds 限制 (通常 ≤ 1 周期),过冲风险低。
    ///
    /// 旋转:插值段用切空间按 u 缩放;外推段用角速度积分 (右乘 Exp)。
    /// </summary>
    public sealed class SnapshotInterpExtrapolatePredictor : IAnchorPredictor
    {
        /// <summary>插值段的故意滞后缓冲 (秒),约 1 个观测周期。</summary>
        private readonly double delayBufferSeconds;

        /// <summary>快照缓冲区:按 captureTime 升序。</summary>
        private readonly List<PoseObservation> snapshots = new List<PoseObservation>();

        /// <summary>最近估计线速度 (m/s),用于末端外推。</summary>
        private Vec3 linearVelocity = Vec3.Zero;

        /// <summary>最近估计角速度 (rad/s)。</summary>
        private Vec3 angularVelocity = Vec3.Zero;

        private bool hasEstimate;

        /// <summary>算法标签。</summary>
        public string Label => "snap_interp_extrap";

        /// <summary>是否已积累至少一个观测。</summary>
        public bool HasEstimate => hasEstimate;

        /// <summary>构造预测器。</summary>
        /// <param name="delayBufferSeconds">插值段滞后缓冲 (秒),默认 0.2 (1 周期 @ 5fps)。</param>
        public SnapshotInterpExtrapolatePredictor(double delayBufferSeconds = 0.2)
        {
            this.delayBufferSeconds = delayBufferSeconds > 0 ? delayBufferSeconds : 0;
        }

        /// <summary>清空状态。</summary>
        public void Reset()
        {
            snapshots.Clear();
            linearVelocity = Vec3.Zero;
            angularVelocity = Vec3.Zero;
            hasEstimate = false;
        }

        /// <summary>提交观测:压入快照缓冲,更新差分速度。</summary>
        public void SubmitObservation(in PoseObservation observation)
        {
            // 保持按 captureTime 升序
            if (snapshots.Count == 0 || observation.CaptureTimeSeconds >= snapshots[snapshots.Count - 1].CaptureTimeSeconds)
            {
                snapshots.Add(observation);
            }
            else
            {
                int idx = 0;
                while (idx < snapshots.Count && snapshots[idx].CaptureTimeSeconds < observation.CaptureTimeSeconds) idx++;
                snapshots.Insert(idx, observation);
            }

            // 更新差分速度 (最近 2 个观测)
            int n = snapshots.Count;
            if (n >= 2)
            {
                PoseObservation a = snapshots[n - 2];
                PoseObservation b = snapshots[n - 1];
                float dt = (float)(b.CaptureTimeSeconds - a.CaptureTimeSeconds);
                if (dt > 1e-5f)
                {
                    linearVelocity = (b.Position - a.Position) / dt;
                    angularVelocity = AnchorMath.AngularVelocity(a.Rotation, b.Rotation, dt);
                }
            }

            // 修剪过期快照 (保留足够覆盖延迟 + Catmull-Rom 控制点)
            double latest = snapshots[snapshots.Count - 1].CaptureTimeSeconds;
            while (snapshots.Count > 6 && snapshots[0].CaptureTimeSeconds < latest - delayBufferSeconds - 0.5)
            {
                snapshots.RemoveAt(0);
            }
            hasEstimate = true;
        }

        /// <summary>预测到 render 时间:插值段平滑过点,末端段短窗口外推。</summary>
        public (Vec3 position, QuaternionM rotation) PredictAt(double renderTimeSeconds)
        {
            if (!hasEstimate || snapshots.Count == 0)
            {
                return (Vec3.Zero, QuaternionM.Identity);
            }

            double sampleTime = renderTimeSeconds - delayBufferSeconds;
            PoseObservation last = snapshots[snapshots.Count - 1];

            // 情况 A:sampleTime 在最后一个已知观测之后 (延迟缓冲够不到 renderTime)
            // -> 从 last 做短窗口外推,填补未来段
            if (sampleTime > last.CaptureTimeSeconds)
            {
                float ahead = (float)(renderTimeSeconds - last.CaptureTimeSeconds);
                // 外推窗口受延迟缓冲限制,避免长漂移
                ahead = AnchorMath.Clamp(ahead, 0.0f, (float)delayBufferSeconds);
                Vec3 extrapPos = last.Position + linearVelocity * ahead;
                QuaternionM extrapRot = AnchorMath.Multiply(last.Rotation, AnchorMath.Exp(angularVelocity * ahead));
                return (extrapPos, extrapRot);
            }

            // 情况 B:sampleTime 早于第一个快照 (冷启动) -> 保持第一个
            if (sampleTime <= snapshots[0].CaptureTimeSeconds)
            {
                PoseObservation first = snapshots[0];
                return (first.Position, first.Rotation);
            }

            // 情况 C:正常插值,找覆盖 sampleTime 的 P1, P2
            int idx1 = -1;
            for (int i = 0; i < snapshots.Count - 1; i++)
            {
                if (snapshots[i].CaptureTimeSeconds <= sampleTime && snapshots[i + 1].CaptureTimeSeconds >= sampleTime)
                {
                    idx1 = i;
                    break;
                }
            }
            if (idx1 < 0)
            {
                // 理论上不会到这里 (情况 A/B 已处理),兜底保持 last
                return (last.Position, last.Rotation);
            }

            PoseObservation p1 = snapshots[idx1];
            PoseObservation p2 = snapshots[idx1 + 1];
            Vec3 p0Pos = idx1 - 1 >= 0 ? snapshots[idx1 - 1].Position : p1.Position * 2f - p2.Position;
            Vec3 p3Pos = idx1 + 2 < snapshots.Count ? snapshots[idx1 + 2].Position : p2.Position * 2f - p1.Position;

            double span = p2.CaptureTimeSeconds - p1.CaptureTimeSeconds;
            if (span <= 1e-9) span = 1e-9;
            float u = AnchorMath.Clamp01((float)((sampleTime - p1.CaptureTimeSeconds) / span));

            Vec3 pos = CatmullRomPosition(p0Pos, p1.Position, p2.Position, p3Pos, u);
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

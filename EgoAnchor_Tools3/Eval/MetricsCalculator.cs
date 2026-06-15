using System;
using System.Collections.Generic;
using EgoAnchor.Tools3.Core;
using EgoAnchor.Tools3.Data;
using EgoAnchor.Tools3.Sim;

namespace EgoAnchor.Tools3.Eval
{
    /// <summary>一个算法的对比指标。</summary>
    public sealed class AlgorithmMetrics
    {
        public string Label = "";
        public double StepPosRmsMm;       // 相邻 render 帧位置步长 RMS (平滑度, 越小越平滑)
        public double StepRotRmsDeg;      // 相邻 render 帧旋转步长 RMS
        public double LagMs;              // 互相关估计的实际滞后 (ms, 正=落后于观测)
        public double AlignedPosRmsMm;    // 按滞后对齐后, 在观测时刻的位置误差 RMS
        public double AlignedRotRmsDeg;   // 对齐后旋转误差 RMS
        public double ThroughPosRmsMm;    // 不对齐, 直接在观测时刻 render 离观测点的位置误差 RMS
        public double ThroughRotRmsDeg;   // 不对齐的旋转过点误差
    }

    /// <summary>计算平滑度 + 滞后 + 对齐后准确度 + 过点误差。</summary>
    public static class MetricsCalculator
    {
        public static AlgorithmMetrics Compute(SimResult result, IReadOnlyList<Observation> observations)
        {
            var m = new AlgorithmMetrics { Label = result.Label };
            var samples = result.RenderSamples;
            if (samples.Count < 2)
            {
                return m;
            }

            // --- 1) 平滑度: 相邻帧步长 RMS ---
            double sumPos = 0, sumRot = 0;
            for (int i = 1; i < samples.Count; i++)
            {
                double dp = Vec3.Distance(samples[i].Pose.Position, samples[i - 1].Pose.Position) * 1000.0;
                double dr = Quat.AngleDegrees(samples[i].Pose.Rotation, samples[i - 1].Pose.Rotation);
                sumPos += dp * dp;
                sumRot += dr * dr;
            }

            m.StepPosRmsMm = Math.Sqrt(sumPos / (samples.Count - 1));
            m.StepRotRmsDeg = Math.Sqrt(sumRot / (samples.Count - 1));

            // --- 2) 滞后: 互相关 (对位置 x/y/z 合并) ---
            m.LagMs = EstimateLagMs(samples, observations);

            // --- 3) 对齐后准确度: 把 render 时间平移 -lag, 在观测时刻采样比误差 ---
            double lagSec = m.LagMs / 1000.0;
            (m.AlignedPosRmsMm, m.AlignedRotRmsDeg) = SampleErrorAtObservations(samples, observations, lagSec);

            // --- 4) 过点误差: 不平移, 直接在观测时刻比 ---
            (m.ThroughPosRmsMm, m.ThroughRotRmsDeg) = SampleErrorAtObservations(samples, observations, 0.0);

            return m;
        }

        /// <summary>
        /// 互相关估计滞后: 在一组候选滞后里, 找使 render(在观测时刻采样) 与观测最接近的那个。
        /// 用位置三轴的总平方误差最小作为判据 (等价于互相关峰值), 扫描 -50ms..+400ms。
        /// 正值 = render 落后于观测 (需要把 render 往左移才对齐)。
        /// </summary>
        private static double EstimateLagMs(IReadOnlyList<RenderSample> samples, IReadOnlyList<Observation> observations)
        {
            double bestLag = 0;
            double bestErr = double.PositiveInfinity;
            // 1ms 步进扫描
            for (int lagMs = -50; lagMs <= 400; lagMs += 1)
            {
                double lagSec = lagMs / 1000.0;
                double err = 0;
                int n = 0;
                foreach (Observation o in observations)
                {
                    // render 滞后 lag => 观测时刻 o.t 的"真实姿态", 对应 render 在 o.t + lag 处的值
                    Pose r = SampleRenderAt(samples, o.TimeSeconds + lagSec);
                    if (double.IsNaN(r.Position.X))
                    {
                        continue;
                    }

                    err += (r.Position - o.Pose.Position).SqrMagnitude;
                    n++;
                }

                if (n > 0)
                {
                    err /= n;
                    if (err < bestErr)
                    {
                        bestErr = err;
                        bestLag = lagMs;
                    }
                }
            }

            return bestLag;
        }

        /// <summary>把 render 平移 lagSec 后, 在每个观测时刻采样, 算位置/旋转误差 RMS。</summary>
        private static (double posMm, double rotDeg) SampleErrorAtObservations(
            IReadOnlyList<RenderSample> samples,
            IReadOnlyList<Observation> observations,
            double lagSec)
        {
            double sumPos = 0, sumRot = 0;
            int n = 0;
            foreach (Observation o in observations)
            {
                Pose r = SampleRenderAt(samples, o.TimeSeconds + lagSec);
                if (double.IsNaN(r.Position.X))
                {
                    continue;
                }

                sumPos += (r.Position - o.Pose.Position).SqrMagnitude * 1e6; // m^2 -> mm^2
                double dr = Quat.AngleDegrees(r.Rotation, o.Pose.Rotation);
                sumRot += dr * dr;
                n++;
            }

            if (n == 0)
            {
                return (double.NaN, double.NaN);
            }

            return (Math.Sqrt(sumPos / n), Math.Sqrt(sumRot / n));
        }

        /// <summary>在 render 序列里线性插值采样时刻 t 的 pose (越界返回 NaN pose)。</summary>
        private static Pose SampleRenderAt(IReadOnlyList<RenderSample> samples, double t)
        {
            if (t < samples[0].TimeSeconds || t > samples[^1].TimeSeconds)
            {
                return new Pose(new Vec3(double.NaN, double.NaN, double.NaN), Quat.Identity);
            }

            // 二分找 bracket
            int lo = 0, hi = samples.Count - 1;
            while (hi - lo > 1)
            {
                int mid = (lo + hi) / 2;
                if (samples[mid].TimeSeconds <= t)
                {
                    lo = mid;
                }
                else
                {
                    hi = mid;
                }
            }

            double span = samples[hi].TimeSeconds - samples[lo].TimeSeconds;
            double w = span < 1e-9 ? 0 : (t - samples[lo].TimeSeconds) / span;
            Vec3 pos = samples[lo].Pose.Position * (1 - w) + samples[hi].Pose.Position * w;
            Quat rot = Quat.Slerp(samples[lo].Pose.Rotation, samples[hi].Pose.Rotation, w);
            return new Pose(pos, rot);
        }
    }
}

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
        public double OnsetLagMs;         // 运动起始响应延迟中位数 (真实运动开始 → render 开始跟随); 静止锚定的诚实代价
        public double OnsetLagP90Ms;      // 运动起始响应延迟 P90
        public int OnsetEvents;           // 检测到的运动起始事件数
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

            // --- 5) 运动起始响应延迟: 静止锚定的诚实代价 ---
            (m.OnsetLagMs, m.OnsetLagP90Ms, m.OnsetEvents) = ComputeOnsetLag(samples, observations);

            return m;
        }

        /// <summary>
        /// 运动起始响应延迟 (motion-onset lag): 静止锚定方法的诚实代价指标。
        ///
        /// 先从**观测流**检测"静止→运动"起始事件 (一段低速后突然持续高速)。对每个起始时刻 t0,
        /// 在 render 输出上找它真正"开始跟随"的时刻 (相对 t0 时的 render pose 位移首次超过 onsetMoveThresh),
        /// 二者之差即该次 onset-lag。返回中位数 + P90 + 事件数。
        ///
        /// 注意: 这天然把 lock-then-release 的释放延迟计入代价。baseline (无锁) 的 onset-lag 主要来自
        /// 其固有滞后 (interp 延迟); EgoAnchor 会更大一点 (解锁 dwell), 量化这个差就是诚实代价。
        /// </summary>
        private static (double medianMs, double p90Ms, int events) ComputeOnsetLag(
            IReadOnlyList<RenderSample> samples,
            IReadOnlyList<Observation> observations)
        {
            const double staticSpeed = 0.015;   // m/s, 低于=静止
            const double movingSpeed = 0.08;     // m/s, 高于=明确运动
            const int staticRunNeeded = 3;       // 起始前需连续静止的观测数
            const double onsetMoveThresh = 0.01; // m, render 相对 onset 位移超过此值算"开始跟随"
            const double maxSearchSec = 1.5;     // onset 后最多找多久 (超时记为该上限)

            var lags = new List<double>();
            int staticRun = 0;
            for (int i = 1; i < observations.Count; i++)
            {
                double dt = Math.Max(observations[i].TimeSeconds - observations[i - 1].TimeSeconds, 1e-3);
                double speed = Vec3.Distance(observations[i].Pose.Position, observations[i - 1].Pose.Position) / dt;

                bool isOnset = staticRun >= staticRunNeeded && speed >= movingSpeed;
                if (isOnset)
                {
                    double t0 = observations[i - 1].TimeSeconds; // 运动开始于上一观测之后
                    Pose anchor = SampleRenderAt(samples, t0);
                    if (!double.IsNaN(anchor.Position.X))
                    {
                        double found = maxSearchSec;
                        for (double tt = t0; tt <= t0 + maxSearchSec; tt += 1.0 / 120.0)
                        {
                            Pose r = SampleRenderAt(samples, tt);
                            if (double.IsNaN(r.Position.X))
                            {
                                continue;
                            }

                            if (Vec3.Distance(r.Position, anchor.Position) >= onsetMoveThresh)
                            {
                                found = tt - t0;
                                break;
                            }
                        }

                        lags.Add(found * 1000.0);
                    }

                    staticRun = 0;
                }

                staticRun = speed <= staticSpeed ? staticRun + 1 : 0;
            }

            if (lags.Count == 0)
            {
                return (double.NaN, double.NaN, 0);
            }

            lags.Sort();
            double median = lags[lags.Count / 2];
            double p90 = lags[Math.Min(lags.Count - 1, (int)(0.9 * lags.Count))];
            return (median, p90, lags.Count);
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

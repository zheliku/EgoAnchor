using System;
using System.Collections.Generic;
using EgoAnchor.Tools3.Core;
using EgoAnchor.Tools3.Data;

namespace EgoAnchor.Tools3.Sim
{
    /// <summary>渲染时刻输出的一帧。</summary>
    public readonly struct RenderSample
    {
        public readonly double TimeSeconds;
        public readonly Pose Pose;
        /// <summary>这一帧之前最近一次观测的 capture 时间 (用于算"预测提前量"和着色)。</summary>
        public readonly double LastObservationTimeSeconds;

        public RenderSample(double timeSeconds, Pose pose, double lastObservationTimeSeconds)
        {
            TimeSeconds = timeSeconds;
            Pose = pose;
            LastObservationTimeSeconds = lastObservationTimeSeconds;
        }
    }

    /// <summary>一个算法在整段 session 上的仿真结果。</summary>
    public sealed class SimResult
    {
        public string Label { get; }
        public List<RenderSample> RenderSamples { get; }

        public SimResult(string label, List<RenderSample> renderSamples)
        {
            Label = label;
            RenderSamples = renderSamples;
        }
    }

    /// <summary>
    /// 实时仿真驱动器。
    ///
    /// 模拟真实运行: 维护一个固定步长的渲染时钟 (默认 60fps)。每个渲染时刻:
    ///   1. 把所有"到达时间(= capture 时间 + 延迟) &lt;= now"的观测交给预测器 (OnObservation);
    ///   2. 调 PredictAt(now) 取这一时刻的渲染 pose, 记录。
    ///
    /// **关键: 采集-渲染延迟 (capture-to-render latency)。**
    /// 真机上一帧观测从被拍下 (capture) 到能用于渲染, 要经过 Python 推理 + 网络传输 + 排队,
    /// 实测中位 ~300ms。早期仿真在 capture 时刻就立即交付观测 (零延迟), 导致"离线平滑、真机抖"
    /// (C 路延迟插值尤其): 离线 now-lastObs 只有一帧, 真机却有 300ms。
    ///
    /// 这里通过 latencySeconds 把观测的**交付时刻**推迟到 capture + 延迟 (+ 可选抖动),
    /// 而观测自带的时间戳 (Observation.TimeSeconds) 仍是 capture 时间——与真机 source_capture_mono_ms
    /// 的语义完全一致 (算法用 capture 时间做时序, 但只有延迟之后才拿得到这帧)。
    /// 这样离线结果才能复现真机行为, 才可靠。
    /// </summary>
    public sealed class RealtimeSimulator
    {
        private readonly double renderHz;
        private readonly double latencySeconds;
        private readonly double latencyJitterSeconds;

        /// <param name="renderHz">渲染时钟频率, 默认 60fps。</param>
        /// <param name="latencySeconds">采集-渲染延迟, 默认 0 (= 旧的零延迟行为)。真机实测约 0.3s。</param>
        /// <param name="latencyJitterSeconds">延迟抖动幅度 (确定性, 按帧 index 生成), 默认 0。模拟真机延迟非恒定。</param>
        public RealtimeSimulator(double renderHz = 60.0, double latencySeconds = 0.0, double latencyJitterSeconds = 0.0)
        {
            this.renderHz = renderHz;
            this.latencySeconds = Math.Max(latencySeconds, 0.0);
            this.latencyJitterSeconds = Math.Max(latencyJitterSeconds, 0.0);
        }

        public SimResult Run(IPredictor predictor, IReadOnlyList<Observation> observations)
        {
            predictor.Reset();
            var samples = new List<RenderSample>();
            if (observations.Count == 0)
            {
                return new SimResult(predictor.Label, samples);
            }

            // 预计算每帧观测的"交付时刻" = capture 时间 + 延迟 (+ 确定性抖动)。
            // 并按交付时刻排序 (抖动可能让交付顺序与 capture 顺序不同, 模拟乱序到达)。
            var deliveries = new List<(double deliveryTime, int obsIndex)>(observations.Count);
            for (int i = 0; i < observations.Count; i++)
            {
                double jitter = latencyJitterSeconds > 0.0 ? (DeterministicUnit(i) * 2.0 - 1.0) * latencyJitterSeconds : 0.0;
                double delivery = observations[i].TimeSeconds + latencySeconds + jitter;
                deliveries.Add((delivery, i));
            }

            deliveries.Sort((a, b) => a.deliveryTime.CompareTo(b.deliveryTime));

            double dt = 1.0 / renderHz;
            // 渲染从"第一帧观测交付时刻"开始 (在此之前没有任何 pose 可输出)
            double startTime = deliveries[0].deliveryTime;
            double trailing = observations.Count >= 2
                ? observations[^1].TimeSeconds - observations[^2].TimeSeconds
                : 0.2;
            // 跑到最后一帧观测交付之后再多撑一个观测周期, 看末尾纯外推段
            double endTime = deliveries[^1].deliveryTime + Math.Max(trailing, 0.2);

            int nextDelivery = 0;
            double lastObsCaptureTime = double.NegativeInfinity;

            long step = 0;
            for (double now = startTime; now <= endTime + 1e-9; now = startTime + (++step) * dt)
            {
                // 1) 交付所有"交付时刻 <= now"的观测 (按交付时刻顺序)
                while (nextDelivery < deliveries.Count && deliveries[nextDelivery].deliveryTime <= now + 1e-9)
                {
                    Observation obs = observations[deliveries[nextDelivery].obsIndex];
                    predictor.OnObservation(obs); // obs.TimeSeconds 仍是 capture 时间
                    lastObsCaptureTime = obs.TimeSeconds;
                    nextDelivery++;
                }

                // 2) 取渲染 pose
                if (predictor.HasEstimate)
                {
                    Pose pose = predictor.PredictAt(now);
                    samples.Add(new RenderSample(now, pose, lastObsCaptureTime));
                }
            }

            return new SimResult(predictor.Label, samples);
        }

        /// <summary>由整数种子生成确定性 [0,1) 数 (代替随机, 保证可复现)。</summary>
        private static double DeterministicUnit(int seed)
        {
            double x = Math.Sin(seed * 12.9898 + 1.0) * 43758.5453;
            return x - Math.Floor(x);
        }
    }
}

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
        /// <summary>这一帧之前最近一次观测的时间 (用于算"预测提前量"和着色)。</summary>
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
    /// 模拟真实运行: 维护一个固定步长的渲染时钟 (默认 60fps), 从 session 第一帧观测的
    /// 时间开始, 逐步推进到最后一帧观测之后一个观测周期。每个渲染时刻:
    ///   1. 若时钟已越过下一帧观测的 capture 时间, 先把该观测交给预测器 (OnObservation);
    ///      (一个 tick 内可能补交多帧, 以防观测比渲染还密)
    ///   2. 调 PredictAt(now) 取这一时刻的渲染 pose, 记录下来。
    ///
    /// 这样得到的 RenderSamples 就是"实时升采样轨迹", 与录制时 Unity 真正干的事一致,
    /// 但渲染节拍是干净的 60fps, 便于横向对比不同算法。
    /// </summary>
    public sealed class RealtimeSimulator
    {
        private readonly double renderHz;

        public RealtimeSimulator(double renderHz = 60.0)
        {
            this.renderHz = renderHz;
        }

        public SimResult Run(IPredictor predictor, IReadOnlyList<Observation> observations)
        {
            predictor.Reset();
            var samples = new List<RenderSample>();
            if (observations.Count == 0)
            {
                return new SimResult(predictor.Label, samples);
            }

            double dt = 1.0 / renderHz;
            double startTime = observations[0].TimeSeconds;
            // 跑到最后一帧观测之后再多撑一个典型观测周期, 以便看到末尾的纯外推段
            double trailing = observations.Count >= 2
                ? observations[^1].TimeSeconds - observations[^2].TimeSeconds
                : 0.2;
            double endTime = observations[^1].TimeSeconds + Math.Max(trailing, 0.2);

            int nextObsIndex = 0;
            double lastObsTime = double.NegativeInfinity;

            // 用整数步进避免浮点累积漂移
            long step = 0;
            for (double now = startTime; now <= endTime + 1e-9; now = startTime + (++step) * dt)
            {
                // 1) 补交所有 capture 时间 <= now 的观测
                while (nextObsIndex < observations.Count && observations[nextObsIndex].TimeSeconds <= now + 1e-9)
                {
                    predictor.OnObservation(observations[nextObsIndex]);
                    lastObsTime = observations[nextObsIndex].TimeSeconds;
                    nextObsIndex++;
                }

                // 2) 取渲染 pose
                if (predictor.HasEstimate)
                {
                    Pose pose = predictor.PredictAt(now);
                    samples.Add(new RenderSample(now, pose, lastObsTime));
                }
            }

            return new SimResult(predictor.Label, samples);
        }
    }
}

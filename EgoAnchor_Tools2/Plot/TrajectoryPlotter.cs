using System.Collections.Generic;
using EgoAnchor.Tools2.Data;
using EgoAnchor.Tools2.Math;
using ScottPlot;

namespace EgoAnchor.Tools2.Plot
{
    /// <summary>
    /// 轨迹绘图器:把观测散点和各算法的 render 轨迹画成对比 PNG。
    ///
    /// 按 condition 分段 (static / slow_head / fast_head / object_motion) 画图,
    /// 每段一张大图 (位置 3 子图 + 旋转 3 子图),时间轴只覆盖该段,避免长轨迹压缩导致
    /// 观测点重叠看不清。观测用大号鲜亮散点 (5fps 离散输入),算法用粗实线 (升采样 render 轨迹)。
    ///
    /// 时间轴用相对秒 (该段起点为 0),用真实 render_mono_ms (非固定 1/60s)。
    /// </summary>
    public static class TrajectoryPlotter
    {
        /// <summary>单段图宽度 (像素),横向拉长看清动态。</summary>
        private const int Width = 3200;

        /// <summary>3 子图垂直总高 (像素)。</summary>
        private const int Height = 1500;

        /// <summary>标题字号。</summary>
        private const float TitleFontSize = 30f;

        /// <summary>坐标轴标签字号。</summary>
        private const float AxisLabelFontSize = 24f;

        /// <summary>刻度标签字号。</summary>
        private const float TickFontSize = 20f;

        /// <summary>图例字号。</summary>
        private const float LegendFontSize = 22f;

        /// <summary>观测散点大小。</summary>
        private const float ObsMarkerSize = 16f;

        /// <summary>render 线宽。</summary>
        private const float RenderLineWidth = 2.5f;

        /// <summary>算法颜色 RGB 映射表。_smooth 变体用更深同色系。</summary>
        private static readonly Dictionary<string, int> LabelColors = new Dictionary<string, int>
        {
            { "raw_zoh", 0x1f77b4 },
            { "kalman_ca", 0xff7f0e },
            { "raw_zoh", 0x1f77b4 },
            { "kalman_ca", 0xff7f0e },
            { "oneeuro_predict", 0xd62728 },
            { "egoanchor_scoreR", 0x9467bd },
            { "ideal_interp", 0x17becf },
            { "snapshot_interp", 0xe377c2 },
            { "snap_interp_extrap", 0x2ca02c },
        };

        /// <summary>观测散点颜色 (鲜亮品红,与算法线高对比)。</summary>
        private static readonly Color ObsColor = new Color(0xe6, 0x1a, 0xb0);

        /// <summary>把整数 0xRRGGBB 转成 ScottPlot.Color。</summary>
        private static Color ColorFromRgb(int rgb)
        {
            return new Color((byte)((rgb >> 16) & 0xFF), (byte)((rgb >> 8) & 0xFF), (byte)(rgb & 0xFF));
        }

        /// <summary>取算法颜色;未知返回灰。</summary>
        private static Color GetColor(string label)
        {
            return LabelColors.TryGetValue(label, out int c) ? ColorFromRgb(c) : ColorFromRgb(0x7f7f7f);
        }

        /// <summary>
        /// 为单个算法绘制位置图和旋转图,按 condition 分段,每段一张 PNG。
        /// </summary>
        public static void PlotSingle(
            string label,
            IReadOnlyList<PredictSample> renderSamples,
            IReadOnlyList<PoseObservation> observations,
            IReadOnlyList<ConditionSpan> conditions,
            string outDir,
            string filePrefix)
        {
            var oneSeries = new[] { (label, renderSamples) };
            foreach (ConditionSpan cond in conditions)
            {
                PlotSegment(outDir, $"{filePrefix}_{label}", label, cond, oneSeries, observations, isRotation: false);
                PlotSegment(outDir, $"{filePrefix}_{label}", label, cond, oneSeries, observations, isRotation: true);
            }
        }

        /// <summary>
        /// 绘制总对比位置图和旋转图,按 condition 分段。
        /// </summary>
        public static void PlotComparison(
            Dictionary<string, IReadOnlyList<PredictSample>> allRenderSamples,
            IReadOnlyList<PoseObservation> observations,
            IReadOnlyList<ConditionSpan> conditions,
            string outDir,
            string filePrefix)
        {
            List<(string, IReadOnlyList<PredictSample>)> list = new List<(string, IReadOnlyList<PredictSample>)>();
            foreach (var kv in allRenderSamples) list.Add((kv.Key, kv.Value));

            foreach (ConditionSpan cond in conditions)
            {
                PlotSegment(outDir, filePrefix, "comparison_all", cond, list, observations, isRotation: false);
                PlotSegment(outDir, filePrefix, "comparison_all", cond, list, observations, isRotation: true);
            }
        }

        /// <summary>为一个 condition 分段渲染一张 3 子图 PNG (位置或旋转)。</summary>
        private static void PlotSegment(
            string outDir,
            string filePrefix,
            string seriesTitle,
            ConditionSpan cond,
            IReadOnlyList<(string label, IReadOnlyList<PredictSample> samples)> renderSeries,
            IReadOnlyList<PoseObservation> observations,
            bool isRotation)
        {
            string kind = isRotation ? "rotation" : "position";
            string path = System.IO.Path.Combine(outDir, $"{filePrefix}__{cond.Label}__{kind}.png");

            Multiplot mp = new Multiplot();

            // 该段的零点 (用段起点,使横轴从 0 开始且范围小)
            double segZero = cond.StartSeconds;

            // 3 个面板定义
            (string name, System.Func<PredictSample, double> pick, System.Func<PoseObservation, double> pickObs)[] panels = isRotation
                ? new (string, System.Func<PredictSample, double>, System.Func<PoseObservation, double>)[]
                {
                    ("Roll (deg)", s => EulerConverter.ToEulerDegrees(s.Rotation).roll, o => EulerConverter.ToEulerDegrees(o.Rotation).roll),
                    ("Pitch (deg)", s => EulerConverter.ToEulerDegrees(s.Rotation).pitch, o => EulerConverter.ToEulerDegrees(o.Rotation).pitch),
                    ("Yaw (deg)", s => EulerConverter.ToEulerDegrees(s.Rotation).yaw, o => EulerConverter.ToEulerDegrees(o.Rotation).yaw),
                }
                : new (string, System.Func<PredictSample, double>, System.Func<PoseObservation, double>)[]
                {
                    ("X position (m)", s => s.Position.X, o => o.Position.X),
                    ("Y position (m)", s => s.Position.Y, o => o.Position.Y),
                    ("Z position (m)", s => s.Position.Z, o => o.Position.Z),
                };

            for (int i = 0; i < 3; i++)
            {
                ScottPlot.Plot sp = mp.AddPlot();
                // 标题含算法名 + 条件 + 维度
                sp.Title($"{seriesTitle} — {cond.Label} — {panels[i].name}", TitleFontSize);

                sp.Axes.Left.Label.Text = panels[i].name;
                sp.Axes.Left.Label.FontSize = AxisLabelFontSize;
                sp.Axes.Left.TickLabelStyle.FontSize = TickFontSize;

                sp.Axes.Bottom.Label.Text = "time (s, relative to segment start)  ←  real render_mono_ms (~60fps)";
                sp.Axes.Bottom.Label.FontSize = AxisLabelFontSize;
                sp.Axes.Bottom.TickLabelStyle.FontSize = TickFontSize;

                // 该段内的观测散点
                System.Collections.Generic.List<double> obsT = new System.Collections.Generic.List<double>();
                System.Collections.Generic.List<double> obsV = new System.Collections.Generic.List<double>();
                foreach (PoseObservation o in observations)
                {
                    if (o.CaptureTimeSeconds < cond.StartSeconds || o.CaptureTimeSeconds > cond.EndSeconds) continue;
                    obsT.Add(o.CaptureTimeSeconds - segZero);
                    obsV.Add(panels[i].pickObs(o));
                }
                if (obsT.Count > 0)
                {
                    var obsScatter = sp.Add.ScatterPoints(obsT.ToArray(), obsV.ToArray());
                    obsScatter.Color = ObsColor;
                    obsScatter.MarkerSize = ObsMarkerSize;
                    obsScatter.MarkerShape = MarkerShape.FilledCircle;
                    obsScatter.LegendText = "observations (5fps)";
                }

                // 该段内的 render 连续粗线
                foreach (var (label, samples) in renderSeries)
                {
                    System.Collections.Generic.List<double> rt = new System.Collections.Generic.List<double>();
                    System.Collections.Generic.List<double> rv = new System.Collections.Generic.List<double>();
                    foreach (PredictSample s in samples)
                    {
                        if (s.RenderTimeSeconds < cond.StartSeconds || s.RenderTimeSeconds > cond.EndSeconds) continue;
                        rt.Add(s.RenderTimeSeconds - segZero);
                        rv.Add(panels[i].pick(s));
                    }
                    if (rt.Count > 0)
                    {
                        var scatter = sp.Add.ScatterLine(rt.ToArray(), rv.ToArray());
                        scatter.Color = GetColor(label);
                        scatter.LegendText = $"{label} (upsampled render)";
                        scatter.LineWidth = RenderLineWidth;
                    }
                }

                sp.Legend.FontSize = LegendFontSize;
                sp.Legend.Alignment = Alignment.UpperLeft;
                sp.ShowLegend();
            }

            mp.SavePng(path, Width, Height);
        }
    }
}

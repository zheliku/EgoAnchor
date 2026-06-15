using System;
using System.Collections.Generic;
using System.Linq;
using EgoAnchor.Tools3.Core;
using EgoAnchor.Tools3.Data;
using EgoAnchor.Tools3.Eval;
using EgoAnchor.Tools3.Sim;
using ScottPlot;

namespace EgoAnchor.Tools3.Viz
{
    /// <summary>
    /// 用 ScottPlot 画对比曲线 (类似 Python matplotlib)。
    ///
    /// 每张图是 2x3 的 6 子图:
    ///   上排: X / Y / Z 位置 (米)
    ///   下排: 旋转向量 RotVecX / RotVecY / RotVecZ (度) —— 见 Core/Rotation.cs 说明,
    ///         用旋转向量而非欧拉角, 无 gimbal lock, 平滑当且仅当旋转平滑。
    ///
    /// 每个子图里:
    ///   - 黑色散点 = 观测 pose (真实 ~5fps 输入)
    ///   - 彩色连线 = 各算法实时生成的 ~60fps render 轨迹
    ///
    /// 产出两类图:
    ///   PlotSingle      —— 单算法一张图 (观测 + 该算法 render)
    ///   PlotComparison  —— 所有算法叠加在一张图
    /// </summary>
    public static class TrajectoryPlotter
    {
        /// <summary>静态构造: 设置支持中文的默认字体, 避免图里中文显示成方块。</summary>
        static TrajectoryPlotter()
        {
            // Windows 上优先用微软雅黑/黑体; 用 GetTypeface 拿到的 FamilyName 与请求名匹配才算存在。
            foreach (string font in new[] { "Microsoft YaHei", "微软雅黑", "SimHei", "黑体", "Microsoft JhengHei" })
            {
                var typeface = ScottPlot.Fonts.GetTypeface(font, false, false);
                if (typeface != null && typeface.FamilyName.Equals(font, StringComparison.OrdinalIgnoreCase))
                {
                    ScottPlot.Fonts.Default = font;
                    return;
                }
            }

            string detected = ScottPlot.Fonts.Detect("平滑度滞后位置旋转观测");
            if (!string.IsNullOrEmpty(detected))
            {
                ScottPlot.Fonts.Default = detected;
            }
        }

        // 每个面板: 标题 + 从 pose 取标量的函数
        private static readonly (string Title, Func<Pose, double> Pick)[] Panels =
        {
            ("X position (m)", p => p.Position.X),
            ("Y position (m)", p => p.Position.Y),
            ("Z position (m)", p => p.Position.Z),
            ("RotVec X (deg)", p => Rotation.ToRotationVectorDegrees(p.Rotation).x),
            ("RotVec Y (deg)", p => Rotation.ToRotationVectorDegrees(p.Rotation).y),
            ("RotVec Z (deg)", p => Rotation.ToRotationVectorDegrees(p.Rotation).z),
        };

        // 固定算法配色, 跨图一致
        private static readonly Dictionary<string, Color> LabelColors = new()
        {
            // 参照基线
            ["raw_zoh"] = new Color(0x99, 0x99, 0x99),                // 灰
            ["deadreckoning_spline"] = new Color(0x8c, 0x56, 0x4b),   // 棕
            // B 行: 外推 + 误差融合 (实线系)
            ["cv_blend"] = new Color(0x2c, 0xa0, 0x2c),               // 绿
            ["kalman_blend"] = new Color(0xd6, 0x27, 0x28),           // 红
            ["oneeuro_blend"] = new Color(0x94, 0x67, 0xbd),          // 紫
            // C 行: 延迟一周期 + 插值 (与 B 同列同色系, 偏亮以区分)
            ["raw_hermite"] = new Color(0x17, 0xbe, 0xcf),            // 青 (DR 列)
            ["oneeuro_interp"] = new Color(0xe3, 0x77, 0xc2),         // 粉 (1€ 列)
            ["kalman_hermite"] = new Color(0xff, 0x7f, 0x0e),         // 橙 (Kalman 列)
            ["egoanchor"] = new Color(0xbc, 0xbd, 0x22),             // 橄榄 (留给 ego)
        };

        private static readonly Color ObsColor = new(0x20, 0x20, 0x20);

        private static Color ColorFor(string label)
            => LabelColors.TryGetValue(label, out Color c) ? c : new Color(0x7f, 0x7f, 0x7f);

        /// <summary>单算法图。window 非空时只画该时间窗 (相对秒) 的细节。</summary>
        public static void PlotSingle(
            SimResult result,
            IReadOnlyList<Observation> observations,
            double timeZero,
            string outputPath,
            (double start, double end)? window = null)
        {
            RenderMultiplot($"{result.Label}", new[] { result }, observations, timeZero, outputPath, 1700, 1000, window);
        }

        /// <summary>所有算法对比图。window 非空时只画该时间窗 (相对秒) 的细节。</summary>
        public static void PlotComparison(
            IReadOnlyList<SimResult> results,
            IReadOnlyList<Observation> observations,
            double timeZero,
            string outputPath,
            (double start, double end)? window = null)
        {
            string title = window is { } w
                ? $"comparison (zoom {w.start:F1}-{w.end:F1}s)"
                : "comparison (all algorithms)";
            RenderMultiplot(title, results, observations, timeZero, outputPath, 1900, 1100, window);
        }

        /// <summary>
        /// 平滑度 vs 滞后散点图: 每个算法一个点, 横轴=滞后(ms), 纵轴=位置步长RMS(mm, 平滑度)。
        /// 理想算法在**左下角**(既不滞后又平滑)。这是 B 路(零延迟) vs C 路(延迟插值)拍板用的总图。
        /// </summary>
        public static void PlotSmoothnessVsLag(IReadOnlyList<AlgorithmMetrics> metrics, string outputPath)
        {
            var plt = new Plot();
            plt.Title("平滑度 vs 滞后 (左下角最优)");
            plt.Axes.Bottom.Label.Text = "实际滞后 lag (ms)  →  越右越拖影";
            plt.Axes.Left.Label.Text = "位置步长 RMS (mm)  →  越上越抖";

            foreach (AlgorithmMetrics m in metrics)
            {
                Color c = ColorFor(m.Label);
                var marker = plt.Add.Marker(m.LagMs, m.StepPosRmsMm, MarkerShape.FilledCircle, 14f, c);
                marker.LegendText = m.Label;

                var label = plt.Add.Text($" {m.Label}", m.LagMs, m.StepPosRmsMm);
                label.LabelFontSize = 13;
                label.LabelFontColor = c;
                label.OffsetX = 6;
                label.OffsetY = -6;
            }

            plt.ShowLegend(Alignment.UpperRight);
            plt.SavePng(outputPath, 1100, 800);
        }

        private static void RenderMultiplot(
            string title,
            IReadOnlyList<SimResult> results,
            IReadOnlyList<Observation> observations,
            double timeZero,
            string outputPath,
            int width,
            int height,
            (double start, double end)? window)
        {
            bool zoomed = window.HasValue;
            float obsMarkerSize = zoomed ? 9f : 5f;
            float lineWidth = zoomed ? 2.2f : 1.6f;

            // 预计算观测散点的时间和各通道值
            int obsCount = observations.Count;
            double[] obsT = new double[obsCount];
            var obsVals = new double[Panels.Length][];
            for (int k = 0; k < Panels.Length; k++)
            {
                obsVals[k] = new double[obsCount];
            }

            for (int i = 0; i < obsCount; i++)
            {
                obsT[i] = observations[i].TimeSeconds - timeZero;
                for (int k = 0; k < Panels.Length; k++)
                {
                    obsVals[k][i] = Panels[k].Pick(observations[i].Pose);
                }
            }

            // 预计算每个算法每个通道的曲线
            var seriesT = new Dictionary<string, double[]>();
            var seriesVals = new Dictionary<string, double[][]>();
            foreach (SimResult r in results)
            {
                int n = r.RenderSamples.Count;
                double[] t = new double[n];
                var vals = new double[Panels.Length][];
                for (int k = 0; k < Panels.Length; k++)
                {
                    vals[k] = new double[n];
                }

                for (int j = 0; j < n; j++)
                {
                    t[j] = r.RenderSamples[j].TimeSeconds - timeZero;
                    for (int k = 0; k < Panels.Length; k++)
                    {
                        vals[k][j] = Panels[k].Pick(r.RenderSamples[j].Pose);
                    }
                }

                seriesT[r.Label] = t;
                seriesVals[r.Label] = vals;
            }

            var multiplot = new Multiplot();
            multiplot.RemovePlot(multiplot.GetPlots().FirstOrDefault()!); // 清掉默认空 plot (若有)

            for (int k = 0; k < Panels.Length; k++)
            {
                Plot plt = multiplot.AddPlot();
                plt.Title($"{title}  —  {Panels[k].Title}");
                plt.Axes.Bottom.Label.Text = "time (s)";

                // 观测散点 (黑色, 空心圆, 不连线)。zoom 时点更大、连线更粗。
                var obsMarkers = plt.Add.Markers(obsT, obsVals[k], MarkerShape.OpenCircle, obsMarkerSize, ObsColor);
                obsMarkers.LegendText = "observation (~5fps)";

                // 各算法 render 线
                foreach (SimResult r in results)
                {
                    var line = plt.Add.ScatterLine(seriesT[r.Label], seriesVals[r.Label][k], ColorFor(r.Label));
                    line.LineWidth = lineWidth;
                    line.MarkerSize = 0; // 纯线
                    line.LegendText = r.Label;
                }

                // zoom: 限定 X 轴时间窗, 并按窗内数据自动定 Y 轴
                if (window is { } w)
                {
                    plt.Axes.SetLimitsX(w.start, w.end);
                    AutoScaleYInWindow(plt, w, obsT, obsVals[k], results, seriesT, seriesVals, k);
                }

                plt.ShowLegend(Alignment.UpperRight);
            }

            IMultiplotExtensions.SavePng(multiplot, outputPath, width, height);
        }

        /// <summary>在给定时间窗内, 根据观测和所有算法的值自动设定 Y 轴范围 (留 8% 边距)。</summary>
        private static void AutoScaleYInWindow(
            Plot plt,
            (double start, double end) w,
            double[] obsT,
            double[] obsVals,
            IReadOnlyList<SimResult> results,
            Dictionary<string, double[]> seriesT,
            Dictionary<string, double[][]> seriesVals,
            int channel)
        {
            double min = double.PositiveInfinity, max = double.NegativeInfinity;

            void Consider(double[] ts, double[] vs)
            {
                for (int i = 0; i < ts.Length; i++)
                {
                    if (ts[i] < w.start || ts[i] > w.end)
                    {
                        continue;
                    }

                    if (vs[i] < min) min = vs[i];
                    if (vs[i] > max) max = vs[i];
                }
            }

            Consider(obsT, obsVals);
            foreach (SimResult r in results)
            {
                Consider(seriesT[r.Label], seriesVals[r.Label][channel]);
            }

            if (double.IsFinite(min) && double.IsFinite(max))
            {
                double pad = (max - min) * 0.08;
                if (pad < 1e-9)
                {
                    pad = Math.Abs(max) * 0.01 + 1e-4;
                }

                plt.Axes.SetLimitsY(min - pad, max + pad);
            }
        }
    }
}

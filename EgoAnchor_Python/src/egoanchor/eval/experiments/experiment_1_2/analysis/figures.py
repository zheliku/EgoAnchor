"""实验一/二论文图的项目内实现。"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np

from egoanchor.visuals import (
    ARRIVAL_COLOR_HEX,
    CAPTURE_COLOR_HEX,
    EGOANCHOR_COLOR_HEX,
    ONE_EURO_COLOR_HEX,
    PAPER_GRID_COLOR,
    PAPER_MUTED_COLOR,
    PAPER_PAIR_COLOR,
    PAPER_TEXT_COLOR,
    apply_paper_style,
)

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from .metrics import (
    FULL_VARIANT,
    LINEAR_SLERP_VARIANT,
    METHODS,
    NO_STATIC_LOCK,
    PaperResults,
    SMOOTHED_EXTRAPOLATION_VARIANT,
    paired_metric_matrix,
    segment_identity,
)


_SHORT_LABELS = {
    "Arrival-Hold": "Arrival",
    "Capture-Hold": "Capture",
    "One-Euro Anchor": "One-Euro",
    FULL_VARIANT: "EgoAnchor",
}
_METHOD_COLORS = {
    "Arrival-Hold": ARRIVAL_COLOR_HEX,
    "Capture-Hold": CAPTURE_COLOR_HEX,
    "One-Euro Anchor": ONE_EURO_COLOR_HEX,
    FULL_VARIANT: EGOANCHOR_COLOR_HEX,
}
_PAIR_COLOR = PAPER_PAIR_COLOR
_FULL_COLOR = _METHOD_COLORS[FULL_VARIANT]
_DISABLED_COLOR = "#B07AA1"
_EXTRAPOLATION_COLOR = "#2A9D8F"
_HERMITE_COLOR = "#9C6ADE"
_DYNAMIC_X_LIMITS = (150.0, 400.0)
_EXP2_PANEL_HEIGHT_IN = 2.18
_EXP2_NARROW_WIDTH_IN = 1.26
_EXP2_WIDE_WIDTH_IN = 2.80
_EXP2_AXIS_BOTTOM = 0.25
_EXP2_AXIS_TOP = 0.97
_COMPOSITE_FONT_SIZE = 7.4
"""正文四面板组合图的基础字号。"""

_COMPOSITE_TITLE_SIZE = 7.2
"""单行子图标题字号；与正文接近但不压过图内数据。"""


def _configure() -> None:
    """应用论文面板的固定字体、线宽和导出分辨率。"""

    apply_paper_style(font_size=7.6, dpi=260)


def _clean_axis(axis: Any, grid: str | None = "y") -> None:
    """保留轻量网格并隐藏顶部和右侧边框。"""

    if grid is not None:
        axis.grid(
            axis=grid,
            color=PAPER_GRID_COLOR,
            linestyle=":",
            linewidth=0.70,
            alpha=0.65,
        )
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)


def _save_pair(
    figure: Any,
    root: Path,
    stem: str,
    *,
    crop_to_content: bool = True,
) -> tuple[Path, Path]:
    """同时保存 PNG 与矢量 PDF，并按需保留固定画布。"""

    root.mkdir(parents=True, exist_ok=True)
    png = root / f"{stem}.png"
    pdf = root / f"{stem}.pdf"
    crop_options = (
        {"bbox_inches": "tight", "pad_inches": 0.035}
        if crop_to_content
        else {}
    )
    figure.savefig(png, **crop_options)
    figure.savefig(
        pdf,
        metadata={"CreationDate": None, "ModDate": None},
        **crop_options,
    )
    plt.close(figure)
    return png, pdf


def _save_axis_crops(
    figure: Any,
    root: Path,
    stems: Sequence[str],
    *,
    pad_inches: float = 0.025,
) -> tuple[tuple[Path, Path], ...]:
    """从组合图裁切各坐标轴，保证独立子图与正文图使用同一视觉编码。"""

    if len(figure.axes) != len(stems):
        raise ValueError("组合图坐标轴数量与独立子图文件名数量不一致")
    if pad_inches < 0.0:
        raise ValueError("独立子图裁切边距不得为负数")
    root.mkdir(parents=True, exist_ok=True)
    saved: list[tuple[Path, Path]] = []
    axis_visibility = tuple(axis.get_visible() for axis in figure.axes)
    axis_legends = tuple(axis.get_legend() for axis in figure.axes)
    axis_legend_visibility = tuple(
        legend.get_visible() if legend is not None else None
        for legend in axis_legends
    )
    legend_visibility = tuple(legend.get_visible() for legend in figure.legends)
    try:
        for legend in figure.legends:
            legend.set_visible(False)
        for selected, stem in zip(figure.axes, stems, strict=True):
            for axis in figure.axes:
                axis.set_visible(axis is selected)
            for axis, legend in zip(figure.axes, axis_legends, strict=True):
                if legend is not None:
                    legend.set_visible(axis is selected)
            figure.canvas.draw()
            renderer = figure.canvas.get_renderer()
            bounds = selected.get_tightbbox(renderer).transformed(
                figure.dpi_scale_trans.inverted()
            )
            png = root / f"{stem}.png"
            pdf = root / f"{stem}.pdf"
            figure.savefig(png, bbox_inches=bounds, pad_inches=pad_inches)
            figure.savefig(
                pdf,
                bbox_inches=bounds,
                pad_inches=pad_inches,
                metadata={"CreationDate": None, "ModDate": None},
            )
            saved.append((png, pdf))
    finally:
        for axis, visible in zip(figure.axes, axis_visibility, strict=True):
            axis.set_visible(visible)
        for legend, visible in zip(
            axis_legends,
            axis_legend_visibility,
            strict=True,
        ):
            if legend is not None and visible is not None:
                legend.set_visible(visible)
        for legend, visible in zip(figure.legends, legend_visibility, strict=True):
            legend.set_visible(visible)
        figure.canvas.draw()
    return tuple(saved)


def _set_experiment_two_layout(
    figure: Any,
    *,
    left: float,
    right: float,
) -> None:
    """固定实验二所有面板的纵向坐标轴边界，保证 LaTeX 排版后齐平。"""

    figure.subplots_adjust(
        left=left,
        right=right,
        bottom=_EXP2_AXIS_BOTTOM,
        top=_EXP2_AXIS_TOP,
    )


def _remove_stale_panels(root: Path, published: Sequence[Path]) -> None:
    """删除分析目录中不属于本次组合图与子图清单的旧托管图片。"""

    keep = {path.resolve() for path in published}
    for suffix in ("pdf", "png"):
        for candidate in root.glob(f"figure[23]*.{suffix}"):
            if candidate.resolve() not in keep:
                candidate.unlink()


def _metric_values(
    rows: Mapping[str, tuple[Mapping[str, Any], ...]],
    variant: str,
    key: str,
) -> np.ndarray:
    """提取一个方法的有限片段指标，并拒绝空序列。"""

    values: np.ndarray = np.asarray(
        [float(row[key]) for row in rows.get(variant, ())],
        dtype=float,
    )
    values = values[np.isfinite(values)]
    if values.size == 0:
        raise ValueError(f"论文图缺少 {variant}/{key} 数据")
    return values


def _paired_rows(
    rows: Mapping[str, tuple[Mapping[str, Any], ...]],
    full_variant: str,
    disabled_variant: str,
    value_key: str,
) -> tuple[np.ndarray, np.ndarray]:
    """按片段身份严格配对两个配置，并拒绝重复或缺失键。"""

    paired = paired_metric_matrix(
        rows,
        (full_variant, disabled_variant),
        (value_key,),
    )
    return (
        paired[:, 0, 0],
        paired[:, 1, 0],
    )


def _unique_metric_matrix(
    rows: Sequence[Mapping[str, Any]],
    keys: Sequence[str],
    context: str,
) -> np.ndarray:
    """按片段身份读取同一行内的配对指标，并拒绝重复或非有限值。"""

    indexed: dict[tuple[str, str, str], tuple[float, ...]] = {}
    for row in rows:
        identity = segment_identity(row)
        if identity in indexed:
            raise ValueError(f"{context} 片段键重复：{identity}")
        values = tuple(float(row[key]) for key in keys)
        if not np.isfinite(values).all():
            raise ValueError(f"{context} 包含非有限值：{identity}")
        indexed[identity] = values
    if not indexed:
        raise ValueError(f"{context} 缺少配对数据")
    return np.asarray([indexed[identity] for identity in sorted(indexed)], dtype=float)


def _paired_axis(
    axis: Any,
    full: np.ndarray,
    disabled: np.ndarray,
    ylabel: str,
    labels: tuple[str, str] = ("On", "Off"),
    logarithmic: bool = False,
    endpoint_colors: tuple[str, str] = (_FULL_COLOR, _DISABLED_COLOR),
) -> None:
    """绘制逐片段配对线与中位数粗线。"""

    for full_value, disabled_value in zip(full, disabled, strict=True):
        axis.plot(
            [0, 1],
            [full_value, disabled_value],
            color=_PAIR_COLOR,
            linewidth=0.8,
            alpha=0.35,
            zorder=1,
        )
    axis.scatter(np.zeros_like(full), full, color=endpoint_colors[0], s=11, alpha=0.38, zorder=2)
    axis.scatter(np.ones_like(disabled), disabled, color=endpoint_colors[1], s=11, alpha=0.38, zorder=2)
    axis.plot(
        [0, 1],
        [np.median(full), np.median(disabled)],
        color=_PAIR_COLOR,
        linewidth=2.35,
        zorder=3,
    )
    axis.scatter(0, np.median(full), marker="D", color=endpoint_colors[0], s=42, zorder=4)
    axis.scatter(1, np.median(disabled), marker="D", color=endpoint_colors[1], s=42, zorder=4)
    axis.set_xticks((0, 1), labels)
    axis.set_xlim(-0.20, 1.20)
    axis.set_ylabel(ylabel, labelpad=1.0)
    if logarithmic:
        axis.set_yscale("log")
    else:
        axis.set_ylim(bottom=0)
    _clean_axis(axis)


def _paired_panel(
    full: np.ndarray,
    disabled: np.ndarray,
    ylabel: str,
    labels: tuple[str, str] = ("On", "Off"),
    logarithmic: bool = False,
    endpoint_colors: tuple[str, str] = (_FULL_COLOR, _DISABLED_COLOR),
) -> Any:
    """创建可直接放入 LaTeX 子图的单个配对面板。"""

    # LaTeX 以 0.18\textwidth 放置前三个图三面板；原生宽度与目标宽度一致可避免字体缩小。
    figure, axis = plt.subplots(
        figsize=(_EXP2_NARROW_WIDTH_IN, _EXP2_PANEL_HEIGHT_IN)
    )
    _paired_axis(axis, full, disabled, ylabel, labels, logarithmic, endpoint_colors)
    _set_experiment_two_layout(figure, left=0.34, right=0.96)
    return figure


def _plot_temporal_axis(axis: Any, paired_points: np.ndarray) -> None:
    """绘制预测式追踪与两种历史状态查询的配对 lag--residual 分布。"""

    labels = (
        "Predictive tracking",
        "History query\n(Linear/SLERP)",
        "History query\n(Hermite)",
    )
    colors = (_EXTRAPOLATION_COLOR, _FULL_COLOR, _HERMITE_COLOR)
    markers = ("D", "s", "o")
    for episode in paired_points:
        axis.plot(
            episode[:, 0],
            episode[:, 1],
            color=_PAIR_COLOR,
            linewidth=0.65,
            alpha=0.20,
            zorder=1,
        )
    for index, (label, color, marker) in enumerate(
        zip(labels, colors, markers, strict=True)
    ):
        points = paired_points[:, index, :]
        axis.scatter(
            points[:, 0],
            points[:, 1],
            s=15.0 if index < 2 else 11.0,
            alpha=0.38 if index < 2 else 0.24,
            marker=marker,
            color=color,
            label=label,
            zorder=2,
        )
        median_x, median_y = np.median(points, axis=0)
        q1_x, q3_x = np.quantile(points[:, 0], (0.25, 0.75))
        q1_y, q3_y = np.quantile(points[:, 1], (0.25, 0.75))
        axis.errorbar(
            median_x,
            median_y,
            xerr=[[median_x - q1_x], [q3_x - median_x]],
            yerr=[[median_y - q1_y], [q3_y - median_y]],
            fmt=marker,
            markersize=6,
            capsize=3.5,
            linewidth=1.7,
            color=color,
        )
    axis.set_xlabel("Effective latency (ms)")
    axis.set_ylabel("LA-RMSE, translation (mm)")
    all_points = paired_points.reshape(-1, paired_points.shape[-1])
    axis.set_xlim(
        min(_DYNAMIC_X_LIMITS[0], float(np.min(all_points[:, 0])) * 0.96),
        max(_DYNAMIC_X_LIMITS[1], float(np.max(all_points[:, 0])) * 1.02),
    )
    y_step_mm = 5.0
    y_max_mm = max(
        y_step_mm,
        y_step_mm * np.ceil(float(np.max(all_points[:, 1])) * 1.08 / y_step_mm),
    )
    axis.set_ylim(0.0, y_max_mm)
    axis.annotate("better", xy=(168, 2.2), xytext=(220, 5.4), arrowprops={"arrowstyle": "->", "linewidth": 0.9})
    _clean_axis(axis, "both")
    axis.legend(
        frameon=False,
        ncol=1,
        loc="upper left",
        bbox_to_anchor=(-0.01, 1.0),
        borderaxespad=0.0,
        handletextpad=0.4,
        labelspacing=0.25,
    )


def build_temporal_strategy_panel(paired_points: np.ndarray) -> Any:
    """创建可直接放入 LaTeX 子图的预测与历史查询审计面板。"""

    figure, axis = plt.subplots(
        figsize=(_EXP2_WIDE_WIDTH_IN, _EXP2_PANEL_HEIGHT_IN)
    )
    _plot_temporal_axis(axis, paired_points)
    _set_experiment_two_layout(figure, left=0.18, right=0.94)
    return figure


def summarize_risk_coverage(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, float | int], ...]:
    """在固定 coverage 网格上汇总 event 曲线，且不拆分同分候选组。

    每个网格点使用该 event 中第一个 coverage 不小于目标值的完整同分组，
    再跨 event 汇总 median/IQR。这样图形不会凭空为 tied score 排序。
    """

    grouped: defaultdict[tuple[str, str, str], list[tuple[float, float]]] = defaultdict(list)
    for row in rows:
        identity = segment_identity(row)
        grouped[identity].append((float(row["coverage"]), float(row["selective_risk_mm"])))
    if not grouped:
        raise ValueError("VCD risk-coverage 图缺少 event 曲线")
    curves: list[tuple[np.ndarray, np.ndarray]] = []
    for identity, points in sorted(grouped.items()):
        ordered = sorted(points)
        coverage: np.ndarray = np.asarray(
            [point[0] for point in ordered],
            dtype=float,
        )
        risk: np.ndarray = np.asarray(
            [point[1] for point in ordered],
            dtype=float,
        )
        if (
            coverage.size == 0
            or not np.isfinite(coverage).all()
            or not np.isfinite(risk).all()
            or np.any(np.diff(coverage) <= 0.0)
            or not np.isclose(coverage[-1], 1.0)
        ):
            raise ValueError(f"VCD risk-coverage event 曲线非法：{identity}")
        curves.append((coverage, risk))

    output: list[Mapping[str, float | int]] = []
    for target in np.linspace(0.05, 1.0, 20):
        values = []
        for coverage, risk in curves:
            index = min(int(np.searchsorted(coverage, target, side="left")), len(coverage) - 1)
            values.append(float(risk[index]))
        quantiles: np.ndarray = np.quantile(
            np.asarray(values, dtype=float),
            (0.5, 0.25, 0.75),
        )
        output.append(
            {
                "coverage": float(target),
                "selective_risk_median_mm": float(quantiles[0]),
                "selective_risk_q1_mm": float(quantiles[1]),
                "selective_risk_q3_mm": float(quantiles[2]),
                "event_count": len(curves),
            }
        )
    return tuple(output)


def build_vcd_risk_coverage_panel(results: PaperResults) -> Any:
    """绘制 VCD 分数诱导的 event 曲线及跨 event median/IQR。"""

    grouped: defaultdict[tuple[str, str, str], list[tuple[float, float]]] = defaultdict(list)
    for row in results.vcd_risk_coverage:
        grouped[segment_identity(row)].append(
            (float(row["coverage"]), float(row["selective_risk_mm"]))
        )
    if not grouped:
        raise ValueError("VCD risk-coverage 图缺少 event 曲线")

    figure, axis = plt.subplots(
        figsize=(_EXP2_NARROW_WIDTH_IN, _EXP2_PANEL_HEIGHT_IN)
    )
    summary = summarize_risk_coverage(results.vcd_risk_coverage)
    coverage: np.ndarray = np.asarray(
        [float(row["coverage"]) for row in summary],
        dtype=float,
    )
    median: np.ndarray = np.asarray(
        [float(row["selective_risk_median_mm"]) for row in summary],
        dtype=float,
    )
    q1: np.ndarray = np.asarray(
        [float(row["selective_risk_q1_mm"]) for row in summary],
        dtype=float,
    )
    q3: np.ndarray = np.asarray(
        [float(row["selective_risk_q3_mm"]) for row in summary],
        dtype=float,
    )
    axis.fill_between(coverage, q1, q3, color=_FULL_COLOR, alpha=0.18, linewidth=0.0, label="IQR")
    axis.plot(coverage, median, color=_FULL_COLOR, linewidth=1.8, label="Median", zorder=3)
    axis.set_xlim(0.0, 1.0)
    axis.set_ylim(max(0.0, float(np.min(q1)) - 0.45), float(np.max(q3)) + 0.45)
    axis.set_xticks((0.0, 0.5, 1.0), ("0", "50", "100"))
    axis.set_xlabel("Retained (%)")
    axis.set_ylabel("Mean error (mm)")
    _clean_axis(axis, "both")
    axis.legend(
        frameon=False,
        loc="upper left",
        borderaxespad=0.25,
        handlelength=1.0,
        handletextpad=0.3,
        labelspacing=0.2,
    )
    _set_experiment_two_layout(figure, left=0.34, right=0.96)
    return figure


def _require_finite_matrix(values: np.ndarray, context: str) -> np.ndarray:
    """验证绘图矩阵非空且全部有限，并返回浮点矩阵。"""

    matrix = np.asarray(values, dtype=float)
    if matrix.size == 0 or not np.isfinite(matrix).all():
        raise ValueError(f"{context} 缺少有限绘图值")
    return matrix


def _draw_paper_metric_axis(
    axis: Any,
    rows: Mapping[str, tuple[Mapping[str, Any], ...]],
    error_key: str,
    jitter_key: str,
    unit: str,
) -> None:
    """在同一纵轴上用透明箱线图绘制误差与残差抖动。"""

    paired = _require_finite_matrix(
        paired_metric_matrix(rows, METHODS, (error_key, jitter_key)),
        f"实验一 {error_key}/{jitter_key}",
    )
    positions: np.ndarray = np.arange(len(METHODS), dtype=float)
    for method_index, method in enumerate(METHODS):
        color = _METHOD_COLORS[method]
        for metric_index, (offset, marker, hollow) in enumerate(
            ((-0.20, "o", False), (0.20, "D", True))
        ):
            linestyle = "-" if metric_index == 0 else "--"
            values = paired[:, method_index, metric_index]
            center = positions[method_index] + offset
            raw_offsets = np.linspace(-0.036, 0.036, values.size)
            axis.scatter(
                center + raw_offsets,
                values,
                s=8.0,
                marker=marker,
                facecolors="none" if hollow else color,
                edgecolors=color,
                linewidths=0.55,
                alpha=0.24,
                zorder=2,
            )
            boxplot = axis.boxplot(
                [values],
                positions=[center],
                widths=0.24,
                patch_artist=True,
                manage_ticks=False,
                showfliers=False,
                showmeans=True,
                whis=1.5,
                boxprops={
                    "facecolor": "none",
                    "edgecolor": color,
                    "linewidth": 1.35,
                    "linestyle": linestyle,
                },
                medianprops={"color": color, "linewidth": 1.85},
                whiskerprops={
                    "color": color,
                    "linewidth": 1.05,
                    "linestyle": linestyle,
                },
                capprops={
                    "color": color,
                    "linewidth": 1.05,
                    "linestyle": linestyle,
                },
                meanprops={
                    "marker": "o",
                    "markerfacecolor": color,
                    "markeredgecolor": "white",
                    "markeredgewidth": 0.55,
                    "markersize": 4.0,
                },
                zorder=3,
            )
            boxplot["boxes"][0].set_linestyle(linestyle)
            for artist in (*boxplot["whiskers"], *boxplot["caps"]):
                artist.set_linestyle(linestyle)
    axis.set_xticks(
        positions,
        [_SHORT_LABELS[method] for method in METHODS],
        rotation=27,
        ha="right",
        rotation_mode="anchor",
    )
    axis.set_xlim(-0.48, len(METHODS) - 0.52)
    axis.set_ylim(bottom=0.0)
    axis.set_ylabel(f"Value ({unit})")
    axis.tick_params(axis="both", length=2.6, width=0.75, pad=2.0)
    _clean_axis(axis)


def build_exp1_behavior_figure(results: PaperResults) -> Any:
    """生成实验一正文使用的四面板单轴组合图。"""

    apply_paper_style(font_size=_COMPOSITE_FONT_SIZE)
    figure, axes = plt.subplots(1, 4, figsize=(7.15, 2.50))
    specifications = (
        (
            results.static_segments,
            "centered_p95_mm",
            "frame_increment_p95_mm",
            "mm",
            "(a) Static translation",
        ),
        (
            results.static_segments,
            "centered_rotation_p95_deg",
            "frame_rotation_increment_p95_deg",
            "deg",
            "(b) Static rotation",
        ),
        (
            results.translation_segments,
            "aligned_rmse_mm",
            "aligned_residual_increment_p95_mm",
            "mm",
            "(c) Dynamic translation",
        ),
        (
            results.rotation_segments,
            "aligned_rmse_deg",
            "aligned_residual_increment_p95_deg",
            "deg",
            "(d) Dynamic rotation",
        ),
    )
    for axis, (rows, error_key, jitter_key, unit, title) in zip(
        axes, specifications, strict=True
    ):
        _draw_paper_metric_axis(axis, rows, error_key, jitter_key, unit)
        axis.set_title(
            title,
            loc="left",
            fontsize=_COMPOSITE_TITLE_SIZE,
            fontweight="bold",
        )
    legend_handles = (
        Line2D(
            (),
            (),
            color=PAPER_TEXT_COLOR,
            marker="o",
            linestyle="-",
            markersize=5.0,
            label="Head-motion leakage / LA-RMSE",
        ),
        Line2D(
            (),
            (),
            color=PAPER_MUTED_COLOR,
            marker="D",
            markerfacecolor="white",
            linestyle="--",
            markersize=5.0,
            label="Jitter P95",
        ),
        Line2D(
            (),
            (),
            color=PAPER_TEXT_COLOR,
            marker="o",
            markeredgecolor="white",
            markeredgewidth=0.45,
            linestyle="none",
            markersize=4.0,
            label="Mean",
        ),
    )
    figure.legend(
        handles=legend_handles,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.985),
        ncol=3,
        frameon=False,
        handletextpad=0.35,
        columnspacing=1.4,
    )
    figure.subplots_adjust(
        left=0.080,
        right=0.995,
        bottom=0.220,
        top=0.800,
        wspace=0.32,
    )
    return figure


def _draw_vcd_paper_axis(axis: Any, results: PaperResults) -> None:
    """绘制全部 event 风险曲线及跨 event 的中位数和四分位带。"""

    grouped: defaultdict[tuple[str, str, str], list[tuple[float, float]]] = defaultdict(list)
    for row in results.vcd_risk_coverage:
        grouped[segment_identity(row)].append(
            (float(row["coverage"]), float(row["selective_risk_mm"]))
        )
    if not grouped:
        raise ValueError("实验二正文图缺少 VCD event 曲线")
    for identity, points in sorted(grouped.items()):
        ordered: np.ndarray = np.asarray(sorted(points), dtype=float)
        if (
            not np.isfinite(ordered).all()
            or np.any(np.diff(ordered[:, 0]) <= 0.0)
            or not np.isclose(ordered[-1, 0], 1.0)
        ):
            raise ValueError(f"实验二正文图的 VCD event 曲线非法：{identity}")
        event_coverage = np.concatenate(([0.0], ordered[:, 0]))
        event_risk = np.concatenate(([ordered[0, 1]], ordered[:, 1]))
        axis.plot(
            event_coverage,
            event_risk,
            color=PAPER_PAIR_COLOR,
            linewidth=0.55,
            alpha=0.22,
            drawstyle="steps-pre",
            zorder=1,
        )
    summary = summarize_risk_coverage(results.vcd_risk_coverage)
    coverage = np.asarray([float(row["coverage"]) for row in summary])
    median = np.asarray([float(row["selective_risk_median_mm"]) for row in summary])
    q1 = np.asarray([float(row["selective_risk_q1_mm"]) for row in summary])
    q3 = np.asarray([float(row["selective_risk_q3_mm"]) for row in summary])
    coverage = np.concatenate(([0.0], coverage))
    median = np.concatenate(([median[0]], median))
    q1 = np.concatenate(([q1[0]], q1))
    q3 = np.concatenate(([q3[0]], q3))
    axis.fill_between(
        coverage,
        q1,
        q3,
        color=_FULL_COLOR,
        alpha=0.16,
        linewidth=0.0,
        step="pre",
        label="IQR",
        zorder=2,
    )
    axis.plot(
        coverage,
        median,
        color=_FULL_COLOR,
        linewidth=1.8,
        drawstyle="steps-pre",
        label="Median",
        zorder=3,
    )
    axis.set_xlim(0.0, 1.0)
    axis.set_ylim(max(0.0, float(np.min(q1)) - 0.45), float(np.max(q3)) + 0.45)
    axis.set_xticks((0.0, 0.5, 1.0), ("0%", "50%", "100%"))
    axis.set_xlabel("Candidates retained (%)", labelpad=2.0)
    axis.set_ylabel("Risk (mm)", labelpad=1.0)
    axis.legend(
        frameon=False,
        loc="upper left",
        borderaxespad=0.15,
        handlelength=1.0,
        handletextpad=0.35,
        labelspacing=0.18,
    )
    _clean_axis(axis, "both")


def _draw_two_strategy_axis(axis: Any, results: PaperResults) -> None:
    """只展示正文相关的预测式追踪与历史状态查询配对。"""

    variants = (SMOOTHED_EXTRAPOLATION_VARIANT, LINEAR_SLERP_VARIANT)
    points = _require_finite_matrix(
        paired_metric_matrix(
            results.translation_segments,
            variants,
            ("effective_lag_ms", "aligned_rmse_mm"),
        ),
        "实验二两路时序策略",
    )
    labels = ("Predictive tracking", "History query")
    colors = (_EXTRAPOLATION_COLOR, _FULL_COLOR)
    markers = ("D", "s")
    for episode in points:
        axis.plot(
            episode[:, 0],
            episode[:, 1],
            color=PAPER_PAIR_COLOR,
            linewidth=0.65,
            alpha=0.24,
            zorder=1,
        )
    for index, (label, color, marker) in enumerate(
        zip(labels, colors, markers, strict=True)
    ):
        values = points[:, index, :]
        axis.scatter(
            values[:, 0],
            values[:, 1],
            s=15.0,
            alpha=0.42,
            marker=marker,
            color=color,
            label=label,
            zorder=2,
        )
        median_x, median_y = np.median(values, axis=0)
        q1_x, q3_x = np.quantile(values[:, 0], (0.25, 0.75))
        q1_y, q3_y = np.quantile(values[:, 1], (0.25, 0.75))
        axis.errorbar(
            median_x,
            median_y,
            xerr=[[median_x - q1_x], [q3_x - median_x]],
            yerr=[[median_y - q1_y], [q3_y - median_y]],
            fmt=marker,
            markersize=6.0,
            capsize=3.0,
            linewidth=1.45,
            color=color,
            zorder=4,
        )
    axis.set_xlabel("Effective latency (ms)", labelpad=2.0)
    axis.set_ylabel("LA-RMSE (mm)", labelpad=1.0)
    axis.set_ylim(bottom=0.0)
    axis.legend(
        frameon=False,
        loc="lower left",
        borderaxespad=0.15,
        handletextpad=0.35,
        labelspacing=0.18,
    )
    _clean_axis(axis, "both")


def build_exp2_attribution_figure(results: PaperResults) -> Any:
    """生成实验二正文使用的四面板组合图，并隐藏无关 Hermite 条件。"""

    apply_paper_style(font_size=_COMPOSITE_FONT_SIZE)
    capture_alignment = _unique_metric_matrix(
        results.capture_alignment,
        ("capture_p95_mm", "arrival_p95_mm"),
        "实验二采集时刻对齐",
    )
    capture = capture_alignment[:, 0]
    arrival = capture_alignment[:, 1]
    full_static, no_lock = _paired_rows(
        results.static_segments,
        FULL_VARIANT,
        NO_STATIC_LOCK,
        "centered_p95_mm",
    )
    figure = plt.figure(figsize=(7.15, 2.48))
    grid = figure.add_gridspec(1, 4, width_ratios=(1.15, 0.85, 1.18, 1.42))
    axes = tuple(figure.add_subplot(grid[0, index]) for index in range(4))
    _paired_axis(
        axes[0],
        capture,
        arrival,
        "P95 (mm)",
        ("Capture", "Arrival"),
        False,
        (_METHOD_COLORS["Capture-Hold"], _METHOD_COLORS["Arrival-Hold"]),
    )
    _paired_axis(
        axes[1],
        full_static,
        no_lock,
        "P95 (mm)",
        ("On", "Off"),
        False,
    )
    _draw_vcd_paper_axis(axes[2], results)
    _draw_two_strategy_axis(axes[3], results)
    titles = (
        "(a) Capture-time alignment",
        "(b) StaticLock",
        "(c) VCD risk-coverage",
        "(d) Predictive tracking\nvs. history query",
    )
    for axis, title in zip(axes, titles, strict=True):
        axis.set_title(
            title,
            loc="left",
            fontsize=_COMPOSITE_TITLE_SIZE,
            fontweight="bold",
        )
        axis.tick_params(axis="both", length=2.6, width=0.75, pad=2.0)
    for axis in axes[2:]:
        legend = axis.get_legend()
        if legend is not None:
            legend.set_visible(False)
    # 四个面板只共享一份图例，避免 VCD 与时序面板各自占用绘图区。
    figure.legend(
        handles=(
            Patch(
                facecolor=_FULL_COLOR,
                edgecolor="none",
                alpha=0.16,
                label="IQR",
            ),
            Line2D(
                (),
                (),
                color=_FULL_COLOR,
                linewidth=1.8,
                label="Median",
            ),
            Line2D(
                (),
                (),
                color=_EXTRAPOLATION_COLOR,
                marker="D",
                linestyle="-",
                markersize=4.8,
                label="Predictive tracking",
            ),
            Line2D(
                (),
                (),
                color=_FULL_COLOR,
                marker="s",
                linestyle="-",
                markersize=4.8,
                label="History query",
            ),
        ),
        loc="upper center",
        bbox_to_anchor=(0.5, 0.995),
        ncol=4,
        frameon=False,
        handletextpad=0.35,
        columnspacing=1.0,
    )
    figure.subplots_adjust(
        left=0.064,
        right=0.985,
        bottom=0.180,
        top=0.780,
        wspace=0.36,
    )
    return figure


def publish_figures(results: PaperResults, output_root: Path) -> Mapping[str, Path]:
    """发布两张正文组合图，并从同一画布导出八个独立子图。"""

    _configure()
    panels = output_root / "figures"
    panels.mkdir(parents=True, exist_ok=True)

    experiment_one = build_exp1_behavior_figure(results)
    figure2a, figure2b, figure2c, figure2d = _save_axis_crops(
        experiment_one,
        panels,
        (
            "figure2a_static_translation",
            "figure2b_static_rotation",
            "figure2c_dynamic_translation",
            "figure2d_dynamic_rotation",
        ),
    )
    exp1_behavior = _save_pair(
        experiment_one,
        panels,
        "figure2_exp1_behavior",
    )

    experiment_two = build_exp2_attribution_figure(results)
    figure3a, figure3b, figure3c, figure3d = _save_axis_crops(
        experiment_two,
        panels,
        (
            "figure3a_capture_alignment",
            "figure3b_static_lock",
            "figure3c_vcd_risk_coverage",
            "figure3d_temporal_strategies",
        ),
    )
    exp2_attribution = _save_pair(
        experiment_two,
        panels,
        "figure3_exp2_attribution",
    )
    _remove_stale_panels(
        panels,
        (
            *figure2a,
            *figure2b,
            *figure2c,
            *figure2d,
            *figure3a,
            *figure3b,
            *figure3c,
            *figure3d,
            *exp1_behavior,
            *exp2_attribution,
        ),
    )
    return {
        "figure2a_pdf": figure2a[1],
        "figure2a_png": figure2a[0],
        "figure2b_pdf": figure2b[1],
        "figure2b_png": figure2b[0],
        "figure2c_pdf": figure2c[1],
        "figure2c_png": figure2c[0],
        "figure2d_pdf": figure2d[1],
        "figure2d_png": figure2d[0],
        "figure3a_pdf": figure3a[1],
        "figure3a_png": figure3a[0],
        "figure3b_pdf": figure3b[1],
        "figure3b_png": figure3b[0],
        "figure3c_pdf": figure3c[1],
        "figure3c_png": figure3c[0],
        "figure3d_pdf": figure3d[1],
        "figure3d_png": figure3d[0],
        "figure2_composite_pdf": exp1_behavior[1],
        "figure2_composite_png": exp1_behavior[0],
        "figure3_composite_pdf": exp2_attribution[1],
        "figure3_composite_png": exp2_attribution[0],
    }


__all__ = [
    "build_exp1_behavior_figure",
    "build_exp2_attribution_figure",
    "build_temporal_strategy_panel",
    "build_vcd_risk_coverage_panel",
    "publish_figures",
    "summarize_risk_coverage",
]

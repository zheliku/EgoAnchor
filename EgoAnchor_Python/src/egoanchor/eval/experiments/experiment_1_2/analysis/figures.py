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
)

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .metrics import (
    FULL_VARIANT,
    METHODS,
    NO_STATIC_LOCK,
    PaperResults,
    TEMPORAL_STRATEGY_VARIANTS,
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
_PAIR_COLOR = "#7F8790"
_FULL_COLOR = _METHOD_COLORS[FULL_VARIANT]
_DISABLED_COLOR = "#B07AA1"
_EXTRAPOLATION_COLOR = "#2A9D8F"
_HERMITE_COLOR = "#9C6ADE"
_ERROR_AXIS_COLOR = "#374151"
_JITTER_AXIS_COLOR = "#8B3A88"
_MARKERS = ("s", "o", "^", "D")
_DYNAMIC_X_LIMITS = (150.0, 400.0)
_EXP2_PANEL_HEIGHT_IN = 2.18
_EXP2_NARROW_WIDTH_IN = 1.26
_EXP2_WIDE_WIDTH_IN = 2.80
_EXP2_AXIS_BOTTOM = 0.25
_EXP2_AXIS_TOP = 0.97


def _configure() -> None:
    """应用论文面板的固定字体、线宽和导出分辨率。"""

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 7.6,
            "axes.labelsize": 7.6,
            "xtick.labelsize": 7.2,
            "ytick.labelsize": 7.2,
            "legend.fontsize": 7.0,
            "axes.linewidth": 0.9,
            "savefig.dpi": 260,
        }
    )


def _clean_axis(axis: Any, grid: str | None = "y") -> None:
    """保留轻量网格并隐藏顶部和右侧边框。"""

    if grid is not None:
        axis.grid(axis=grid, linestyle=":", linewidth=0.75, alpha=0.35)
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
        {"bbox_inches": "tight", "pad_inches": 0.06}
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
    """删除分析目录中不属于本次八面板清单的旧托管图片。"""

    keep = {path.resolve() for path in published}
    for suffix in ("pdf", "png"):
        for candidate in root.glob(f"figure[23][a-d]_*.{suffix}"):
            if candidate.resolve() not in keep:
                candidate.unlink()


def _metric_values(
    rows: Mapping[str, tuple[Mapping[str, Any], ...]],
    variant: str,
    key: str,
) -> np.ndarray:
    """提取一个方法的有限片段指标，并拒绝空序列。"""

    values = np.asarray([float(row[key]) for row in rows.get(variant, ())], dtype=float)
    values = values[np.isfinite(values)]
    if values.size == 0:
        raise ValueError(f"论文图缺少 {variant}/{key} 数据")
    return values


def _draw_metric_summary(
    axis: Any,
    rows: Mapping[str, tuple[Mapping[str, Any], ...]],
    key: str,
    *,
    horizontal_offset: float,
    marker: str,
    hollow: bool,
) -> None:
    """在指定轴上绘制四方法原始点、中位数与 IQR。"""

    for index, method in enumerate(METHODS):
        values = _metric_values(rows, method, key)
        center = float(index) + horizontal_offset
        raw_offsets = np.linspace(-0.035, 0.035, values.size)
        color = _METHOD_COLORS[method]
        axis.scatter(
            center + raw_offsets,
            values,
            s=6.0,
            alpha=0.20,
            marker=marker,
            facecolors="none" if hollow else color,
            edgecolors=color,
            linewidths=0.45,
            zorder=2,
        )
        median = float(np.median(values))
        q1, q3 = (float(item) for item in np.quantile(values, (0.25, 0.75)))
        axis.errorbar(
            center,
            median,
            yerr=[[median - q1], [q3 - median]],
            fmt=marker,
            markersize=4.7,
            capsize=2.0,
            linewidth=1.15,
            color=color,
            markerfacecolor="white" if hollow else color,
            markeredgecolor=color,
            markeredgewidth=0.85,
            zorder=4,
        )


def build_dual_metric_panel(
    rows: Mapping[str, tuple[Mapping[str, Any], ...]],
    error_key: str,
    jitter_key: str,
    unit: str,
    *,
    error_label: str = "Error P95",
) -> Any:
    """绘制误差与抖动分属左右纵轴的四方法紧凑面板。"""

    # 0.245\textwidth 在 VGTC 双栏中约为 1.75 英寸；原生宽度贴近最终尺寸，
    # 避免 LaTeX 再缩小后把 7 pt 字体压到可读性门槛以下。
    figure, error_axis = plt.subplots(figsize=(1.76, 2.16))
    jitter_axis = error_axis.twinx()
    positions = np.arange(len(METHODS), dtype=float)
    _draw_metric_summary(
        error_axis,
        rows,
        error_key,
        horizontal_offset=-0.12,
        marker="o",
        hollow=False,
    )
    _draw_metric_summary(
        jitter_axis,
        rows,
        jitter_key,
        horizontal_offset=0.12,
        marker="D",
        hollow=True,
    )
    error_axis.set_xticks(
        positions,
        [_SHORT_LABELS[method] for method in METHODS],
        rotation=27,
        ha="right",
        rotation_mode="anchor",
    )
    error_axis.set_xlim(-0.45, len(METHODS) - 0.55)
    error_axis.set_ylim(bottom=0.0)
    jitter_axis.set_ylim(bottom=0.0)
    error_axis.set_ylabel(f"{error_label} ({unit})", color=_ERROR_AXIS_COLOR, labelpad=1.8)
    jitter_axis.set_ylabel(f"Jitter P95 ({unit})", color=_JITTER_AXIS_COLOR, labelpad=2.0)
    error_axis.tick_params(axis="y", colors=_ERROR_AXIS_COLOR, pad=1.5)
    jitter_axis.tick_params(axis="y", colors=_JITTER_AXIS_COLOR, pad=1.5)
    error_axis.tick_params(axis="x", pad=1.8)
    error_axis.grid(axis="y", linestyle=":", linewidth=0.7, alpha=0.30)
    error_axis.spines["top"].set_visible(False)
    jitter_axis.spines["top"].set_visible(False)
    error_axis.spines["right"].set_visible(False)
    jitter_axis.spines["left"].set_visible(False)
    error_axis.spines["left"].set_color(_ERROR_AXIS_COLOR)
    jitter_axis.spines["right"].set_color(_JITTER_AXIS_COLOR)
    figure.tight_layout(pad=0.30)
    return figure


def _paired_rows(
    rows: Mapping[str, tuple[Mapping[str, Any], ...]],
    full_variant: str,
    disabled_variant: str,
    value_key: str,
) -> tuple[np.ndarray, np.ndarray]:
    """按同 session/trial/segment 精确配对，禁止位置式 zip 掩盖缺失。"""

    full = {segment_identity(row): float(row[value_key]) for row in rows.get(full_variant, ())}
    disabled = {segment_identity(row): float(row[value_key]) for row in rows.get(disabled_variant, ())}
    if set(full) != set(disabled):
        raise ValueError(
            f"论文图组件配对不完整：{full_variant}={len(full)}, {disabled_variant}={len(disabled)}"
        )
    keys = sorted(full)
    return (
        np.asarray([full[key] for key in keys], dtype=float),
        np.asarray([disabled[key] for key in keys], dtype=float),
    )


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
    axis.set_ylabel(ylabel)
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
    """绘制外推、默认 Linear/SLERP 与 Hermite 的配对 lag--residual 分布。"""

    labels = ("Smoothed KF", "Linear/SLERP", "Hermite")
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
    axis.set_xlabel("Effective lag (ms)")
    axis.set_ylabel("Lag-aligned translation RMSE (mm)")
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
    """创建可直接放入 LaTeX 子图的时序合成面板。"""

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
        coverage = np.asarray([point[0] for point in ordered], dtype=float)
        risk = np.asarray([point[1] for point in ordered], dtype=float)
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
        quantiles = np.quantile(np.asarray(values, dtype=float), (0.5, 0.25, 0.75))
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
    coverage = np.asarray([float(row["coverage"]) for row in summary], dtype=float)
    median = np.asarray([float(row["selective_risk_median_mm"]) for row in summary], dtype=float)
    q1 = np.asarray([float(row["selective_risk_q1_mm"]) for row in summary], dtype=float)
    q3 = np.asarray([float(row["selective_risk_q3_mm"]) for row in summary], dtype=float)
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


def publish_figures(results: PaperResults, output_root: Path) -> Mapping[str, Path]:
    """在活动批次发布实验一四联图与实验二四个独立面板。"""

    _configure()
    panels = output_root / "figures"
    panels.mkdir(parents=True, exist_ok=True)

    figure2a = _save_pair(
        build_dual_metric_panel(
            results.static_segments,
            "centered_p95_mm",
            "frame_increment_p95_mm",
            "mm",
        ),
        panels,
        "figure2a_static_translation",
    )
    figure2b = _save_pair(
        build_dual_metric_panel(
            results.static_segments,
            "centered_rotation_p95_deg",
            "frame_rotation_increment_p95_deg",
            "deg",
        ),
        panels,
        "figure2b_static_rotation",
    )
    figure2c = _save_pair(
        build_dual_metric_panel(
            results.translation_segments,
            "aligned_rmse_mm",
            "aligned_residual_increment_p95_mm",
            "mm",
            error_label="Lag-aligned RMSE",
        ),
        panels,
        "figure2c_dynamic_translation",
    )
    figure2d = _save_pair(
        build_dual_metric_panel(
            results.rotation_segments,
            "aligned_rmse_deg",
            "aligned_residual_increment_p95_deg",
            "deg",
            error_label="Lag-aligned RMSE",
        ),
        panels,
        "figure2d_dynamic_rotation",
    )
    capture = np.asarray([float(row["capture_p95_mm"]) for row in results.capture_alignment])
    arrival = np.asarray([float(row["arrival_p95_mm"]) for row in results.capture_alignment])
    if capture.size == 0 or capture.size != arrival.size:
        raise ValueError("论文图 capture alignment 缺少完整同候选片段")
    full_static, no_lock = _paired_rows(
        results.static_segments,
        FULL_VARIANT,
        NO_STATIC_LOCK,
        "centered_p95_mm",
    )
    temporal_points = paired_metric_matrix(
        results.translation_segments,
        TEMPORAL_STRATEGY_VARIANTS,
        ("effective_lag_ms", "aligned_rmse_mm"),
    )
    figure3a = _save_pair(
        _paired_panel(
            capture,
            arrival,
            "Candidate P95 (mm)",
            ("Capture\ntime", "Arrival\ntime"),
            endpoint_colors=(_METHOD_COLORS["Capture-Hold"], _METHOD_COLORS["Arrival-Hold"]),
        ),
        panels,
        "figure3a_capture_alignment",
        crop_to_content=False,
    )
    figure3b = _save_pair(
        _paired_panel(full_static, no_lock, "Centered P95 (mm)"),
        panels,
        "figure3b_static_lock",
        crop_to_content=False,
    )
    figure3c = _save_pair(
        build_vcd_risk_coverage_panel(results),
        panels,
        "figure3c_vcd_risk_coverage",
        crop_to_content=False,
    )
    figure3d = _save_pair(
        build_temporal_strategy_panel(temporal_points),
        panels,
        "figure3d_temporal_strategies",
        crop_to_content=False,
    )
    _remove_stale_panels(
        panels,
        (*figure2a, *figure2b, *figure2c, *figure2d, *figure3a, *figure3b, *figure3c, *figure3d),
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
    }


__all__ = [
    "build_dual_metric_panel",
    "build_temporal_strategy_panel",
    "build_vcd_risk_coverage_panel",
    "publish_figures",
    "summarize_risk_coverage",
]

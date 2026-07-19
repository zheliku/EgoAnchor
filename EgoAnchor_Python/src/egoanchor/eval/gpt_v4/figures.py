"""GPT corrected-newdata-v4 两张论文图的项目内实现。"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import fitz  # type: ignore[import-untyped]
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .metrics import (
    FULL_VARIANT,
    METHODS,
    NO_STATIC_LOCK,
    NO_TEMPORAL_SYNTHESIS,
    NO_VCD,
    GptV4Results,
)


_SHORT_LABELS = {
    "Arrival-Hold": "Arrival",
    "Capture-Hold": "Capture",
    "One-Euro Anchor": "One-Euro",
    "EgoAnchor": "EgoAnchor",
}
_MARKERS = ("s", "o", "^", "D")
_DYNAMIC_X_LIMITS = (150.0, 400.0)
_DYNAMIC_Y_LIMITS = (0.0, 21.0)
_DYNAMIC_X_TICKS = (150, 200, 250, 300, 350, 400)
_DYNAMIC_Y_TICKS = (0, 5, 10, 15, 20)


def _configure() -> None:
    """应用 GPT v4 的固定字体、线宽和导出分辨率。"""

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10.2,
            "axes.titlesize": 12.5,
            "axes.labelsize": 10.6,
            "xtick.labelsize": 9.0,
            "ytick.labelsize": 9.0,
            "legend.fontsize": 8.8,
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


def _save_pair(figure: Any, root: Path, stem: str) -> tuple[Path, Path]:
    """同时保存 PNG 与矢量 PDF。"""

    root.mkdir(parents=True, exist_ok=True)
    png = root / f"{stem}.png"
    pdf = root / f"{stem}.pdf"
    figure.savefig(png, bbox_inches="tight", pad_inches=0.06)
    figure.savefig(pdf, bbox_inches="tight", pad_inches=0.06)
    plt.close(figure)
    return png, pdf


def _combine_pdf(source_paths: Sequence[Path], destination: Path, columns: int) -> None:
    """把独立面板 PDF 无栅格化地拼接为一页。"""

    documents = [fitz.open(str(path)) for path in source_paths]
    try:
        rectangles = [document[0].rect for document in documents]
        rows = math.ceil(len(documents) / columns)
        cell_width = max(rectangle.width for rectangle in rectangles)
        cell_height = max(rectangle.height for rectangle in rectangles)
        gap = 8.0
        padding = 5.0
        output = fitz.open()
        page = output.new_page(
            width=2 * padding + columns * cell_width + (columns - 1) * gap,
            height=2 * padding + rows * cell_height + (rows - 1) * gap,
        )
        for index, (document, rectangle) in enumerate(zip(documents, rectangles, strict=True)):
            row, column = divmod(index, columns)
            left = padding + column * (cell_width + gap) + (cell_width - rectangle.width) / 2
            top = padding + row * (cell_height + gap) + (cell_height - rectangle.height) / 2
            page.show_pdf_page(
                fitz.Rect(left, top, left + rectangle.width, top + rectangle.height),
                document,
                0,
            )
        output.save(str(destination))
        output.close()
    finally:
        for document in documents:
            document.close()


def _render_pdf(pdf: Path, png: Path, dpi: int = 220) -> None:
    """把组合矢量图渲染为论文审阅用 PNG。"""

    document = fitz.open(str(pdf))
    try:
        pixmap = document[0].get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
        pixmap.save(str(png))
    finally:
        document.close()


def _values(rows: Mapping[str, tuple[Mapping[str, Any], ...]], variant: str, key: str) -> np.ndarray:
    """提取某 variant 的有限片段值，并拒绝空图。"""

    values = np.asarray([float(row[key]) for row in rows.get(variant, ())], dtype=float)
    values = values[np.isfinite(values)]
    if values.size == 0:
        raise ValueError(f"GPT v4 图缺少 {variant}/{key} 数据")
    return values


def _point_panel(
    data: Mapping[str, np.ndarray],
    title: str,
    subtitle: str,
    ylabel: str,
) -> Any:
    """绘制四系统片段散点与 median--IQR。"""

    figure, axis = plt.subplots(figsize=(4.55, 3.65))
    positions = np.arange(len(METHODS))
    for index, method in enumerate(METHODS):
        values = data[method]
        offsets = np.linspace(-0.11, 0.11, len(values))
        scatter = axis.scatter(
            positions[index] + offsets,
            values,
            s=25,
            alpha=0.46,
            marker=_MARKERS[index],
        )
        color = scatter.get_facecolor()[0]
        median = float(np.median(values))
        q1, q3 = np.quantile(values, (0.25, 0.75))
        axis.errorbar(
            positions[index],
            median,
            yerr=[[median - q1], [q3 - median]],
            fmt=_MARKERS[index],
            markersize=7.5,
            capsize=4,
            linewidth=1.8,
            color=color,
        )
    axis.set_xticks(positions, [_SHORT_LABELS[method] for method in METHODS], rotation=16, ha="right")
    axis.set_ylabel(ylabel)
    axis.set_title(title, loc="left", fontweight="bold", pad=15)
    axis.text(0, 1.01, subtitle, transform=axis.transAxes, ha="left", va="bottom", fontsize=9.1)
    axis.set_ylim(bottom=0)
    _clean_axis(axis)
    figure.tight_layout()
    return figure


def _translation_panel(results: GptV4Results) -> Any:
    """绘制实验一持续平移 lag--residual 散点与 IQR。"""

    figure, axis = plt.subplots(figsize=(4.7, 3.65))
    for index, method in enumerate(METHODS):
        rows = results.translation_segments.get(method, ())
        points = np.asarray(
            [(float(row["effective_lag_ms"]), float(row["aligned_rmse_mm"])) for row in rows],
            dtype=float,
        )
        points = points[np.isfinite(points).all(axis=1)]
        if points.size == 0:
            raise ValueError(f"GPT v4 图缺少 {method} 持续平移片段")
        scatter = axis.scatter(
            points[:, 0],
            points[:, 1],
            s=24,
            alpha=0.28,
            marker=_MARKERS[index],
            label=_SHORT_LABELS[method],
        )
        color = scatter.get_facecolor()[0]
        median_x, median_y = np.median(points, axis=0)
        q1_x, q3_x = np.quantile(points[:, 0], (0.25, 0.75))
        q1_y, q3_y = np.quantile(points[:, 1], (0.25, 0.75))
        axis.errorbar(
            median_x,
            median_y,
            xerr=[[median_x - q1_x], [q3_x - median_x]],
            yerr=[[median_y - q1_y], [q3_y - median_y]],
            fmt=_MARKERS[index],
            markersize=8,
            capsize=3.5,
            linewidth=1.7,
            color=color,
        )
    axis.set_xlabel("Effective lag (ms)")
    axis.set_ylabel("Lag-aligned translation RMSE (mm)")
    axis.set_title("(b) Dynamic translation", loc="left", fontweight="bold", pad=15)
    axis.text(0, 1.01, "Lag and residual are interpreted jointly", transform=axis.transAxes, ha="left", va="bottom", fontsize=9.1)
    axis.set_xlim(*_DYNAMIC_X_LIMITS)
    axis.set_ylim(*_DYNAMIC_Y_LIMITS)
    axis.set_xticks(_DYNAMIC_X_TICKS)
    axis.set_yticks(_DYNAMIC_Y_TICKS)
    axis.annotate("better", xy=(168, 2.2), xytext=(220, 5.4), arrowprops={"arrowstyle": "->", "linewidth": 0.9})
    _clean_axis(axis, "both")
    axis.legend(frameon=False, ncol=2, loc="upper center")
    figure.tight_layout()
    return figure


def _identity(row: Mapping[str, Any]) -> tuple[str, str, str]:
    """返回 Full/Disabled 严格连接使用的片段键。"""

    return str(row["session_id"]), str(row["trial_id"]), str(row["segment_id"])


def _paired_rows(
    rows: Mapping[str, tuple[Mapping[str, Any], ...]],
    full_variant: str,
    disabled_variant: str,
    value_key: str,
) -> tuple[np.ndarray, np.ndarray]:
    """按同 session/trial/segment 精确配对，禁止位置式 zip 掩盖缺失。"""

    full = {_identity(row): float(row[value_key]) for row in rows.get(full_variant, ())}
    disabled = {_identity(row): float(row[value_key]) for row in rows.get(disabled_variant, ())}
    if set(full) != set(disabled):
        raise ValueError(
            f"GPT v4 组件配对不完整：{full_variant}={len(full)}, {disabled_variant}={len(disabled)}"
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
    title: str,
    subtitle: str,
    ylabel: str,
    labels: tuple[str, str] = ("Enabled", "Disabled"),
    logarithmic: bool = False,
) -> None:
    """绘制 GPT v4 的逐片段配对线与中位数粗线。"""

    for full_value, disabled_value in zip(full, disabled, strict=True):
        axis.plot([0, 1], [full_value, disabled_value], marker="o", linewidth=0.9, alpha=0.40, markersize=3.5)
    axis.plot(
        [0, 1],
        [np.median(full), np.median(disabled)],
        marker="D",
        linewidth=2.35,
        markersize=6.5,
    )
    axis.set_xticks((0, 1), labels)
    axis.set_xlim(-0.20, 1.20)
    axis.set_ylabel(ylabel)
    if logarithmic:
        axis.set_yscale("log")
    else:
        axis.set_ylim(bottom=0)
    axis.set_title(title, fontweight="bold", pad=17, fontsize=10.8)
    axis.text(0.5, 1.01, subtitle, transform=axis.transAxes, ha="center", va="bottom", fontsize=7.9)
    _clean_axis(axis)


def publish_figures(results: GptV4Results, paper_root: Path) -> Mapping[str, Path]:
    """按 GPT v4 构图发布两张组合图和三个实验一独立面板。"""

    _configure()
    generated = paper_root / "figures" / "generated"
    panels = paper_root / "figures" / "panels"
    panels.mkdir(parents=True, exist_ok=True)

    world = {
        method: _values(results.static_segments, method, "centered_p95_mm")
        for method in METHODS
    }
    world_pair = _save_pair(
        _point_panel(
            world,
            "(a) Head-motion leakage",
            "Fixed registration offset removed per segment",
            "Centered translation P95 (mm)",
        ),
        panels,
        "exp1a_head_motion_leakage",
    )
    translation_pair = _save_pair(
        _translation_panel(results), panels, "exp1b_dynamic_translation"
    )
    occlusion = {
        method: _values(results.occlusion_episodes, method, "translation_p95_mm")
        for method in METHODS
    }
    occlusion_pair = _save_pair(
        _point_panel(
            occlusion,
            "(c) Failure containment",
            "Episode-level P95 during visual occlusion",
            "Occlusion translation P95 (mm)",
        ),
        panels,
        "exp1c_failure_containment",
    )
    exp1_pdf = generated / "experiment1_corrected_newdata.pdf"
    exp1_png = generated / "experiment1_corrected_newdata.png"
    generated.mkdir(parents=True, exist_ok=True)
    _combine_pdf((world_pair[1], translation_pair[1], occlusion_pair[1]), exp1_pdf, 3)
    _render_pdf(exp1_pdf, exp1_png)

    figure = plt.figure(figsize=(12.3, 3.9))
    outer = figure.add_gridspec(1, 2, width_ratios=(1.78, 1.0), wspace=0.28)
    left = outer[0].subgridspec(1, 3, wspace=0.42)
    capture = np.asarray([float(row["capture_p95_mm"]) for row in results.capture_alignment])
    arrival = np.asarray([float(row["arrival_p95_mm"]) for row in results.capture_alignment])
    if capture.size == 0 or capture.size != arrival.size:
        raise ValueError("GPT v4 capture alignment 缺少完整同候选片段")
    _paired_axis(
        figure.add_subplot(left[0, 0]),
        capture,
        arrival,
        "Capture-time alignment",
        "same raw candidates, all segments paired",
        "Candidate P95 (mm)",
        ("Capture time", "Arrival time"),
    )
    full_static, no_lock = _paired_rows(
        results.static_segments,
        FULL_VARIANT,
        NO_STATIC_LOCK,
        "centered_p95_mm",
    )
    _paired_axis(
        figure.add_subplot(left[0, 1]),
        full_static,
        no_lock,
        "StaticLock",
        "removes stationary output fluctuation",
        "Centered P95 (mm)",
    )
    full_vcd, no_vcd = _paired_rows(
        results.occlusion_episodes,
        FULL_VARIANT,
        NO_VCD,
        "translation_p95_mm",
    )
    vcd_axis = figure.add_subplot(left[0, 2])
    _paired_axis(
        vcd_axis,
        full_vcd,
        no_vcd,
        "VCD admission",
        "tail failures during occlusion",
        "Occlusion P95 (mm)",
        logarithmic=True,
    )
    vcd_axis.axhline(40.0, linestyle="--", linewidth=1)
    vcd_axis.text(0.02, 42.0, "40-mm failure threshold", fontsize=7.5, va="bottom")

    temporal_axis = figure.add_subplot(outer[0, 1])
    full_lag, no_temporal_lag = _paired_rows(
        results.translation_segments,
        FULL_VARIANT,
        NO_TEMPORAL_SYNTHESIS,
        "effective_lag_ms",
    )
    full_residual, no_temporal_residual = _paired_rows(
        results.translation_segments,
        FULL_VARIANT,
        NO_TEMPORAL_SYNTHESIS,
        "aligned_rmse_mm",
    )
    full_points = np.column_stack((full_lag, full_residual))
    disabled_points = np.column_stack((no_temporal_lag, no_temporal_residual))
    for full_point, disabled_point in zip(full_points, disabled_points, strict=True):
        temporal_axis.plot(
            (full_point[0], disabled_point[0]),
            (full_point[1], disabled_point[1]),
            linewidth=0.82,
            alpha=0.26,
        )
    temporal_axis.scatter(full_points[:, 0], full_points[:, 1], marker="D", s=27, alpha=0.42, label="Full")
    temporal_axis.scatter(disabled_points[:, 0], disabled_points[:, 1], marker="X", s=34, alpha=0.42, label="Synthesis disabled")
    full_median = np.median(full_points, axis=0)
    disabled_median = np.median(disabled_points, axis=0)
    temporal_axis.scatter(float(full_median[0]), float(full_median[1]), marker="D", s=95)
    temporal_axis.scatter(float(disabled_median[0]), float(disabled_median[1]), marker="X", s=110)
    temporal_axis.set_xlabel("Effective lag (ms)")
    temporal_axis.set_ylabel("Lag-aligned translation RMSE (mm)")
    temporal_axis.set_title("(b) Temporal synthesis trade-off", loc="left", fontweight="bold", pad=17)
    temporal_axis.text(0, 1.01, "less delay without synthesis, but larger residual", transform=temporal_axis.transAxes, ha="left", va="bottom", fontsize=8.5)
    temporal_axis.set_xlim(*_DYNAMIC_X_LIMITS)
    temporal_axis.set_ylim(*_DYNAMIC_Y_LIMITS)
    temporal_axis.set_xticks(_DYNAMIC_X_TICKS)
    temporal_axis.set_yticks(_DYNAMIC_Y_TICKS)
    temporal_axis.annotate("better", xy=(168, 2.2), xytext=(220, 5.4), arrowprops={"arrowstyle": "->", "linewidth": 0.9})
    _clean_axis(temporal_axis, "both")
    temporal_axis.legend(frameon=False, loc="upper right")
    figure.text(0.012, 0.985, "(a) Targeted component effects", ha="left", va="top", fontweight="bold", fontsize=12.5)
    figure.subplots_adjust(left=0.055, right=0.99, top=0.80, bottom=0.20)
    exp2_png, exp2_pdf = _save_pair(figure, generated, "experiment2_corrected_newdata")
    return {
        "experiment1_pdf": exp1_pdf,
        "experiment1_png": exp1_png,
        "experiment2_pdf": exp2_pdf,
        "experiment2_png": exp2_png,
    }


__all__ = ["publish_figures"]

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
_METHOD_COLORS = {
    "Arrival-Hold": "#4C78A8",
    "Capture-Hold": "#59A14F",
    "One-Euro Anchor": "#F28E2B",
    "EgoAnchor": "#E15759",
}
_PAIR_COLOR = "#7F8790"
_FULL_COLOR = _METHOD_COLORS["EgoAnchor"]
_DISABLED_COLOR = "#B07AA1"
_MARKERS = ("s", "o", "^", "D")
_DYNAMIC_X_LIMITS = (150.0, 400.0)
_DYNAMIC_X_TICKS = (150, 200, 250, 300, 350, 400)
_EXP1_DYNAMIC_Y_LIMITS = (0.0, 15.0)
_EXP1_DYNAMIC_Y_TICKS = (0, 5, 10, 15)
_EXP2_TEMPORAL_Y_LIMITS = (0.0, 15.0)
_EXP2_TEMPORAL_Y_TICKS = (0, 5, 10, 15)


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
    ylabel: str,
    paired_values: np.ndarray,
) -> Any:
    """绘制四系统片段散点与箱线分布。"""

    figure, axis = plt.subplots(figsize=(4.55, 3.65))
    positions = np.arange(len(METHODS))
    for values in paired_values:
        axis.plot(
            positions,
            values,
            color=_PAIR_COLOR,
            linewidth=0.75,
            alpha=0.24,
            zorder=1,
        )
    for index, method in enumerate(METHODS):
        values = data[method]
        offsets = np.linspace(-0.11, 0.11, len(values))
        color = _METHOD_COLORS[method]
        axis.scatter(
            positions[index] + offsets,
            values,
            s=25,
            alpha=0.26,
            marker=_MARKERS[index],
            color=color,
            zorder=2,
        )
        box = axis.boxplot(
            [values],
            positions=[positions[index]],
            widths=0.22,
            whis=(0, 100),
            showfliers=False,
            patch_artist=True,
            zorder=3,
            boxprops={"facecolor": "white", "edgecolor": color, "linewidth": 1.45},
            whiskerprops={"color": color, "linewidth": 1.45},
            capprops={"color": color, "linewidth": 1.45},
            medianprops={"color": color, "linewidth": 2.1},
        )
        for patch in box["boxes"]:
            patch.set_alpha(0.72)
        axis.plot(
            positions[index],
            float(np.median(values)),
            marker=_MARKERS[index],
            markersize=7.5,
            markerfacecolor=color,
            markeredgecolor="white",
            markeredgewidth=0.8,
            linestyle="none",
            zorder=4,
        )
    axis.set_xticks(positions, [_SHORT_LABELS[method] for method in METHODS], rotation=16, ha="right")
    axis.set_ylabel(ylabel)
    axis.set_title(title, loc="left", fontweight="bold", pad=15)
    axis.set_ylim(bottom=0)
    _clean_axis(axis)
    figure.tight_layout()
    return figure


def _paired_method_matrix(
    rows: Mapping[str, tuple[Mapping[str, Any], ...]],
    keys: Sequence[str],
) -> np.ndarray:
    """按严格事件身份组成 episode×method×metric 矩阵，禁止按数组位置连接。"""

    per_method: dict[str, dict[tuple[str, str, str], tuple[float, ...]]] = {}
    for method in METHODS:
        values: dict[tuple[str, str, str], tuple[float, ...]] = {}
        for row in rows.get(method, ()):
            identity = _identity(row)
            if identity in values:
                raise ValueError(f"GPT v4 方法片段键重复：{method}/{identity}")
            metrics = tuple(float(row[key]) for key in keys)
            if all(np.isfinite(metrics)):
                values[identity] = metrics
        per_method[method] = values
    expected = set(per_method[METHODS[0]])
    if not expected or any(set(per_method[method]) != expected for method in METHODS[1:]):
        counts = ", ".join(f"{method}={len(per_method[method])}" for method in METHODS)
        raise ValueError(f"GPT v4 实验一方法配对不完整：{counts}")
    return np.asarray(
        [[per_method[method][identity] for method in METHODS] for identity in sorted(expected)],
        dtype=float,
    )


def _translation_panel(results: GptV4Results) -> Any:
    """绘制实验一持续平移 lag--residual 散点与 IQR。"""

    figure, axis = plt.subplots(figsize=(4.7, 3.65))
    paired = _paired_method_matrix(
        results.translation_segments,
        ("effective_lag_ms", "aligned_rmse_mm"),
    )
    for episode in paired:
        axis.plot(
            episode[:, 0],
            episode[:, 1],
            color=_PAIR_COLOR,
            linewidth=0.75,
            alpha=0.24,
            zorder=1,
        )
    for index, method in enumerate(METHODS):
        points = paired[:, index, :]
        color = _METHOD_COLORS[method]
        axis.scatter(
            points[:, 0],
            points[:, 1],
            s=24,
            alpha=0.28,
            marker=_MARKERS[index],
            color=color,
            label=_SHORT_LABELS[method],
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
            fmt=_MARKERS[index],
            markersize=8,
            capsize=3.5,
            linewidth=1.7,
            color=color,
            alpha=1.0,
        )
    axis.set_xlabel("Effective lag (ms)")
    axis.set_ylabel("Lag-aligned translation RMSE (mm)")
    axis.set_title("(b) Dynamic translation", loc="left", fontweight="bold", pad=15)
    axis.set_xlim(
        min(_DYNAMIC_X_LIMITS[0], float(np.min(paired[:, :, 0])) * 0.96),
        max(_DYNAMIC_X_LIMITS[1], float(np.max(paired[:, :, 0])) * 1.04),
    )
    axis.set_ylim(_EXP1_DYNAMIC_Y_LIMITS[0], max(_EXP1_DYNAMIC_Y_LIMITS[1], float(np.max(paired[:, :, 1])) * 1.08))
    axis.annotate("better", xy=(168, 2.2), xytext=(220, 5.4), arrowprops={"arrowstyle": "->", "linewidth": 0.9})
    _clean_axis(axis, "both")
    axis.legend(
        frameon=False,
        ncol=4,
        loc="lower right",
        bbox_to_anchor=(1.0, 1.0),
        borderaxespad=0.0,
        handletextpad=0.9,
        columnspacing=1.9,
    )
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
    ylabel: str,
    labels: tuple[str, str] = ("Enabled", "Disabled"),
    logarithmic: bool = False,
    endpoint_colors: tuple[str, str] = (_FULL_COLOR, _DISABLED_COLOR),
) -> None:
    """绘制 GPT v4 的逐片段配对线与中位数粗线。"""

    for full_value, disabled_value in zip(full, disabled, strict=True):
        axis.plot(
            [0, 1],
            [full_value, disabled_value],
            color=_PAIR_COLOR,
            linewidth=0.8,
            alpha=0.35,
            zorder=1,
        )
    axis.scatter(np.zeros_like(full), full, color=endpoint_colors[0], s=18, alpha=0.38, zorder=2)
    axis.scatter(np.ones_like(disabled), disabled, color=endpoint_colors[1], s=18, alpha=0.38, zorder=2)
    axis.plot(
        [0, 1],
        [np.median(full), np.median(disabled)],
        color=_PAIR_COLOR,
        linewidth=2.35,
        zorder=3,
    )
    axis.scatter(0, np.median(full), marker="D", color=endpoint_colors[0], s=72, zorder=4)
    axis.scatter(1, np.median(disabled), marker="D", color=endpoint_colors[1], s=72, zorder=4)
    axis.set_xticks((0, 1), labels)
    axis.set_xlim(-0.20, 1.20)
    axis.set_ylabel(ylabel)
    if logarithmic:
        axis.set_yscale("log")
    else:
        axis.set_ylim(bottom=0)
    axis.set_title(title, fontweight="bold", pad=17, fontsize=10.8)
    _clean_axis(axis)


def _paired_panel(
    full: np.ndarray,
    disabled: np.ndarray,
    title: str,
    ylabel: str,
    labels: tuple[str, str] = ("Enabled", "Disabled"),
    logarithmic: bool = False,
    endpoint_colors: tuple[str, str] = (_FULL_COLOR, _DISABLED_COLOR),
) -> Any:
    """创建可直接放入 LaTeX 子图的单个配对面板。"""

    figure, axis = plt.subplots(figsize=(3.3, 3.25))
    _paired_axis(axis, full, disabled, title, ylabel, labels, logarithmic, endpoint_colors)
    figure.tight_layout()
    return figure


def _plot_temporal_axis(axis: Any, full_points: np.ndarray, disabled_points: np.ndarray) -> None:
    """绘制时序合成 lag--residual 面板，保留全部严格配对 episode。"""

    for full_point, disabled_point in zip(full_points, disabled_points, strict=True):
        axis.plot(
            (full_point[0], disabled_point[0]),
            (full_point[1], disabled_point[1]),
            color=_PAIR_COLOR,
            linewidth=0.82,
            alpha=0.26,
        )
    axis.scatter(
        full_points[:, 0],
        full_points[:, 1],
        marker="D",
        color=_FULL_COLOR,
        s=27,
        alpha=0.42,
        label="Full",
    )
    axis.scatter(
        disabled_points[:, 0],
        disabled_points[:, 1],
        marker="X",
        color=_DISABLED_COLOR,
        s=34,
        alpha=0.42,
        label="Synthesis disabled",
    )
    full_median = np.median(full_points, axis=0)
    disabled_median = np.median(disabled_points, axis=0)
    axis.scatter(float(full_median[0]), float(full_median[1]), marker="D", color=_FULL_COLOR, s=95)
    axis.scatter(float(disabled_median[0]), float(disabled_median[1]), marker="X", color=_DISABLED_COLOR, s=110)
    axis.set_xlabel("Effective lag (ms)")
    axis.set_ylabel("Lag-aligned translation RMSE (mm)")
    axis.set_title("(d) Temporal synthesis trade-off", loc="left", fontweight="bold", pad=17)
    all_points = np.vstack((full_points, disabled_points))
    axis.set_xlim(
        min(_DYNAMIC_X_LIMITS[0], float(np.min(all_points[:, 0])) * 0.96),
        max(_DYNAMIC_X_LIMITS[1], float(np.max(all_points[:, 0])) * 1.04),
    )
    axis.set_ylim(_EXP2_TEMPORAL_Y_LIMITS[0], max(_EXP2_TEMPORAL_Y_LIMITS[1], float(np.max(all_points[:, 1])) * 1.08))
    axis.annotate("better", xy=(168, 2.2), xytext=(220, 5.4), arrowprops={"arrowstyle": "->", "linewidth": 0.9})
    _clean_axis(axis, "both")
    axis.legend(
        frameon=False,
        ncol=2,
        loc="lower right",
        bbox_to_anchor=(1.0, 1.0),
        borderaxespad=0.0,
        handletextpad=1.0,
        columnspacing=1.9,
    )


def _temporal_panel(full_points: np.ndarray, disabled_points: np.ndarray) -> Any:
    """创建可直接放入 LaTeX 子图的时序合成面板。"""

    figure, axis = plt.subplots(figsize=(4.7, 3.65))
    _plot_temporal_axis(axis, full_points, disabled_points)
    figure.tight_layout()
    return figure


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
    world_paired = _paired_method_matrix(results.static_segments, ("centered_p95_mm",))[:, :, 0]
    world_pair = _save_pair(
        _point_panel(
            world,
            "(a) Head-motion leakage",
            "Centered translation P95 (mm)",
            world_paired,
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
    occlusion_paired = _paired_method_matrix(results.occlusion_episodes, ("translation_p95_mm",))[:, :, 0]
    occlusion_pair = _save_pair(
        _point_panel(
            occlusion,
            "(c) Failure containment",
            "Occlusion translation P95 (mm)",
            occlusion_paired,
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
        "Candidate P95 (mm)",
        ("Capture time", "Arrival time"),
        endpoint_colors=(_METHOD_COLORS["Capture-Hold"], _METHOD_COLORS["Arrival-Hold"]),
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
        "Occlusion P95 (mm)",
        logarithmic=True,
    )
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
    temporal_axis = figure.add_subplot(outer[0, 1])
    _plot_temporal_axis(temporal_axis, full_points, disabled_points)
    figure.text(0.012, 0.985, "(a) Targeted component effects", ha="left", va="top", fontweight="bold", fontsize=12.5)
    figure.subplots_adjust(left=0.055, right=0.99, top=0.80, bottom=0.20)
    exp2_png, exp2_pdf = _save_pair(figure, generated, "experiment2_corrected_newdata")
    exp2a_pair = _save_pair(
        _paired_panel(
            capture,
            arrival,
            "(a) Capture-time alignment",
            "Candidate P95 (mm)",
            ("Capture time", "Arrival time"),
            endpoint_colors=(_METHOD_COLORS["Capture-Hold"], _METHOD_COLORS["Arrival-Hold"]),
        ),
        panels,
        "exp2a_capture_alignment",
    )
    exp2b_pair = _save_pair(
        _paired_panel(full_static, no_lock, "(b) StaticLock", "Centered P95 (mm)"),
        panels,
        "exp2b_staticlock",
    )
    exp2c_pair = _save_pair(
        _paired_panel(
            full_vcd,
            no_vcd,
            "(c) VCD admission",
            "Occlusion P95 (mm)",
            logarithmic=True,
        ),
        panels,
        "exp2c_vcd_admission",
    )
    exp2d_pair = _save_pair(
        _temporal_panel(full_points, disabled_points),
        panels,
        "exp2d_temporal_synthesis",
    )
    return {
        "experiment1_pdf": exp1_pdf,
        "experiment1_png": exp1_png,
        "experiment2_pdf": exp2_pdf,
        "experiment2_png": exp2_png,
        "experiment2a_pdf": exp2a_pair[1],
        "experiment2a_png": exp2a_pair[0],
        "experiment2b_pdf": exp2b_pair[1],
        "experiment2b_png": exp2b_pair[0],
        "experiment2c_pdf": exp2c_pair[1],
        "experiment2c_png": exp2c_pair[0],
        "experiment2d_pdf": exp2d_pair[1],
        "experiment2d_png": exp2d_pair[0],
    }


__all__ = ["publish_figures"]

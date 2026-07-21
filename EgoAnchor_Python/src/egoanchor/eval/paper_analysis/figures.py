"""实验一/二论文图的项目内实现。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .metrics import (
    FULL_VARIANT,
    HERMITE_VARIANT,
    METHODS,
    NO_STATIC_LOCK,
    NO_TEMPORAL_SYNTHESIS,
    NO_VCD,
    PaperResults,
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
    "Arrival-Hold": "#4C78A8",
    "Capture-Hold": "#59A14F",
    "One-Euro Anchor": "#F28E2B",
    FULL_VARIANT: "#E15759",
}
_PAIR_COLOR = "#7F8790"
_FULL_COLOR = _METHOD_COLORS[FULL_VARIANT]
_DISABLED_COLOR = "#B07AA1"
_HERMITE_COLOR = "#2A9D8F"
_MARKERS = ("s", "o", "^", "D")
_DYNAMIC_X_LIMITS = (150.0, 400.0)
_EXP1_DYNAMIC_Y_LIMITS = (0.0, 15.0)
_EXP2_TEMPORAL_Y_LIMITS = (0.0, 15.0)


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


def _save_pair(figure: Any, root: Path, stem: str) -> tuple[Path, Path]:
    """同时保存 PNG 与矢量 PDF。"""

    root.mkdir(parents=True, exist_ok=True)
    png = root / f"{stem}.png"
    pdf = root / f"{stem}.pdf"
    figure.savefig(png, bbox_inches="tight", pad_inches=0.06)
    figure.savefig(pdf, bbox_inches="tight", pad_inches=0.06)
    plt.close(figure)
    return png, pdf


def _values(rows: Mapping[str, tuple[Mapping[str, Any], ...]], variant: str, key: str) -> np.ndarray:
    """提取某 variant 的有限片段值，并拒绝空图。"""

    values = np.asarray([float(row[key]) for row in rows.get(variant, ())], dtype=float)
    values = values[np.isfinite(values)]
    if values.size == 0:
        raise ValueError(f"论文图缺少 {variant}/{key} 数据")
    return values


def build_point_panel(
    data: Mapping[str, np.ndarray],
    ylabel: str,
    paired_values: np.ndarray,
) -> Any:
    """绘制四系统片段散点与箱线分布。"""

    figure, axis = plt.subplots(figsize=(2.28, 2.18))
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
            label=_SHORT_LABELS[method],
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
    axis.set_ylim(bottom=0)
    _clean_axis(axis)
    axis.legend(
        frameon=False,
        ncol=2,
        loc="lower right",
        bbox_to_anchor=(1.0, 1.0),
        borderaxespad=0.0,
        handletextpad=0.5,
        columnspacing=1.1,
    )
    figure.tight_layout()
    return figure


def build_translation_panel(results: PaperResults) -> Any:
    """绘制实验一持续平移 lag--residual 散点与 IQR。"""

    figure, axis = plt.subplots(figsize=(2.28, 2.18))
    paired = paired_metric_matrix(
        results.translation_segments,
        METHODS,
        ("effective_lag_ms", "aligned_rmse_mm"),
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
    axis.set_xlim(
        min(_DYNAMIC_X_LIMITS[0], float(np.min(paired[:, :, 0])) * 0.96),
        max(_DYNAMIC_X_LIMITS[1], float(np.max(paired[:, :, 0])) * 1.04),
    )
    axis.set_ylim(_EXP1_DYNAMIC_Y_LIMITS[0], max(_EXP1_DYNAMIC_Y_LIMITS[1], float(np.max(paired[:, :, 1])) * 1.08))
    axis.annotate("better", xy=(168, 2.2), xytext=(220, 5.4), arrowprops={"arrowstyle": "->", "linewidth": 0.9})
    _clean_axis(axis, "both")
    axis.legend(
        frameon=False,
        ncol=2,
        loc="lower right",
        bbox_to_anchor=(1.0, 1.0),
        borderaxespad=0.0,
        handletextpad=0.5,
        columnspacing=1.1,
    )
    figure.tight_layout()
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
    labels: tuple[str, str] = ("Enabled", "Disabled"),
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
    _clean_axis(axis)


def _paired_panel(
    full: np.ndarray,
    disabled: np.ndarray,
    ylabel: str,
    labels: tuple[str, str] = ("Enabled", "Disabled"),
    logarithmic: bool = False,
    endpoint_colors: tuple[str, str] = (_FULL_COLOR, _DISABLED_COLOR),
) -> Any:
    """创建可直接放入 LaTeX 子图的单个配对面板。"""

    # LaTeX 以 0.18\textwidth 放置前三个图三面板；原生宽度与目标宽度一致可避免字体缩小。
    figure, axis = plt.subplots(figsize=(1.26, 2.18))
    _paired_axis(axis, full, disabled, ylabel, labels, logarithmic, endpoint_colors)
    figure.tight_layout()
    return figure


def _plot_temporal_axis(axis: Any, paired_points: np.ndarray) -> None:
    """绘制三个真实运行时时序策略的 lag--residual 分布。"""

    labels = ("Predict-to-Now", "Hermite", "Linear/SLERP")
    colors = (_DISABLED_COLOR, _HERMITE_COLOR, _FULL_COLOR)
    markers = ("X", "D", "o")
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
            marker=marker,
            color=color,
            s=27,
            alpha=0.38,
            label=label,
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
            markersize=8,
            capsize=3.5,
            linewidth=1.7,
            color=color,
        )
    axis.set_xlabel("Effective lag (ms)")
    axis.set_ylabel("Lag-aligned translation RMSE (mm)")
    all_points = paired_points.reshape(-1, paired_points.shape[-1])
    axis.set_xlim(
        min(_DYNAMIC_X_LIMITS[0], float(np.min(all_points[:, 0])) * 0.96),
        max(_DYNAMIC_X_LIMITS[1], float(np.max(all_points[:, 0])) * 1.04),
    )
    axis.set_ylim(_EXP2_TEMPORAL_Y_LIMITS[0], max(_EXP2_TEMPORAL_Y_LIMITS[1], float(np.max(all_points[:, 1])) * 1.08))
    axis.annotate("better", xy=(168, 2.2), xytext=(220, 5.4), arrowprops={"arrowstyle": "->", "linewidth": 0.9})
    _clean_axis(axis, "both")
    axis.legend(
        frameon=False,
        ncol=1,
        loc="upper right",
        borderaxespad=0.3,
        handletextpad=0.4,
    )


def _temporal_panel(paired_points: np.ndarray) -> Any:
    """创建可直接放入 LaTeX 子图的时序合成面板。"""

    figure, axis = plt.subplots(figsize=(2.9, 2.18))
    _plot_temporal_axis(axis, paired_points)
    figure.tight_layout()
    return figure


def publish_figures(results: PaperResults, paper_root: Path) -> Mapping[str, Path]:
    """发布由 LaTeX 排列的图二和图三独立面板。"""

    _configure()
    panels = paper_root / "figures" / "panels"
    panels.mkdir(parents=True, exist_ok=True)

    world = {
        method: _values(results.static_segments, method, "centered_p95_mm")
        for method in METHODS
    }
    world_paired = paired_metric_matrix(
        results.static_segments,
        METHODS,
        ("centered_p95_mm",),
    )[:, :, 0]
    figure2a = _save_pair(
        build_point_panel(
            world,
            "Centered translation P95 (mm)",
            world_paired,
        ),
        panels,
        "figure2a_head_motion",
    )
    figure2b = _save_pair(
        build_translation_panel(results), panels, "figure2b_translation"
    )
    occlusion = {
        method: _values(results.occlusion_episodes, method, "translation_p95_mm")
        for method in METHODS
    }
    occlusion_paired = paired_metric_matrix(
        results.occlusion_episodes,
        METHODS,
        ("translation_p95_mm",),
    )[:, :, 0]
    figure2c = _save_pair(
        build_point_panel(
            occlusion,
            "Occlusion translation P95 (mm)",
            occlusion_paired,
        ),
        panels,
        "figure2c_occlusion",
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
    full_vcd, no_vcd = _paired_rows(
        results.occlusion_episodes,
        FULL_VARIANT,
        NO_VCD,
        "translation_p95_mm",
    )
    temporal_points = paired_metric_matrix(
        results.translation_segments,
        (NO_TEMPORAL_SYNTHESIS, HERMITE_VARIANT, FULL_VARIANT),
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
    )
    figure3b = _save_pair(
        _paired_panel(full_static, no_lock, "Centered P95 (mm)"),
        panels,
        "figure3b_static_lock",
    )
    figure3c = _save_pair(
        _paired_panel(
            full_vcd,
            no_vcd,
            "Occlusion P95 (mm)",
            logarithmic=True,
        ),
        panels,
        "figure3c_vcd",
    )
    figure3d = _save_pair(
        _temporal_panel(temporal_points),
        panels,
        "figure3d_temporal_strategies",
    )
    return {
        "figure2a_pdf": figure2a[1],
        "figure2a_png": figure2a[0],
        "figure2b_pdf": figure2b[1],
        "figure2b_png": figure2b[0],
        "figure2c_pdf": figure2c[1],
        "figure2c_png": figure2c[0],
        "figure3a_pdf": figure3a[1],
        "figure3a_png": figure3a[0],
        "figure3b_pdf": figure3b[1],
        "figure3b_png": figure3b[0],
        "figure3c_pdf": figure3c[1],
        "figure3c_png": figure3c[0],
        "figure3d_pdf": figure3d[1],
        "figure3d_png": figure3d[0],
    }


__all__ = ["build_point_panel", "build_translation_panel", "publish_figures"]

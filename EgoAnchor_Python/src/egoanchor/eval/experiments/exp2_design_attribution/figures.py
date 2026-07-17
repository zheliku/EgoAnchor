"""实验二的 IEEE VR 论文 PDF 图表生成器。

两张核心图共享 ``egoanchor.eval.figure_style``：
- ``exp2_component_delta``：组件×指标的归因热力图，颜色为“消融−完整”配对差，
  正值(变差)暖色、负值(更好)冷色，替代信息量单薄的单指标条形图；
- ``exp2_vcd_risk_coverage``：把候选按 VCD 分数降序诱导的 risk--coverage 曲线，
  对比随机接纳基线并阴影 AURC，修正旧图直接铺逐候选噪声的问题。

另有三张单组件效应图（alignment/synthesis/StaticLock）作为附属证据，使用一致的
配对差条形＋数值标注。全部只消费分析层公开表，不重算配对或 AURC。
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

from egoanchor.eval import figure_style as fs

from .contract import ABLATION_VARIANTS, BASELINE_VARIANT


# 组件消融 → 热力图行标签（读者可读）。
_COMPONENT_LABEL = {
    "EgoAnchor w/o capture-time alignment": "w/o Capture-time\nalignment",
    "EgoAnchor w/o VCD": "w/o VCD\nadmission",
    "EgoAnchor w/o temporal synthesis": "w/o Temporal\nsynthesis",
    "EgoAnchor w/o StaticLock": "w/o StaticLock",
}

# 热力图列：跨场景、可比、覆盖误差中心/尾部/抖动/连续性的中性指标。
_HEATMAP_METRICS = (
    ("display_error.translation_error_mm_median", "Trans median\n(mm)"),
    ("display_error.translation_error_mm_p95", "Trans P95\n(mm)"),
    ("static.position_hp_rms_mm", "Static jitter\n(mm)"),
    ("occlusion.display_jump_p95_mm", "Occl. jump P95\n(mm)"),
    ("transition.visible_response_time_ms", "Visible resp.\n(ms)"),
)


def write_exp2_figures(
    summary: pd.DataFrame,
    risk: pd.DataFrame,
    output_dir: Path | str,
) -> None:
    """按固定文件名生成组件热力图、三张单组件效应图与 risk-coverage 图。"""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    _write_component_heatmap(summary, output / "exp2_component_delta.pdf")
    _write_single_effect(
        summary,
        output / "exp2_alignment_effect.pdf",
        ablation=ABLATION_VARIANTS[0],
        metrics=(
            ("display_error.translation_error_mm_median", "Trans median (mm)"),
            ("display_error.translation_error_mm_p95", "Trans P95 (mm)"),
        ),
        title="Capture-time alignment",
    )
    _write_single_effect(
        summary,
        output / "exp2_temporal_synthesis_effect.pdf",
        ablation=ABLATION_VARIANTS[2],
        metrics=(
            ("transition.visible_response_time_ms", "Visible resp. (ms)"),
            ("transition.peak_translation_error_mm", "Peak trans. (mm)"),
        ),
        title="Temporal synthesis",
    )
    _write_single_effect(
        summary,
        output / "exp2_static_lock_tradeoff.pdf",
        ablation=ABLATION_VARIANTS[3],
        metrics=(
            ("static.position_hp_rms_mm", "Static jitter (mm)"),
            ("transition.visible_response_time_ms", "Visible resp. (ms)"),
        ),
        title="StaticLock trade-off",
    )
    _write_risk_coverage(risk, output / "exp2_vcd_risk_coverage.pdf")


# ---------------------------------------------------------------------------
# 组件归因热力图。
# ---------------------------------------------------------------------------


def _write_component_heatmap(summary: pd.DataFrame, path: Path) -> Path:
    """绘制组件×指标的配对差热力图，颜色编码优劣、单元格标注数值。"""

    fs.apply_paper_style()
    import matplotlib.pyplot as plt

    components = list(ABLATION_VARIANTS)
    metrics = _HEATMAP_METRICS
    matrix = np.full((len(components), len(metrics)), np.nan)
    for row, component in enumerate(components):
        for column, (metric, _) in enumerate(metrics):
            matrix[row, column] = _delta(summary, component, metric)

    # 每列独立归一化，避免 ms 量级压过 mm 量级。
    column_scale = np.nanmax(np.abs(matrix), axis=0)
    column_scale[~np.isfinite(column_scale) | (column_scale <= 0)] = 1.0

    figure, axes = plt.subplots(
        figsize=(fs.COLUMN_WIDTH_IN * 1.55, 0.62 * len(components) + 1.15)
    )
    for row in range(len(components)):
        for column in range(len(metrics)):
            value = matrix[row, column]
            color = fs.diverging_color(value, column_scale[column])
            axes.add_patch(
                plt.Rectangle(
                    (column, row),
                    1.0,
                    1.0,
                    facecolor=color,
                    edgecolor="white",
                    linewidth=1.4,
                )
            )
            text = "--" if not np.isfinite(value) else (f"{value:+.2f}" if abs(value) < 100 else f"{value:+.0f}")
            axes.text(
                column + 0.5,
                row + 0.5,
                text,
                ha="center",
                va="center",
                fontsize=7.0,
                color=fs.readable_text_color(color),
            )
    axes.set_xlim(0, len(metrics))
    axes.set_ylim(0, len(components))
    axes.invert_yaxis()
    axes.set_xticks(np.arange(len(metrics)) + 0.5)
    axes.set_xticklabels([label for _, label in metrics], fontsize=6.8)
    axes.set_yticks(np.arange(len(components)) + 0.5)
    axes.set_yticklabels([_COMPONENT_LABEL.get(name, name) for name in components], fontsize=6.8)
    axes.tick_params(length=0)
    for spine in axes.spines.values():
        spine.set_visible(False)
    axes.set_title("Component attribution: ablation − full EgoAnchor", fontsize=8.0, pad=8.0)
    # 颜色语义脚注：暖=消融更差(组件有益)，冷=消融更好。
    axes.annotate(
        "warmer = ablation worse (component helps)   ·   cooler = ablation better",
        xy=(0.5, -0.02),
        xycoords="axes fraction",
        ha="center",
        va="top",
        fontsize=6.0,
        color="#555555",
    )
    figure.tight_layout()
    return fs.save_figure(figure, path)


# ---------------------------------------------------------------------------
# 单组件效应条形图（两指标并列）。
# ---------------------------------------------------------------------------


def _write_single_effect(
    summary: pd.DataFrame,
    path: Path,
    *,
    ablation: str,
    metrics: Sequence[tuple[str, str]],
    title: str,
) -> Path:
    """绘制单个组件在两项关键指标上的配对差，正=变差。"""

    fs.apply_paper_style()
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(figsize=(fs.COLUMN_WIDTH_IN, fs.COLUMN_WIDTH_IN * 0.72))
    fs.style_axes(axes)
    color = fs.ablation_color(ablation)
    values = [_delta(summary, ablation, metric) for metric, _ in metrics]
    positions = np.arange(len(metrics))
    for index, value in enumerate(values):
        axes.bar(
            index,
            0.0 if not np.isfinite(value) else value,
            width=0.6,
            color=color,
            zorder=3,
        )
    axes.axhline(0.0, color="#333333", linewidth=0.8, zorder=2)
    for index, value in enumerate(values):
        if not np.isfinite(value):
            continue
        axes.annotate(
            f"{value:+.2f}" if abs(value) < 100 else f"{value:+.0f}",
            xy=(index, value),
            xytext=(0.0, 3.0 if value >= 0 else -9.0),
            textcoords="offset points",
            ha="center",
            fontsize=6.6,
            color="#333333",
        )
    axes.set_xticks(positions)
    axes.set_xticklabels([label for _, label in metrics], fontsize=6.8)
    axes.set_ylabel("Ablation − full", fontsize=7.0)
    axes.set_title(title, fontsize=8.0)
    if not any(np.isfinite(value) for value in values):
        axes.text(0.5, 0.5, "No paired deltas", transform=axes.transAxes, ha="center", va="center")
    figure.tight_layout()
    return fs.save_figure(figure, path)


# ---------------------------------------------------------------------------
# VCD risk-coverage 曲线。
# ---------------------------------------------------------------------------


def _write_risk_coverage(risk: pd.DataFrame, path: Path) -> Path:
    """把 VCD 分数诱导的 risk-coverage 聚合为一条稳定中位曲线并对比随机基线。

    对每个 trial/event 单元的曲线在公共 coverage 网格上插值后取中位，避免旧图
    直接叠加逐候选阶梯造成的锯齿。随机接纳基线为“全体接纳平均风险”水平线，
    曲线低于该线即表明 VCD 分数具有风险判别性；两者之间的面积近似 AURC 收益。
    """

    fs.apply_paper_style()
    import matplotlib.pyplot as plt

    figure, axes = fs.new_figure(fs.COLUMN_WIDTH_IN * 1.35, fs.COLUMN_WIDTH_IN * 0.9)
    required = {"coverage", "selective_risk_mm"}
    grid = np.linspace(0.05, 1.0, 40)
    color = fs.variant_color("EgoAnchor")

    if not risk.empty and required.issubset(risk.columns):
        view = risk.copy()
        view["coverage"] = pd.to_numeric(view["coverage"], errors="coerce")
        view["selective_risk_mm"] = pd.to_numeric(view["selective_risk_mm"], errors="coerce")
        view = view.dropna(subset=["coverage", "selective_risk_mm"])
        group_columns = [
            column
            for column in ("session_id", "scenario_id", "trial_id", "event_id", "condition_id")
            if column in view.columns
        ]
        interpolated: list[np.ndarray] = []
        groups = view.groupby(group_columns, dropna=False, sort=True) if group_columns else [((), view)]
        for _, group in groups:
            ordered = group.sort_values("coverage", kind="stable")
            coverage = ordered["coverage"].to_numpy(dtype=float)
            risk_values = ordered["selective_risk_mm"].to_numpy(dtype=float)
            if coverage.size < 2:
                continue
            interpolated.append(np.interp(grid, coverage, risk_values, left=risk_values[0], right=risk_values[-1]))
            axes.plot(coverage, risk_values, color=color, alpha=0.14, linewidth=0.6, zorder=2)
        if interpolated:
            stacked = np.vstack(interpolated)
            median_curve = np.median(stacked, axis=0)
            baseline = float(median_curve[-1])  # coverage=1.0 即全体接纳（随机顺序）平均风险。
            axes.fill_between(
                grid,
                median_curve,
                baseline,
                where=median_curve <= baseline,
                color=color,
                alpha=0.16,
                zorder=1,
                label="AURC gain",
            )
            axes.plot(grid, median_curve, color=color, linewidth=2.0, zorder=5, label="VCD-ranked")
            axes.axhline(
                baseline,
                color="#555555",
                linestyle=(0, (4, 2)),
                linewidth=1.0,
                zorder=4,
                label="Random admission",
            )
            axes.legend(loc="upper right", fontsize=6.6)
    else:
        axes.text(0.5, 0.5, "No usable risk-coverage rows", transform=axes.transAxes, ha="center", va="center")

    axes.set_xlabel("Coverage (fraction of candidates accepted)")
    axes.set_ylabel("Selective risk: translation error (mm)")
    axes.set_title("VCD risk–coverage (full EgoAnchor)", fontsize=8.0)
    axes.set_xlim(0.0, 1.0)
    axes.set_ylim(bottom=0.0)
    return fs.save_figure(figure, path)


def _delta(summary: pd.DataFrame, variant: str, metric: str) -> float:
    """读取一个消融在指定 metric 上的跨 session 中位配对差；缺失返回 NaN。"""

    required = {"variant_label", "metric", "delta_median"}
    if summary.empty or not required.issubset(summary.columns):
        return float("nan")
    selected = pd.to_numeric(
        summary.loc[
            summary["variant_label"].astype(str).eq(variant)
            & summary["metric"].astype(str).eq(metric),
            "delta_median",
        ],
        errors="coerce",
    ).dropna()
    return float(selected.median()) if not selected.empty else float("nan")


__all__ = ["write_exp2_figures"]

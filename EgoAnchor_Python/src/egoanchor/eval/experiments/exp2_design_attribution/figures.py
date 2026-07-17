"""实验二的论文 PDF 图表生成器。"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import matplotlib
import numpy as np
import pandas as pd

from .contract import ABLATION_VARIANTS, BASELINE_VARIANT, REQUIRED_VARIANTS

matplotlib.use("Agg")
import matplotlib.pyplot as plt


# 颜色和系统语义一一绑定，禁止因差值大小或输入行顺序改变配色。
_VARIANT_COLORS = dict(
    zip(
        REQUIRED_VARIANTS,
        ("#4C78A8", "#F58518", "#54A24B", "#E45756", "#72B7B2"),
        strict=True,
    )
)

_SHORT_LABELS = {
    BASELINE_VARIANT: "Full",
    ABLATION_VARIANTS[0]: "No alignment",
    ABLATION_VARIANTS[1]: "No VCD",
    ABLATION_VARIANTS[2]: "No synthesis",
    ABLATION_VARIANTS[3]: "No StaticLock",
}

_DISPLAY_METRIC = "display_error.translation_error_mm_median"
_TRANSITION_METRIC = "transition.visible_response_time_ms"
_STATIC_METRIC = "static.position_hp_rms_mm"


def _choose_metric(
    summary: pd.DataFrame,
    variants: Sequence[str],
    preferred: str,
    prefix: str,
) -> str | None:
    """从公开 summary 契约选择首选指标，或同语义命名空间中的稳定备选。"""

    required = {"variant_label", "metric"}
    if summary.empty or not required.issubset(summary.columns):
        return None
    rows = summary.loc[summary["variant_label"].astype(str).isin(variants)]
    metrics = set(rows["metric"].dropna().astype(str))
    if preferred in metrics:
        return preferred
    alternatives = sorted(metric for metric in metrics if metric.startswith(prefix))
    return alternatives[0] if alternatives else None


def _delta(summary: pd.DataFrame, variant: str, metric: str | None) -> float:
    """读取某消融的跨 session 中位差；完整系统固定为零基线。"""

    if variant == BASELINE_VARIANT:
        return 0.0
    required = {"variant_label", "metric", "delta_median"}
    if metric is None or summary.empty or not required.issubset(summary.columns):
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


def _draw_delta(
    axes: plt.Axes,
    summary: pd.DataFrame,
    variants: Sequence[str],
    *,
    preferred_metric: str,
    metric_prefix: str,
    title: str,
    ylabel: str,
) -> None:
    """按冻结系统顺序绘制完整系统与指定消融的配对差。"""

    metric = _choose_metric(summary, variants[1:], preferred_metric, metric_prefix)
    values = [_delta(summary, variant, metric) for variant in variants]
    for index, (variant, value) in enumerate(zip(variants, values, strict=True)):
        axes.bar(
            index,
            value,
            color=_VARIANT_COLORS[variant],
            label=variant,
            width=0.72,
        )

    axes.set_xticks(range(len(variants)), [_SHORT_LABELS[variant] for variant in variants])
    axes.set_ylabel(ylabel)
    axes.set_title(title)
    axes.axhline(0.0, color="#333333", linewidth=0.8)
    axes.grid(axis="y", alpha=0.25, linewidth=0.6)
    if not np.isfinite(values[1:]).any():
        axes.text(
            0.5,
            0.5,
            "No usable paired deltas",
            transform=axes.transAxes,
            ha="center",
            va="center",
        )


def _write_delta_figure(
    summary: pd.DataFrame,
    output: Path,
    variants: Sequence[str],
    *,
    preferred_metric: str,
    metric_prefix: str,
    title: str,
    ylabel: str,
) -> None:
    """创建并保存一张组件差值 PDF。"""

    figure, axes = plt.subplots(figsize=(7.8, 4.2), constrained_layout=True)
    _draw_delta(
        axes,
        summary,
        variants,
        preferred_metric=preferred_metric,
        metric_prefix=metric_prefix,
        title=title,
        ylabel=ylabel,
    )
    figure.savefig(output, format="pdf")
    plt.close(figure)


def _write_risk_coverage(risk: pd.DataFrame, output: Path) -> None:
    """绘制 VCD 连续分数诱导的 risk-coverage 诊断曲线。"""

    figure, axes = plt.subplots(figsize=(6.2, 4.2), constrained_layout=True)
    required = {"coverage", "selective_risk_mm"}
    if not risk.empty and required.issubset(risk.columns):
        view = risk.copy()
        view["coverage"] = pd.to_numeric(view["coverage"], errors="coerce")
        view["selective_risk_mm"] = pd.to_numeric(
            view["selective_risk_mm"], errors="coerce"
        )
        view = view.dropna(subset=["coverage", "selective_risk_mm"])
        group_columns = [
            column
            for column in (
                "session_id",
                "scenario_id",
                "trial_id",
                "event_id",
                "condition_id",
            )
            if column in view.columns
        ]
        groups = view.groupby(group_columns, dropna=False, sort=True) if group_columns else [((), view)]
        for _, group in groups:
            ordered = group.sort_values("coverage", kind="stable")
            axes.plot(
                ordered["coverage"],
                ordered["selective_risk_mm"],
                color=_VARIANT_COLORS[ABLATION_VARIANTS[1]],
                alpha=0.18,
                linewidth=0.7,
            )
        median_curve = (
            view.groupby("coverage", as_index=False, sort=True)["selective_risk_mm"]
            .median()
        )
        axes.plot(
            median_curve["coverage"],
            median_curve["selective_risk_mm"],
            color=_VARIANT_COLORS[ABLATION_VARIANTS[1]],
            linewidth=2.0,
        )
    else:
        axes.text(0.5, 0.5, "No usable risk-coverage rows", ha="center", va="center")
    axes.set_xlabel("Coverage")
    axes.set_ylabel("Selective risk (mm)")
    axes.set_title("VCD risk-coverage diagnostic")
    axes.set_xlim(0.0, 1.0)
    axes.grid(alpha=0.25, linewidth=0.6)
    figure.savefig(output, format="pdf")
    plt.close(figure)


def write_exp2_figures(
    summary: pd.DataFrame,
    risk: pd.DataFrame,
    output_dir: Path | str,
) -> None:
    """按固定文件名生成四张组件差值图和一张 risk-coverage 图。"""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    _write_delta_figure(
        summary,
        output / "exp2_component_delta.pdf",
        REQUIRED_VARIANTS,
        preferred_metric=_DISPLAY_METRIC,
        metric_prefix="display_error.",
        title="Display translation attribution",
        ylabel="Ablation - full (mm)",
    )
    _write_delta_figure(
        summary,
        output / "exp2_alignment_effect.pdf",
        (BASELINE_VARIANT, ABLATION_VARIANTS[0]),
        preferred_metric=_DISPLAY_METRIC,
        metric_prefix="display_error.",
        title="Capture-time alignment effect",
        ylabel="Ablation - full (mm)",
    )
    _write_delta_figure(
        summary,
        output / "exp2_temporal_synthesis_effect.pdf",
        (BASELINE_VARIANT, ABLATION_VARIANTS[2]),
        preferred_metric=_TRANSITION_METRIC,
        metric_prefix="transition.",
        title="Temporal synthesis effect",
        ylabel="Ablation - full (ms)",
    )
    _write_delta_figure(
        summary,
        output / "exp2_static_lock_tradeoff.pdf",
        (BASELINE_VARIANT, ABLATION_VARIANTS[3]),
        preferred_metric=_STATIC_METRIC,
        metric_prefix="static.",
        title="StaticLock trade-off",
        ylabel="Ablation - full (mm)",
    )
    _write_risk_coverage(risk, output / "exp2_vcd_risk_coverage.pdf")


__all__ = ["write_exp2_figures"]

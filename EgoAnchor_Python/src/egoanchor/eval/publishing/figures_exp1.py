"""按 GPT final v2 规范绘制实验一三联图。"""

from __future__ import annotations

from collections import defaultdict
import math
from typing import Mapping

import matplotlib.pyplot as plt
import numpy as np

from .style import PlotSpec, save_figure_pair


_SYSTEM_ORDER = ("Arrival-Hold", "Capture-Hold", "One-Euro Anchor", "EgoAnchor")
"""实验一四系统固定显示顺序。"""

_SHORT_LABELS = {
    "Arrival-Hold": "Arrival",
    "Capture-Hold": "Capture",
    "One-Euro Anchor": "One-Euro",
    "EgoAnchor": "EgoAnchor",
}
"""图内短标签。"""

_COLORS = {
    "Arrival-Hold": "#2878B5",
    "Capture-Hold": "#F58518",
    "One-Euro Anchor": "#2CA02C",
    "EgoAnchor": "#D62728",
}
"""GPT final v2 四系统色板。"""

_MARKERS = {"Arrival-Hold": "s", "Capture-Hold": "o", "One-Euro Anchor": "^", "EgoAnchor": "D"}
"""GPT final v2 四系统 marker。"""


def _finite(row: Mapping[str, str], key: str) -> float | None:
    """读取有限 CSV 数值，空字符串返回空值。"""

    raw = str(row.get(key) or "").strip()
    if not raw:
        return None
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"实验一 plot 列 {key} 不是有限数值")
    return value


def _summary_groups(spec: PlotSpec, panel_id: str) -> tuple[dict[str, list[Mapping[str, str]]], dict[str, Mapping[str, str]]]:
    """分离 segment 点和 Stage 2 summary 行。"""

    segments: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    summaries: dict[str, Mapping[str, str]] = {}
    for row in spec.rows:
        if row.get("panel_id") != panel_id:
            continue
        variant = str(row.get("variant_id") or "")
        if row.get("point_kind") == "segment":
            segments[variant].append(row)
        elif row.get("point_kind") == "summary":
            summaries[variant] = row
    if set(segments) != set(_SYSTEM_ORDER) or set(summaries) != set(_SYSTEM_ORDER):
        raise ValueError(f"实验一 {panel_id} 缺少完整四系统 segment/summary")
    return segments, summaries


def _plot_summary(axis, spec: PlotSpec, panel_id: str, title: str, subtitle: str, ylabel: str) -> None:
    """绘制所有 segment 散点和每系统 median/IQR。"""

    segments, summaries = _summary_groups(spec, panel_id)
    x = np.arange(len(_SYSTEM_ORDER), dtype=float)
    for index, name in enumerate(_SYSTEM_ORDER):
        values = np.asarray([_finite(row, "value") for row in segments[name]], dtype=float)
        offsets = np.linspace(-0.11, 0.11, len(values)) if len(values) > 1 else np.asarray([0.0])
        axis.scatter(
            x[index] + offsets,
            values,
            color=_COLORS[name],
            marker=_MARKERS[name],
            s=24,
            alpha=0.42,
            linewidths=0.0,
            zorder=1,
        )
        summary = summaries[name]
        median = _finite(summary, "median")
        q1 = _finite(summary, "q1")
        q3 = _finite(summary, "q3")
        if median is None or q1 is None or q3 is None:
            raise ValueError(f"实验一 {panel_id}/{name} summary 不完整")
        axis.errorbar(
            x[index],
            median,
            yerr=np.asarray([[median - q1], [q3 - median]]),
            color=_COLORS[name],
            marker=_MARKERS[name],
            markersize=7.5,
            capsize=4,
            linewidth=1.7,
            zorder=3,
        )
    axis.set_xticks(x, [_SHORT_LABELS[name] for name in _SYSTEM_ORDER], rotation=16, ha="right")
    axis.set_title(title, loc="left", fontweight="bold", pad=15)
    axis.text(0.0, 1.01, subtitle, transform=axis.transAxes, ha="left", va="bottom", fontsize=8.8)
    axis.set_ylabel(ylabel)
    axis.set_ylim(bottom=0)
    axis.grid(axis="y", linestyle=":", linewidth=0.75, alpha=0.35)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)


def _plot_lag_tradeoff(axis, spec: PlotSpec) -> None:
    """绘制持续平移全部 segment 的 lag--RMSE 散点和摘要误差棒。"""

    event_rows: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    summaries: dict[str, Mapping[str, str]] = {}
    for row in spec.rows:
        variant = str(row.get("variant_id") or "")
        if row.get("point_kind") == "segment":
            event_rows[variant].append(row)
        elif row.get("point_kind") == "summary":
            summaries[variant] = row
    if set(event_rows) != set(_SYSTEM_ORDER) or set(summaries) != set(_SYSTEM_ORDER):
        raise ValueError("lag--RMSE 图缺少完整四系统 segment/summary")
    for name in _SYSTEM_ORDER:
        rows = event_rows[name]
        axis.scatter(
            [_finite(row, "effective_lag_ms") for row in rows],
            [_finite(row, "lag_residual_mm") for row in rows],
            color=_COLORS[name],
            marker=_MARKERS[name],
            s=24,
            alpha=0.28,
            label=_SHORT_LABELS[name],
            linewidths=0.0,
        )
        summary = summaries[name]
        lag = _finite(summary, "effective_lag_ms")
        residual = _finite(summary, "lag_residual_mm")
        lag_q1 = _finite(summary, "lag_q1_ms")
        lag_q3 = _finite(summary, "lag_q3_ms")
        residual_q1 = _finite(summary, "residual_q1_mm")
        residual_q3 = _finite(summary, "residual_q3_mm")
        if None in {lag, residual, lag_q1, lag_q3, residual_q1, residual_q3}:
            raise ValueError(f"lag--RMSE 摘要不完整：{name}")
        assert lag is not None and residual is not None
        assert lag_q1 is not None and lag_q3 is not None
        assert residual_q1 is not None and residual_q3 is not None
        axis.errorbar(
            lag,
            residual,
            xerr=np.asarray([[lag - lag_q1], [lag_q3 - lag]]),
            yerr=np.asarray([[residual - residual_q1], [residual_q3 - residual]]),
            color=_COLORS[name],
            marker=_MARKERS[name],
            markersize=8,
            capsize=3.5,
            linewidth=1.7,
            zorder=3,
        )
    axis.set_xlabel("Effective lag (ms)")
    axis.set_ylabel("Lag-aligned translation RMSE (mm)")
    axis.set_title("(b) Dynamic translation", loc="left", fontweight="bold", pad=15)
    axis.text(0.0, 1.01, "Lag and residual form a paired trade-off", transform=axis.transAxes, ha="left", va="bottom", fontsize=8.8)
    axis.annotate("better", xy=(0.07, 0.08), xytext=(0.26, 0.24), xycoords="axes fraction", textcoords="axes fraction", arrowprops={"arrowstyle": "->", "linewidth": 0.9})
    axis.grid(axis="both", linestyle=":", linewidth=0.75, alpha=0.35)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.legend(frameon=False, ncol=2, loc="upper center")


def publish_exp1(specs: Mapping[str, PlotSpec], output_root) -> dict[str, tuple[str, str]]:
    """发布 GPT final v2 风格实验一三联图。"""

    figure, axes = plt.subplots(1, 3, figsize=(13.9, 3.58), gridspec_kw={"width_ratios": (1.0, 1.06, 1.0)})
    _plot_summary(axes[0], specs["exp1_summary"], "world_consistency", "(a) World consistency", "Head motion should not move a static anchor", "Segment-wise translation P95 (mm)")
    _plot_lag_tradeoff(axes[1], specs["exp1_lag_tradeoff"])
    _plot_summary(axes[2], specs["exp1_summary"], "failure_containment", "(c) Failure containment", "Low-quality updates should not corrupt the anchor", "Occlusion-episode translation P95 (mm)")
    figure.subplots_adjust(left=0.045, right=0.995, bottom=0.22, top=0.82, wspace=0.38)
    return {"exp1_final_v2": save_figure_pair(figure, output_root, "exp1_final_v2")}


__all__ = ["publish_exp1"]

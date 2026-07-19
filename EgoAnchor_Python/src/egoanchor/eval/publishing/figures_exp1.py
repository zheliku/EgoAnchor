"""实验一 GPT 风格三联图的 CSV-only 绘制函数。"""

from __future__ import annotations

from collections import defaultdict
import math
from typing import Mapping

import matplotlib.pyplot as plt
import numpy as np

from .style import PlotSpec, save_figure_pair


_FIGURE_SIZE = (7.15, 2.25)
"""跨双栏三联图尺寸，接近 GPT 版的宽屏构图。"""

_SYSTEM_ORDER = ("Arrival-Hold", "Capture-Hold", "One-Euro Anchor", "EgoAnchor")
"""实验一系统显示顺序。"""

_COLORS = {
    "Arrival-Hold": "#2878B5",
    "Capture-Hold": "#F58518",
    "One-Euro Anchor": "#2CA02C",
    "EgoAnchor": "#D62728",
}
"""迁移 GPT 版的高对比、灰度可区分色板。"""

_MARKERS = {
    "Arrival-Hold": "s",
    "Capture-Hold": "o",
    "One-Euro Anchor": "^",
    "EgoAnchor": "D",
}
"""四个系统的形状编码。"""

_SUMMARY_COLOR = "#2878B5"
"""GPT 摘要栏使用的统一蓝色。"""


def _finite(row: Mapping[str, str], key: str) -> float | None:
    """读取有限 CSV 浮点值，空值返回 ``None``。"""

    raw = str(row.get(key) or "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"实验一 plot 列 {key} 不是数字") from exc
    if not math.isfinite(value):
        raise ValueError(f"实验一 plot 列 {key} 不是有限值")
    return value


def _summary_rows(spec: PlotSpec, panel_id: str) -> dict[str, Mapping[str, str]]:
    """按系统整理 Stage 2 已计算的摘要行。"""

    rows: dict[str, Mapping[str, str]] = {
        str(row.get("variant_id") or ""): row
        for row in spec.rows
        if row.get("panel_id") == panel_id
    }
    if tuple(rows) != tuple(name for name in _SYSTEM_ORDER if name in rows):
        raise ValueError(f"实验一摘要系统顺序或内容不完整：{panel_id}")
    return rows


def _plot_summary(axis, spec: PlotSpec, panel_id: str, title: str, ylabel: str) -> None:
    """绘制 GPT 风格的四系统 median/IQR 摘要点。"""

    grouped = _summary_rows(spec, panel_id)
    x = np.arange(len(_SYSTEM_ORDER), dtype=float)
    for index, name in enumerate(_SYSTEM_ORDER):
        row = grouped[name]
        median = _finite(row, "median")
        q1 = _finite(row, "q1")
        q3 = _finite(row, "q3")
        if median is None or q1 is None or q3 is None:
            raise ValueError(f"实验一摘要图统计量不完整：{panel_id}/{name}")
        axis.errorbar(
            x[index],
            median,
            yerr=np.asarray([[median - q1], [q3 - median]]),
            color=_SUMMARY_COLOR,
            marker="o",
            markersize=7.0,
            capsize=3.0,
            linewidth=1.35,
            markeredgecolor="white",
            markeredgewidth=0.45,
            zorder=3,
        )
    axis.set_xticks(x, ("Arrival", "Capture", "One-Euro", "EgoAnchor"), rotation=12, ha="right")
    axis.set_title(title, fontsize=9.5, pad=5)
    axis.set_ylabel(ylabel)
    axis.grid(axis="y", color="#D9D9D9", linewidth=0.45)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)


def _plot_lag_tradeoff(axis, spec: PlotSpec) -> None:
    """绘制全部持续平移 event 点与 Stage 2 median/IQR。"""

    event_rows: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    summaries: dict[str, Mapping[str, str]] = {}
    for row in spec.rows:
        name = str(row.get("variant_id") or "")
        if row.get("point_kind") == "event":
            event_rows[name].append(row)
        elif row.get("point_kind") == "summary":
            summaries[name] = row
    if set(event_rows) != set(_SYSTEM_ORDER) or set(summaries) != set(_SYSTEM_ORDER):
        raise ValueError("lag--fidelity 图缺少完整四系统 event/summary")
    for name in _SYSTEM_ORDER:
        rows = event_rows[name]
        axis.scatter(
            [_finite(row, "effective_lag_ms") for row in rows],
            [_finite(row, "p95_residual_mm") for row in rows],
            color=_COLORS[name],
            marker=_MARKERS[name],
            s=12,
            alpha=0.22,
            linewidths=0.0,
            zorder=1,
        )
        summary = summaries[name]
        lag = _finite(summary, "effective_lag_ms")
        residual = _finite(summary, "p95_residual_mm")
        lag_q1 = _finite(summary, "lag_q1_ms")
        lag_q3 = _finite(summary, "lag_q3_ms")
        residual_q1 = _finite(summary, "residual_q1_mm")
        residual_q3 = _finite(summary, "residual_q3_mm")
        if None in {lag, residual, lag_q1, lag_q3, residual_q1, residual_q3}:
            raise ValueError(f"lag--fidelity 摘要不完整：{name}")
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
            markersize=7.0,
            capsize=2.5,
            linewidth=1.25,
            label=name,
            zorder=3,
        )
    axis.text(0.04, 0.04, "lower-left is better", transform=axis.transAxes, va="bottom", color="#555555")
    axis.set_title("Translation trade-off", fontsize=9.5, pad=5)
    axis.set_xlabel("Effective lag (ms)")
    axis.set_ylabel("Lag-aligned residual (mm)")
    axis.grid(axis="y", color="#D9D9D9", linewidth=0.45)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)


def _legend(figure) -> None:
    """在 lag 面板内建立 GPT 风格短图例。"""

    handles = [
        plt.Line2D(
            (0,),
            (0,),
            marker=_MARKERS[name],
            color=_COLORS[name],
            linestyle="",
            markersize=5.8,
            label=name.replace("-Hold", ""),
        )
        for name in _SYSTEM_ORDER
    ]
    figure.axes[1].legend(handles=handles, loc="upper left", frameon=False, fontsize=7.0, handletextpad=0.35)


def publish_exp1(specs: Mapping[str, PlotSpec], output_root) -> dict[str, tuple[str, str]]:
    """绘制 GPT 风格实验一三联图并返回 PDF/PNG hash。"""

    figure, axes = plt.subplots(1, 3, figsize=_FIGURE_SIZE, gridspec_kw={"width_ratios": (1.0, 1.1, 1.0)})
    _plot_summary(axes[0], specs["exp1_summary"], "world_consistency", "(a) World consistency", "Translation P95 (mm)")
    _plot_lag_tradeoff(axes[1], specs["exp1_lag_tradeoff"])
    axes[1].set_title("(b) Translation trade-off", fontsize=9.5, pad=5)
    _plot_summary(axes[2], specs["exp1_summary"], "failure_containment", "(c) Failure containment", "Occlusion-window P95 (mm)")
    figure.subplots_adjust(left=0.055, right=0.995, bottom=0.23, top=0.88, wspace=0.35)
    _legend(figure)
    return {
        "exp1_behavior_overview": save_figure_pair(figure, output_root, "exp1_behavior_overview")
    }


__all__ = ["publish_exp1"]

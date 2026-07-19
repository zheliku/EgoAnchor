"""实验二 GPT 风格组件归因图的 CSV-only 绘制函数。"""

from __future__ import annotations

from collections import defaultdict
import math
from typing import Mapping

import matplotlib.pyplot as plt
import numpy as np

from .style import PlotSpec, save_figure_pair


_COMPONENT_ORDER = (
    "capture_time_alignment",
    "vcd_admission",
    "temporal_synthesis",
    "static_lock",
)
"""实验二组件从左到右的冻结顺序。"""

_COMPONENT_LABELS = {
    "capture_time_alignment": "Capture-time\nalignment",
    "vcd_admission": "VCD\nadmission",
    "temporal_synthesis": "Temporal\nsynthesis",
    "static_lock": "StaticLock",
}
"""组件机器键到短图内标签的映射。"""

_PRIMARY_METRICS = {
    "capture_time_alignment": "translation_event_pninetyfive_mm",
    "vcd_admission": "occlusion_translation_pninetyfive_mm",
    "temporal_synthesis": "motion_hold_ratio",
    "static_lock": "position_hp_rms_mm",
}
"""每个组件在适用场景内使用的主归因指标。"""

_Y_LABELS = {
    "capture_time_alignment": "Translation P95 Δ (mm)",
    "vcd_admission": "Occlusion P95 Δ (mm)",
    "temporal_synthesis": "Near-zero hold ratio Δ (pp)",
    "static_lock": "Position HP-RMS Δ (mm)",
}
"""组件主指标的读者轴标签。"""

_BLUE = "#1F77B4"
"""迁移 GPT 版 delta-only 图的统一主色。"""

_FIGURE_SIZE = (7.15, 2.08)
"""跨双栏四组件归因图尺寸。"""


def _finite(value: object) -> float | None:
    """读取有限 CSV 浮点值。"""

    try:
        number = float(str(value or ""))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _plot_delta_axis(axis, component: str, rows: list[Mapping[str, str]]) -> None:
    """绘制单组件 Ablated - Full median/IQR 与 event 散点。"""

    metric_key = _PRIMARY_METRICS[component]
    selected = [row for row in rows if row.get("metric_key") == metric_key]
    if not selected:
        raise ValueError(f"实验二主归因指标缺失：{component}/{metric_key}")
    deltas = [value for value in (_finite(row.get("delta")) for row in selected) if value is not None]
    if not deltas:
        raise ValueError(f"实验二主归因没有有效配对：{component}")
    medians = {value for value in (_finite(row.get("delta_median")) for row in selected) if value is not None}
    if len(medians) != 1:
        raise ValueError(f"实验二主归因 median 不唯一：{component}")
    median = next(iter(medians))
    first = selected[0]
    unit = str(first.get("metric_unit") or "")
    scale = 100.0 if unit == "proportion" else 1.0
    values = np.asarray(deltas, dtype=float) * scale
    median_value = median * scale
    finite_q1 = _finite(first.get("delta_q1"))
    finite_q3 = _finite(first.get("delta_q3"))
    if finite_q1 is None or finite_q3 is None:
        raise ValueError(f"实验二主归因 IQR 缺失：{component}")
    q1 = finite_q1 * scale
    q3 = finite_q3 * scale
    jitter = np.linspace(-0.035, 0.035, len(values)) if len(values) > 1 else np.asarray([0.0])
    axis.scatter(
        jitter,
        values,
        s=11,
        color="#8CB6D9",
        alpha=0.7,
        edgecolors="none",
        zorder=1,
    )
    axis.axhline(0.0, color="#777777", linewidth=0.75, zorder=0)
    axis.errorbar(
        0.0,
        median_value,
        yerr=np.asarray([[median_value - q1], [q3 - median_value]]),
        color=_BLUE,
        marker="o",
        markersize=7.0,
        capsize=3.0,
        linewidth=1.4,
        markeredgecolor="white",
        markeredgewidth=0.45,
        zorder=2,
    )
    axis.text(
        0.04,
        0.94,
        f"Δ = {median_value:+.3g}",
        transform=axis.transAxes,
        va="top",
        fontsize=8.0,
        fontweight="bold",
    )
    positive = sum(value > 0 for value in values)
    zero = sum(np.isclose(value, 0.0) for value in values)
    negative = len(values) - positive - zero
    axis.text(
        0.96,
        0.04,
        f"n={len(values)}  +/0/- {positive}/{zero}/{negative}",
        transform=axis.transAxes,
        ha="right",
        va="bottom",
        fontsize=6.8,
        color="#666666",
    )
    axis.set_title("Ablated - Full", fontsize=9.2, pad=4)
    axis.set_xticks((0.0,), (_COMPONENT_LABELS[component],))
    axis.set_ylabel(_Y_LABELS[component])
    axis.grid(axis="y", color="#D9D9D9", linewidth=0.45)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)


def publish_exp2(specs: Mapping[str, PlotSpec], output_root) -> dict[str, tuple[str, str]]:
    """绘制 GPT 风格四组件 delta-only 图并返回 PDF/PNG hash。"""

    grouped: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in specs["exp2_mechanism_attribution"].rows:
        grouped[str(row.get("component_id") or "")].append(row)
    figure, axes = plt.subplots(1, 4, figsize=_FIGURE_SIZE, sharey=False)
    for axis, component in zip(axes, _COMPONENT_ORDER):
        _plot_delta_axis(axis, component, grouped.get(component, []))
    figure.text(
        0.5,
        0.995,
        "Component attribution: Delta = Ablated - Full; interpret sign per metric direction",
        ha="center",
        va="top",
        fontsize=7.8,
        color="#555555",
    )
    figure.subplots_adjust(left=0.055, right=0.995, bottom=0.27, top=0.88, wspace=0.46)
    return {
        "exp2_mechanism_attribution": save_figure_pair(
            figure,
            output_root,
            "exp2_mechanism_attribution",
        )
    }


__all__ = ["publish_exp2"]

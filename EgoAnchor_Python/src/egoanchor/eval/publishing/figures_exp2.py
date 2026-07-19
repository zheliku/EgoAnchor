"""实验二 Full/Ablated/Delta 机制归因图的 CSV-only 绘制函数。"""

from __future__ import annotations

from collections import defaultdict
import math
from typing import Mapping

import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

from .style import PlotSpec, save_figure_pair


_COMPONENT_ORDER = (
    "capture_time_alignment",
    "static_lock",
    "temporal_synthesis",
    "vcd_admission",
)
"""实验二四个组件的小面板顺序。"""

_COMPONENT_LABELS = {
    "capture_time_alignment": "Capture-time alignment",
    "static_lock": "StaticLock",
    "temporal_synthesis": "Temporal synthesis",
    "vcd_admission": "VCD admission",
}
"""组件机器键到图内标签的映射。"""

def _finite(value: object) -> float | None:
    """把 CSV 单元格转换为有限浮点数。"""

    try:
        number = float(str(value or ""))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _delta_annotation(median_delta: float, metric_unit: str) -> str:
    """按面板单位格式化 Stage 2 差值中位数注释。

    参数：
        median_delta: Stage 2 已计算的消融减完整系统中位差。
        metric_unit: 冻结指标单位；比例使用百分点显示。
    """

    if metric_unit == "proportion":
        return f"Delta median={median_delta * 100.0:.3g} pp"
    return f"Delta median={median_delta:.3g}"


def _plot_mechanism_attribution(
    mechanism: PlotSpec,
    vcd_curve: PlotSpec,
) -> plt.Figure:
    """绘制四组件独立单位的 paired Full/Ablated 小面板。"""

    grouped: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in mechanism.rows:
        component = str(row.get("component_id") or "")
        grouped[component].append(row)

    figure, axes = plt.subplots(2, 2, figsize=(10.5, 3.8), squeeze=False)
    for axis, component in zip(axes.flat, _COMPONENT_ORDER):
        rows = grouped.get(component, [])
        if not rows:
            axis.text(0.5, 0.5, "No paired data", ha="center", va="center")
            axis.set_title(_COMPONENT_LABELS[component])
            axis.set_axis_off()
            continue
        pairs = []
        for pair_row in rows:
            full_value = _finite(pair_row.get("full_value"))
            ablation_value = _finite(pair_row.get("ablation_value"))
            if full_value is not None and ablation_value is not None:
                pairs.append((full_value, ablation_value))
        full = [pair[0] for pair in pairs]
        ablation = [pair[1] for pair in pairs]
        for full_value, ablation_value in pairs:
            axis.plot(
                (0, 1),
                (full_value, ablation_value),
                color="#BDBDBD",
                linewidth=0.8,
                zorder=1,
            )
        axis.scatter([0] * len(full), full, color="#0072B2", s=24, label="Full", zorder=2)
        axis.scatter([1] * len(ablation), ablation, color="#D55E00", s=24, label="Ablated", zorder=2)
        metric_unit = str(rows[0].get("metric_unit") or "value")
        median_delta = _finite(rows[0].get("delta_median"))
        if median_delta is not None:
            axis.text(
                0.04,
                0.94,
                _delta_annotation(median_delta, metric_unit),
                transform=axis.transAxes,
                va="top",
                fontsize=8,
            )
        axis.set_xticks((0, 1), ("Full", "Ablated"))
        if metric_unit == "proportion":
            axis.yaxis.set_major_formatter(PercentFormatter(1.0))
            axis.set_ylabel("Hold ratio")
        else:
            axis.set_ylabel(metric_unit)
        axis.set_title(_COMPONENT_LABELS[component])
        axis.grid(axis="y", color="#DDDDDD", linewidth=0.45)
        if component == "capture_time_alignment":
            axis.legend(frameon=False, fontsize=8, loc="best")

    figure.suptitle("Experiment 2: Full vs ablated paired mechanisms")
    figure.tight_layout(rect=(0.0, 0.0, 1.0, 0.95))
    vcd_axis = axes[1, 1]
    panel = vcd_axis.get_position()
    vcd_axis.set_position((panel.x0, panel.y0, panel.width * 0.54, panel.height))
    inset = figure.add_axes(
        (
            panel.x0 + panel.width * 0.62,
            panel.y0 + panel.height * 0.12,
            panel.width * 0.36,
            panel.height * 0.72,
        )
    )
    for reference_kind, color, linestyle in (("vcd", "#0072B2", "-"), ("random", "#6B6B6B", "--")):
        points = [
            row
            for row in vcd_curve.rows
            if row.get("reference_kind") == reference_kind
            and row.get("risk_kind") == "tail_pninetyfive"
        ]
        points.sort(key=lambda row: float(row.get("coverage") or 0.0))
        if points:
            inset.plot(
                [float(row["coverage"]) for row in points],
                [float(row["risk_mm"]) for row in points],
                color=color,
                linestyle=linestyle,
                marker="o",
                markersize=2.5,
                label=reference_kind,
            )
    actual = [row for row in vcd_curve.rows if row.get("reference_kind") == "actual_admitted"]
    if actual:
        inset.scatter(
            [float(actual[0]["coverage"])],
            [float(actual[0]["risk_mm"])],
            color="#009E73",
            marker="*",
            s=65,
            edgecolor="#111111",
            linewidth=0.45,
            zorder=4,
            label="actual admitted",
        )
    inset.set_title("VCD operating point", fontsize=8)
    inset.set_xlabel("coverage", fontsize=7)
    inset.set_ylabel("P95 mm", fontsize=7)
    inset.tick_params(labelsize=7)
    inset.grid(color="#EEEEEE", linewidth=0.35)
    handles, labels = inset.get_legend_handles_labels()
    if handles:
        inset.legend(frameon=False, fontsize=6)
    return figure


def publish_exp2(specs: Mapping[str, PlotSpec], output_root) -> dict[str, tuple[str, str]]:
    """绘制实验二机制归因图并返回 PDF/PNG hash。"""

    return {
        "exp2_mechanism_attribution": save_figure_pair(
            _plot_mechanism_attribution(
                specs["exp2_mechanism_attribution"],
                specs["exp2_vcd_curve"],
            ),
            output_root,
            "exp2_mechanism_attribution",
        )
    }


__all__ = ["publish_exp2"]

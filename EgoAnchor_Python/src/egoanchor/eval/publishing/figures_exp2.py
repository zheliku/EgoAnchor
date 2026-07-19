"""实验二 Full/Ablated/Delta 机制归因图的 CSV-only 绘制函数。"""

from __future__ import annotations

from collections import defaultdict
import math
from typing import Mapping

import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

from .style import ABLATION_COLOR, COLORS, DOUBLE_COLUMN_SIZE, PlotSpec, save_figure_pair


_COMPONENT_ORDER = (
    "capture_time_alignment",
    "static_lock",
    "temporal_synthesis",
    "vcd_admission",
)
"""实验二四个组件的小面板顺序。"""

_COMPONENT_LABELS = {
    "capture_time_alignment": "(A) Capture-time alignment",
    "static_lock": "(B) StaticLock",
    "temporal_synthesis": "(C) Temporal synthesis",
    "vcd_admission": "(D) VCD admission",
}
"""组件机器键到图内标签的映射。"""

_COMPONENT_Y_LABELS = {
    "capture_time_alignment": "Translation P95 (mm)",
    "static_lock": "Position HP-RMS (mm)",
    "temporal_synthesis": "Near-zero hold ratio",
    "vcd_admission": "Occlusion P95 (mm)",
}
"""实验二各组件冻结主指标的读者轴标签。"""

_FIGURE_SIZE = (DOUBLE_COLUMN_SIZE[0], 3.35)
"""实验二图按最终双栏物理宽度生成，避免论文插入后缩小字号。"""

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
        return rf"$\Delta$ = {median_delta * 100.0:+.1f} pp"
    return rf"$\Delta$ = {median_delta:+.2f} {metric_unit}"


def _paired_values(rows: list[Mapping[str, str]]) -> tuple[list[float], list[float]]:
    """提取数值完整的 Full/Ablated 配对。

    参数：
        rows: 同一组件的 Stage 2 plot-ready 行。
    """

    pairs: list[tuple[float, float]] = []
    for row in rows:
        full_value = _finite(row.get("full_value"))
        ablation_value = _finite(row.get("ablation_value"))
        if full_value is not None and ablation_value is not None:
            pairs.append((full_value, ablation_value))
    return [pair[0] for pair in pairs], [pair[1] for pair in pairs]


def _plot_component_axis(axis, component: str, rows: list[Mapping[str, str]]) -> None:
    """绘制一个组件的同事件 Full/Ablated slopegraph。

    参数：
        axis: 目标 Matplotlib 坐标轴。
        component: 冻结组件机器键。
        rows: 该组件的 plot-ready 配对行。
    """

    if not rows:
        axis.text(0.5, 0.5, "No paired data", ha="center", va="center")
        axis.set_title(_COMPONENT_LABELS[component])
        axis.set_axis_off()
        return
    full, ablation = _paired_values(rows)
    for full_value, ablation_value in zip(full, ablation):
        axis.plot((0, 1), (full_value, ablation_value), color="#B8B8B8", linewidth=0.65, zorder=1)
    axis.scatter([0] * len(full), full, color=COLORS["EgoAnchor"], s=20, zorder=2)
    axis.scatter([1] * len(ablation), ablation, color=ABLATION_COLOR, s=20, zorder=2)
    metric_units = {str(row.get("metric_unit") or "") for row in rows}
    if len(metric_units) != 1:
        raise ValueError(f"实验二组件单位不唯一：{component}")
    metric_unit = next(iter(metric_units))
    median_values = {
        value
        for value in (_finite(row.get("delta_median")) for row in rows)
        if value is not None
    }
    if len(median_values) != 1:
        raise ValueError(f"实验二组件差值中位数不唯一：{component}")
    axis.text(
        0.04,
        0.94,
        _delta_annotation(next(iter(median_values)), metric_unit),
        transform=axis.transAxes,
        va="top",
    )
    axis.set_xticks((0, 1), ("Full", "Ablated"))
    if metric_unit == "proportion":
        axis.yaxis.set_major_formatter(PercentFormatter(1.0))
    axis.set_ylabel(_COMPONENT_Y_LABELS[component])
    axis.set_title(_COMPONENT_LABELS[component])
    axis.grid(axis="y", color="#DDDDDD", linewidth=0.45)


def _plot_vcd_curve(axis, rows: tuple[Mapping[str, str], ...]) -> None:
    """绘制候选级 VCD/random tail-risk 和实际接纳工作点。

    参数：
        axis: VCD 组件旁的独立小轴。
        rows: Stage 2 VCD curve 行。
    """

    for reference_kind, label, color, linestyle in (
        ("vcd", "VCD", "#0072B2", "-"),
        ("random", "Random", "#6B6B6B", "--"),
    ):
        points = [
            row
            for row in rows
            if row.get("reference_kind") == reference_kind
            and row.get("risk_kind") == "tail_pninetyfive"
        ]
        points.sort(key=lambda row: float(row.get("coverage") or 0.0))
        if points:
            coverage = [float(row["coverage"]) for row in points]
            risk = [float(row["risk_mm"]) for row in points]
            axis.plot(
                coverage,
                risk,
                color=color,
                linestyle=linestyle,
                linewidth=1.0,
            )
            label_index = -1 if reference_kind == "random" else max(0, int(len(points) * 0.72) - 1)
            axis.annotate(
                label,
                (coverage[label_index], risk[label_index]),
                xytext=(-3, 5 if reference_kind == "random" else -8),
                textcoords="offset points",
                ha="right",
                color=color,
            )
    actual = [row for row in rows if row.get("reference_kind") == "actual_admitted"]
    if len(actual) > 1:
        raise ValueError("VCD curve 只能包含一个实际接纳工作点")
    if actual:
        axis.scatter(
            [float(actual[0]["coverage"])],
            [float(actual[0]["risk_mm"])],
            color=COLORS["EgoAnchor"],
            marker="*",
            s=55,
            edgecolor="#111111",
            linewidth=0.45,
            zorder=4,
        )
        axis.annotate(
            "Actual",
            (float(actual[0]["coverage"]), float(actual[0]["risk_mm"])),
            xytext=(-4, -9),
            textcoords="offset points",
            ha="right",
            color=COLORS["EgoAnchor"],
        )
    axis.set_title("Risk-coverage")
    axis.set_xlabel("Coverage")
    axis.set_ylabel("Tail risk P95 (mm)")
    axis.grid(color="#EEEEEE", linewidth=0.35)


def _plot_mechanism_attribution(
    mechanism: PlotSpec,
    vcd_curve: PlotSpec,
) -> plt.Figure:
    """绘制四组件独立单位的 paired Full/Ablated 小面板。"""

    grouped: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in mechanism.rows:
        component = str(row.get("component_id") or "")
        grouped[component].append(row)

    figure = plt.figure(figsize=_FIGURE_SIZE)
    grid = figure.add_gridspec(
        2,
        4,
        width_ratios=(1.0, 1.0, 1.05, 0.95),
        hspace=0.68,
        wspace=0.82,
    )
    component_axes = (
        figure.add_subplot(grid[0, 0:2]),
        figure.add_subplot(grid[0, 2:4]),
        figure.add_subplot(grid[1, 0:2]),
        figure.add_subplot(grid[1, 2]),
    )
    for axis, component in zip(component_axes, _COMPONENT_ORDER):
        _plot_component_axis(axis, component, grouped.get(component, []))
    _plot_vcd_curve(figure.add_subplot(grid[1, 3]), vcd_curve.rows)
    figure.subplots_adjust(left=0.075, right=0.995, bottom=0.14, top=0.94)
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

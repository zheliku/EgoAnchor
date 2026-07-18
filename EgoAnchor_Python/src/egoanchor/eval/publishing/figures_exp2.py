"""实验二 CSV 图表绘制函数。"""

from __future__ import annotations

from collections import defaultdict
import math
from typing import Mapping

import matplotlib.pyplot as plt

from .style import ABLATION_COLOR, HALF_PANEL_SIZE, PlotSpec, display_label, finite_rows, save_figure_pair


def _plot_component_deltas(spec: PlotSpec) -> plt.Figure:
    """绘制组件消融的 event 配对差值点。"""

    grouped: dict[str, list[tuple[int, float, Mapping[str, str]]]] = defaultdict(list)
    for index, value, row in finite_rows(spec.rows, spec.y):
        grouped[str(row.get(spec.hue) or "unknown")].append((index, value, row))
    names = sorted(grouped)
    figure, axis = plt.subplots(figsize=HALF_PANEL_SIZE)
    for position, name in enumerate(names):
        values = [item[1] for item in grouped[name]]
        x = [position + 1 + (index - (len(values) - 1) / 2) * 0.08 for index in range(len(values))]
        axis.scatter(x, values, color=ABLATION_COLOR, s=24, label="Delta" if position == 0 else None)
    axis.axhline(0.0, color="#333333", linewidth=0.7)
    axis.set_xticks(range(1, len(names) + 1), [display_label(name) for name in names], rotation=20, ha="right")
    axis.set_title("Paired ablation deltas")
    axis.set_xlabel("Component")
    axis.set_ylabel(display_label(spec.y))
    axis.grid(axis="y", color="#DDDDDD", linewidth=0.45)
    axis.legend(frameon=False)
    figure.tight_layout()
    return figure


def _plot_vcd_curve(spec: PlotSpec) -> plt.Figure:
    """绘制 VCD risk-coverage 曲线，保留各阈值点。"""

    grouped: dict[str, list[tuple[float, float, Mapping[str, str]]]] = defaultdict(list)
    for row in spec.rows:
        try:
            coverage = float(row.get(spec.x) or "")
            risk = float(row.get(spec.y) or "")
        except ValueError as exc:
            raise ValueError("VCD plot 的 coverage 或 risk 不是数字") from exc
        if not (math.isfinite(coverage) and math.isfinite(risk)):
            raise ValueError("VCD plot 的 coverage 或 risk 不是有限数字")
        grouped[str(row.get(spec.hue) or "unknown")].append((coverage, risk, row))
    figure, axis = plt.subplots(figsize=HALF_PANEL_SIZE)
    for name in sorted(grouped):
        points = sorted(grouped[name], key=lambda item: item[0])
        axis.plot(
            [point[0] for point in points],
            [point[1] for point in points],
            label=name,
            color="#0072B2" if name == "vcd" else "#6B6B6B",
            linestyle="-" if name == "vcd" else "--",
            marker="o",
            markersize=3.2,
        )
    axis.set_title("VCD risk-coverage")
    axis.set_xlabel("Coverage")
    axis.set_ylabel(display_label(spec.y))
    axis.grid(color="#DDDDDD", linewidth=0.45)
    axis.legend(frameon=False)
    figure.tight_layout()
    return figure


def publish_exp2(specs: Mapping[str, PlotSpec], output_root) -> dict[str, tuple[str, str]]:
    """绘制实验二两张图并返回 PDF/PNG hash。"""

    return {
        "exp2_component_deltas": save_figure_pair(
            _plot_component_deltas(specs["exp2_component_deltas"]),
            output_root,
            "exp2_component_deltas",
        ),
        "exp2_vcd_curve": save_figure_pair(
            _plot_vcd_curve(specs["exp2_vcd_curve"]),
            output_root,
            "exp2_vcd_curve",
        ),
    }


__all__ = ["publish_exp2"]

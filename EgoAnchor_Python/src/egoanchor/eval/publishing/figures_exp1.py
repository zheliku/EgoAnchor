"""实验一 CSV 图表绘制函数。

本模块只接收已由 ``publishing.style`` 校验过的 plot spec，不接触 XLSX 或原始日志。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Mapping

import matplotlib.pyplot as plt

from .style import (
    COLORS,
    LINE_STYLES,
    MARKERS,
    PlotSpec,
    SYSTEM_ORDER,
    THIRD_PANEL_SIZE,
    display_label,
    finite_rows,
    save_figure_pair,
)


def _group_rows(spec: PlotSpec) -> dict[str, list[tuple[int, float, Mapping[str, str]]]]:
    """按 catalog 声明的 hue 列分组并保留输入顺序。"""

    grouped: dict[str, list[tuple[int, float, Mapping[str, str]]]] = defaultdict(list)
    for index, value, row in finite_rows(spec.rows, spec.y):
        grouped[str(row.get(spec.hue) or "unknown")].append((index, value, row))
    return grouped


def _ordered_groups(grouped: Mapping[str, object]) -> list[str]:
    """按冻结系统顺序排列已出现的系统名。"""

    return [name for name in SYSTEM_ORDER if name in grouped] + sorted(
        name for name in grouped if name not in SYSTEM_ORDER
    )


def _legend_or_empty(axis) -> None:
    """用适合三联图宽度的短标签绘制图例。

    参数：
        axis: 当前 Matplotlib 坐标轴。
    """

    handles, labels = axis.get_legend_handles_labels()
    if handles:
        short = {
            "Arrival-Hold": "Arrival",
            "Capture-Hold": "Capture",
            "One-Euro Anchor": "One-Euro",
            "EgoAnchor": "EgoAnchor",
        }
        axis.legend(
            handles,
            [short.get(label, label) for label in labels],
            frameon=False,
            ncol=2,
            columnspacing=0.7,
            handlelength=1.5,
            loc="upper center",
            bbox_to_anchor=(0.5, -0.28),
            borderaxespad=0.0,
        )
    else:
        axis.text(0.5, 0.5, "No event rows", ha="center", va="center", transform=axis.transAxes)


def _plot_event_lines(spec: PlotSpec, title: str) -> plt.Figure:
    """绘制 event/segment 点线图，保留每个事件观测而非 frame 汇总。"""

    grouped = _group_rows(spec)
    figure, axis = plt.subplots(figsize=THIRD_PANEL_SIZE)
    for name in _ordered_groups(grouped):
        points = grouped[name]
        x = list(range(1, len(points) + 1))
        axis.plot(
            x,
            [point[1] for point in points],
            label=name,
            color=COLORS.get(name, "#333333"),
            linestyle=LINE_STYLES.get(name, "-"),
            marker=MARKERS.get(name, "o"),
            markersize=3.5,
        )
    axis.set_title(title)
    axis.set_ylabel(display_label(spec.y))
    event_count = max((len(points) for points in grouped.values()), default=0)
    if event_count:
        axis.set_xticks(range(1, event_count + 1))
    axis.grid(axis="y", color="#DDDDDD", linewidth=0.45)
    _legend_or_empty(axis)
    figure.tight_layout()
    return figure


def _plot_event_points(spec: PlotSpec, title: str) -> plt.Figure:
    """绘制运动事件散点，避免低样本条件下使用柱状图。"""

    grouped = _group_rows(spec)
    figure, axis = plt.subplots(figsize=THIRD_PANEL_SIZE)
    names = _ordered_groups(grouped)
    event_groups: dict[tuple[str, str, str, str], dict[str, float]] = defaultdict(dict)
    for name in names:
        for _, value, row in grouped[name]:
            key = (
                str(row.get("session_id") or ""),
                str(row.get("scenario_id") or ""),
                str(row.get("trial_id") or ""),
                str(row.get(spec.x) or ""),
            )
            event_groups[key][name] = value
    event_positions = {key: index + 1 for index, key in enumerate(event_groups)}
    center = (len(names) - 1) / 2
    for key, values in event_groups.items():
        base = event_positions[key]
        pair = [
            (base + (index - center) * 0.12, values[name])
            for index, name in enumerate(names)
            if name in values
        ]
        if len(pair) >= 2:
            axis.plot(
                [item[0] for item in pair],
                [item[1] for item in pair],
                color="#BBBBBB",
                linewidth=0.55,
                zorder=1,
            )
    for offset, name in enumerate(names):
        points = grouped[name]
        x = []
        for _, _, row in points:
            key = (
                str(row.get("session_id") or ""),
                str(row.get("scenario_id") or ""),
                str(row.get("trial_id") or ""),
                str(row.get(spec.x) or ""),
            )
            x.append(event_positions[key] + (offset - center) * 0.12)
        axis.scatter(
            x,
            [point[1] for point in points],
            label=name,
            color=COLORS.get(name, "#333333"),
            marker=MARKERS.get(name, "o"),
            s=22,
        )
    axis.set_title(title)
    axis.set_ylabel(display_label(spec.y))
    axis.grid(axis="y", color="#DDDDDD", linewidth=0.45)
    _legend_or_empty(axis)
    figure.tight_layout()
    return figure


def _plot_occlusion(spec: PlotSpec) -> plt.Figure:
    """绘制遮挡事件经验风险曲线，展示全部 event 点。"""

    grouped = _group_rows(spec)
    figure, axis = plt.subplots(figsize=THIRD_PANEL_SIZE)
    for name in _ordered_groups(grouped):
        values = sorted(point[1] for point in grouped[name])
        if not values:
            continue
        coverage = [(index + 1) / len(values) for index in range(len(values))]
        axis.plot(
            coverage,
            values,
            label=name,
            color=COLORS.get(name, "#333333"),
            linestyle=LINE_STYLES.get(name, "-"),
            marker=MARKERS.get(name, "o"),
            markersize=3.0,
        )
    axis.set_title("Occlusion recovery event errors")
    axis.set_ylabel(display_label(spec.y))
    axis.grid(color="#DDDDDD", linewidth=0.45)
    _legend_or_empty(axis)
    figure.tight_layout()
    return figure


def publish_exp1(specs: Mapping[str, PlotSpec], output_root) -> dict[str, tuple[str, str]]:
    """绘制实验一三张图并返回 PDF/PNG hash。"""

    results: dict[str, tuple[str, str]] = {}
    results["exp1_static_timeline"] = save_figure_pair(
        _plot_event_lines(specs["exp1_static_timeline"], "Static head-motion event errors"),
        output_root,
        "exp1_static_timeline",
    )
    results["exp1_motion_events"] = save_figure_pair(
        _plot_event_points(specs["exp1_motion_events"], "Motion event errors"),
        output_root,
        "exp1_motion_events",
    )
    results["exp1_occlusion_events"] = save_figure_pair(
        _plot_occlusion(specs["exp1_occlusion_events"]),
        output_root,
        "exp1_occlusion_events",
    )
    return results


__all__ = ["publish_exp1"]

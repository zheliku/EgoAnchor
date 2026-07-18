"""实验一四面板系统行为图的 CSV-only 绘制函数。"""

from __future__ import annotations

from collections import defaultdict
import math
from typing import Mapping

import matplotlib.pyplot as plt
import numpy as np

from .style import COLORS, LINE_STYLES, MARKERS, PlotSpec, SYSTEM_ORDER, save_figure_pair


_FIGURE_SIZE = (7.1, 4.8)
"""IEEE VR 双栏四面板图的英寸尺寸。"""


def _number(row: Mapping[str, str], key: str) -> float | None:
    """读取有限绘图数值，空单元格返回 ``None``。"""

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


def _bool(row: Mapping[str, str], key: str) -> bool:
    """读取冻结 CSV 小写布尔值。"""

    value = str(row.get(key) or "").strip().lower()
    if value not in {"true", "false"}:
        raise ValueError(f"实验一 plot 列 {key} 不是布尔值")
    return value == "true"


def _group_by_variant(spec: PlotSpec) -> dict[str, list[Mapping[str, str]]]:
    """按固定系统顺序前的 variant 字段分组并按样本排序。"""

    grouped: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in spec.rows:
        grouped[str(row.get("variant_id") or "unknown")].append(row)
    for rows in grouped.values():
        rows.sort(key=lambda row: int(str(row.get("sample_index") or "0")))
    return grouped


def _system_order(grouped: Mapping[str, object]) -> tuple[str, ...]:
    """返回已出现系统的冻结论文顺序。"""

    return tuple(name for name in SYSTEM_ORDER if name in grouped)


def _plot_head_motion(axis, spec: PlotSpec) -> None:
    """绘制头动角速度与三系统平移误差时间线。"""

    grouped = _group_by_variant(spec)
    for name in _system_order(grouped):
        rows = grouped[name]
        x = [float(_number(row, "time_ms") or 0.0) / 1000.0 for row in rows]
        y = [_number(row, "translation_error_mm") for row in rows]
        axis.plot(x, y, color=COLORS[name], linestyle=LINE_STYLES[name], label=name)
    ego_rows = grouped.get("EgoAnchor", [])
    secondary = axis.twinx()
    secondary.plot(
        [float(_number(row, "time_ms") or 0.0) / 1000.0 for row in ego_rows],
        [_number(row, "head_angular_speed_deg_s") for row in ego_rows],
        color="#9A9A9A",
        linewidth=0.7,
        alpha=0.75,
    )
    secondary.set_ylabel("Head speed (deg/s)", color="#666666")
    secondary.tick_params(axis="y", colors="#666666")
    axis.set_title("(A) Head motion: alignment limits error")
    axis.set_xlabel("Time (s)")
    axis.set_ylabel("Translation error (mm)")


def _phase_bounds(rows: list[Mapping[str, str]], phase: str) -> tuple[float, float] | None:
    """返回指定 phase 的秒制时间范围。"""

    values = [float(_number(row, "time_ms") or 0.0) / 1000.0 for row in rows if row.get("phase") == phase]
    return None if not values else (min(values), max(values))


def _plot_start_stop(axis, spec: PlotSpec) -> None:
    """绘制参考与四系统起停位移轨迹。"""

    grouped = _group_by_variant(spec)
    ego_rows = grouped.get("EgoAnchor", [])
    x_reference = [float(_number(row, "time_ms") or 0.0) / 1000.0 for row in ego_rows]
    axis.plot(
        x_reference,
        [_number(row, "reference_displacement_mm") for row in ego_rows],
        color="#222222",
        linewidth=1.0,
        label="Reference",
    )
    for name in _system_order(grouped):
        rows = grouped[name]
        axis.plot(
            [float(_number(row, "time_ms") or 0.0) / 1000.0 for row in rows],
            [_number(row, "display_displacement_mm") for row in rows],
            color=COLORS[name],
            linestyle=LINE_STYLES[name],
            label=name,
        )
    motion = _phase_bounds(ego_rows, "motion")
    post_stop = _phase_bounds(ego_rows, "post_stop")
    if motion is not None:
        axis.axvspan(*motion, color="#D9EAF7", alpha=0.55, linewidth=0.0)
    if post_stop is not None:
        axis.axvspan(*post_stop, color="#E2F0E9", alpha=0.6, linewidth=0.0)
    axis.set_title("(B) Start-stop: response and rest")
    axis.set_xlabel("Time (s)")
    axis.set_ylabel("Displacement (mm)")


def _plot_lag_tradeoff(axis, spec: PlotSpec) -> None:
    """绘制全部 event 点和 Stage 2 预计算的系统 median/IQR。"""

    event_groups: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    summaries: dict[str, Mapping[str, str]] = {}
    for row in spec.rows:
        name = str(row.get("variant_id") or "unknown")
        if row.get("point_kind") == "event":
            event_groups[name].append(row)
        elif row.get("point_kind") == "summary":
            summaries[name] = row
        else:
            raise ValueError("lag trade-off point_kind 非法")
    for name in _system_order(event_groups):
        rows = event_groups[name]
        axis.scatter(
            [_number(row, "effective_lag_ms") for row in rows],
            [_number(row, "p95_residual_mm") for row in rows],
            color=COLORS[name],
            marker=MARKERS[name],
            s=9,
            alpha=0.28,
            linewidths=0.0,
        )
        summary = summaries.get(name)
        if summary is None:
            raise ValueError(f"lag trade-off 缺少系统 summary：{name}")
        x = float(_number(summary, "effective_lag_ms") or 0.0)
        y = float(_number(summary, "p95_residual_mm") or 0.0)
        x_q1 = float(_number(summary, "lag_q1_ms") or x)
        x_q3 = float(_number(summary, "lag_q3_ms") or x)
        y_q1 = float(_number(summary, "residual_q1_mm") or y)
        y_q3 = float(_number(summary, "residual_q3_mm") or y)
        axis.errorbar(
            x,
            y,
            xerr=np.asarray([[x - x_q1], [x_q3 - x]]),
            yerr=np.asarray([[y - y_q1], [y_q3 - y]]),
            color=COLORS[name],
            marker=MARKERS[name],
            markersize=5.0,
            capsize=2.0,
            linewidth=1.0,
            label=name,
        )
    axis.text(0.03, 0.95, "lower-left is better", transform=axis.transAxes, va="top", color="#555555")
    axis.set_title("(C) Translation: lag-fidelity trade-off")
    axis.set_xlabel("Effective lag (ms)")
    axis.set_ylabel("Lag-compensated P95 (mm)")


def _plot_occlusion(axis, spec: PlotSpec) -> None:
    """绘制遮挡误差时间线、遮挡区间和 EgoAnchor output 缺失标记。"""

    grouped = _group_by_variant(spec)
    for name in _system_order(grouped):
        rows = grouped[name]
        axis.plot(
            [float(_number(row, "time_ms") or 0.0) / 1000.0 for row in rows],
            [_number(row, "translation_error_mm") for row in rows],
            color=COLORS[name],
            linestyle=LINE_STYLES[name],
            label=name,
        )
    ego_rows = grouped.get("EgoAnchor", [])
    hidden_times = [
        float(_number(row, "time_ms") or 0.0) / 1000.0
        for row in ego_rows
        if _bool(row, "occluded")
    ]
    if hidden_times:
        axis.axvspan(min(hidden_times), max(hidden_times), color="#EFE5D5", alpha=0.7, linewidth=0.0)
    unavailable = [
        float(_number(row, "time_ms") or 0.0) / 1000.0
        for row in ego_rows
        if not _bool(row, "has_output_pose")
    ]
    if unavailable:
        axis.scatter(
            unavailable,
            np.zeros(len(unavailable)),
            color="#D55E00",
            marker="|",
            s=13,
            linewidths=0.6,
            label="Ego output unavailable",
        )
    axis.set_title("(D) Occlusion: harmful updates contained")
    axis.set_xlabel("Time (s)")
    axis.set_ylabel("Translation error (mm)")


def _shared_legend(figure, axes) -> None:
    """为四面板图建立去重的底部共享图例。"""

    handles: list[object] = []
    labels: list[str] = []
    for axis in axes:
        for handle, label in zip(*axis.get_legend_handles_labels()):
            if label not in labels:
                handles.append(handle)
                labels.append(label)
    if handles:
        figure.legend(
            handles,
            labels,
            loc="lower center",
            ncol=6,
            frameon=False,
            bbox_to_anchor=(0.5, 0.0),
            columnspacing=1.0,
            handlelength=1.5,
        )


def publish_exp1(specs: Mapping[str, PlotSpec], output_root) -> dict[str, tuple[str, str]]:
    """绘制实验一四面板组合图并返回 PDF/PNG hash。"""

    figure, grid = plt.subplots(2, 2, figsize=_FIGURE_SIZE)
    axes = tuple(grid.flat)
    _plot_head_motion(axes[0], specs["exp1_head_motion_trace"])
    _plot_start_stop(axes[1], specs["exp1_start_stop_trace"])
    _plot_lag_tradeoff(axes[2], specs["exp1_lag_tradeoff"])
    _plot_occlusion(axes[3], specs["exp1_occlusion_trace"])
    for axis in axes:
        axis.grid(axis="y", color="#DDDDDD", linewidth=0.45)
    _shared_legend(figure, axes)
    figure.tight_layout(rect=(0.0, 0.08, 1.0, 1.0), h_pad=1.4, w_pad=1.2)
    return {
        "exp1_behavior_overview": save_figure_pair(
            figure,
            output_root,
            "exp1_behavior_overview",
        )
    }


__all__ = ["publish_exp1"]

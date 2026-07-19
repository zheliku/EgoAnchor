"""按 GPT final v2 规范绘制实验二组件归因图。"""

from __future__ import annotations

from collections import defaultdict
import math
from typing import Mapping, Sequence

import matplotlib.pyplot as plt
import numpy as np

from .style import PlotSpec, save_figure_pair


_COMPONENT_ORDER = ("capture_time_alignment", "static_lock", "vcd_admission")
"""GPT 左侧三个目标组件顺序。"""

_COMPONENT_LABELS = {
    "capture_time_alignment": ("Capture alignment", "prevents head-motion leakage", "Raw candidate P95 (mm)"),
    "static_lock": ("StaticLock", "stabilizes the resting anchor", "Stationary median (mm)"),
    "vcd_admission": ("VCD admission", "rejects harmful occlusion updates", "Occlusion P95 (mm)"),
}
"""组件标题、副标题和纵轴标签。"""

_COMPONENT_PLOT_METRICS = {
    "capture_time_alignment": "capture_alignment_raw_translation_pninetyfive_mm",
    "static_lock": "position_hp_rms_mm",
    "vcd_admission": "occlusion_translation_pninetyfive_mm",
}
"""每个左侧面板唯一允许绘制的主指标，防止 guardrail 混入同一坐标轴。"""


def _finite(value: object) -> float | None:
    """读取有限 CSV 浮点值。"""

    raw = str(value or "").strip()
    if not raw:
        return None
    value_float = float(raw)
    return value_float if math.isfinite(value_float) else None


def _paired_small(axis, rows: list[Mapping[str, str]], component: str) -> None:
    """绘制单组件 Full/Disabled 配对 segment 线和中位数粗线。"""

    metric_key = _COMPONENT_PLOT_METRICS[component]
    rows = [row for row in rows if str(row.get("metric_key") or "") == metric_key]
    if not rows:
        raise ValueError(f"实验二缺少组件主指标行：{component}/{metric_key}")
    full = [value for value in (_finite(row.get("full_value")) for row in rows) if value is not None]
    disabled = [value for value in (_finite(row.get("ablation_value")) for row in rows) if value is not None]
    if len(full) != len(disabled) or not full:
        raise ValueError(f"实验二组件配对不完整：{component}")
    for full_value, disabled_value in zip(full, disabled):
        axis.plot([0, 1], [full_value, disabled_value], marker="o", linewidth=0.9, alpha=0.40, markersize=3.5)
    axis.plot([0, 1], [np.median(full), np.median(disabled)], marker="D", linewidth=2.35, markersize=6.5)
    title, subtitle, ylabel = _COMPONENT_LABELS[component]
    axis.set_xticks([0, 1], ["Full", "Disabled"])
    axis.set_xlim(-0.20, 1.20)
    axis.set_ylim(bottom=0)
    axis.set_ylabel(ylabel)
    axis.set_title(title, fontweight="bold", pad=17, fontsize=10.8)
    axis.text(0.5, 1.01, subtitle, transform=axis.transAxes, ha="center", va="bottom", fontsize=7.9)
    delta_median = float(np.median(disabled) - np.median(full))
    axis.text(
        0.5,
        0.92,
        f"Disabled - Full = {delta_median:.3g} mm",
        transform=axis.transAxes,
        ha="center",
        va="top",
        fontsize=7.5,
    )
    if component == "vcd_admission":
        full_tail = sum(value > 40.0 for value in full)
        disabled_tail = sum(value > 40.0 for value in disabled)
        axis.text(
            0.5,
            0.84,
            f">40 mm: {full_tail}/{len(full)} vs {disabled_tail}/{len(disabled)}",
            transform=axis.transAxes,
            ha="center",
            va="top",
            fontsize=7.5,
            color="#555555",
        )
    axis.grid(axis="y", linestyle=":", linewidth=0.75, alpha=0.35)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)


def _synthesis_tradeoff(axis, rows: Sequence[Mapping[str, str]]) -> None:
    """绘制时序合成 Full/Disabled 的 lag--RMSE 配对权衡。"""

    grouped: dict[tuple[str, str, str, str], dict[str, Mapping[str, str]]] = defaultdict(dict)
    for row in rows:
        if row.get("component_id") != "temporal_synthesis":
            continue
        key = (str(row.get("session_id") or ""), str(row.get("trial_id") or ""), str(row.get("event_id") or ""), str(row.get("scenario_id") or ""))
        grouped[key][str(row.get("metric_key") or "")] = row
    points: list[tuple[float, float, float, float]] = []
    for metric_rows in grouped.values():
        lag = metric_rows.get("effective_translation_lag_ms")
        residual = metric_rows.get("translation_lag_residual_mm")
        if lag is None or residual is None:
            continue
        full_lag = _finite(lag.get("full_value"))
        disabled_lag = _finite(lag.get("ablation_value"))
        full_residual = _finite(residual.get("full_value"))
        disabled_residual = _finite(residual.get("ablation_value"))
        if None not in {full_lag, disabled_lag, full_residual, disabled_residual}:
            assert full_lag is not None and disabled_lag is not None
            assert full_residual is not None and disabled_residual is not None
            points.append((full_lag, full_residual, disabled_lag, disabled_residual))
    if not points:
        raise ValueError("实验二缺少时序合成 lag--RMSE 配对点")
    point_array = np.asarray(points, dtype=float)
    for full_lag, full_residual, disabled_lag, disabled_residual in point_array:
        axis.plot([full_lag, disabled_lag], [full_residual, disabled_residual], linewidth=0.82, alpha=0.26)
    axis.scatter(point_array[:, 0], point_array[:, 1], marker="D", s=27, alpha=0.48, label="Full")
    axis.scatter(point_array[:, 2], point_array[:, 3], marker="X", s=34, alpha=0.48, label="Synthesis disabled")
    axis.scatter(np.median(point_array[:, 0]), np.median(point_array[:, 1]), marker="D", s=95, color="#2878B5")
    axis.scatter(np.median(point_array[:, 2]), np.median(point_array[:, 3]), marker="X", s=110, color="#D62728")
    axis.set_xlabel("Effective lag (ms)")
    axis.set_ylabel("Lag-aligned translation RMSE (mm)")
    axis.set_title("(b) Temporal synthesis trade-off", loc="left", fontweight="bold", pad=17)
    axis.text(0.0, 1.01, "Additional delay buys a more faithful continuous trajectory", transform=axis.transAxes, ha="left", va="bottom", fontsize=8.6)
    axis.annotate("better", xy=(0.07, 0.08), xytext=(0.25, 0.24), xycoords="axes fraction", textcoords="axes fraction", arrowprops={"arrowstyle": "->", "linewidth": 0.9})
    axis.grid(axis="both", linestyle=":", linewidth=0.75, alpha=0.35)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.legend(frameon=False, loc="upper right")


def publish_exp2(specs: Mapping[str, PlotSpec], output_root) -> dict[str, tuple[str, str]]:
    """发布 GPT final v2 实验二合并图。"""

    rows = list(specs["exp2_mechanism_attribution"].rows)
    grouped: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("component_id") or "")].append(row)
    figure = plt.figure(figsize=(12.0, 3.85))
    outer = figure.add_gridspec(1, 2, width_ratios=[1.68, 1.0], wspace=0.30)
    left = outer[0].subgridspec(1, 3, wspace=0.42)
    for index, component in enumerate(_COMPONENT_ORDER):
        _paired_small(figure.add_subplot(left[0, index]), grouped.get(component, []), component)
    _synthesis_tradeoff(figure.add_subplot(outer[0, 1]), rows)
    figure.text(0.012, 0.985, "(a) Targeted component effects", ha="left", va="top", fontweight="bold", fontsize=12.3)
    figure.subplots_adjust(left=0.055, right=0.99, top=0.80, bottom=0.20)
    return {"exp2_merged_final_v2": save_figure_pair(figure, output_root, "exp2_merged_final_v2")}


__all__ = ["publish_exp2"]

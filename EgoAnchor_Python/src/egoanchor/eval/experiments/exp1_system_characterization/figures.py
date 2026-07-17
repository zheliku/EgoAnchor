"""实验一的 IEEE VR 论文 PDF 图表生成器。

四张图共享 ``egoanchor.eval.figure_style`` 的语义配色与基元：
- ``exp1_system_summary``：按场景的指标网格，替代旧的跨场景混池条形图；
- ``exp1_static_timeline``：静止头动的时间线 + 分布 glyph + 抖动条三面板；
- ``exp1_motion_timeline``：起停 6DoF 的时间线 + 转换标注 + 尾部分布；
- ``exp1_occlusion_recovery``：遮挡恢复的时间线 + 遮挡区间阴影 + 尾部/跳变。

绘图只消费分析层公开表和原始 render 长表，不重算 QC，也不跨场景聚合。
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

from egoanchor.eval import figure_style as fs

from .contract import VARIANTS
from .metrics import (
    SCENARIO_ORDER,
    build_scenario_headline,
    extract_timeline_series,
    occlusion_intervals,
)


def write_exp1_figures(
    render: pd.DataFrame,
    tables: Mapping[str, pd.DataFrame],
    output_dir: str | Path,
) -> list[Path]:
    """按固定契约生成四个实验一 PDF，返回写出的文件路径。"""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    headline = build_scenario_headline(dict(tables))
    events = _events_from_tables(tables)

    # 返回顺序与 OUTPUT_FIGURES 契约一致：三条时间线在前，系统汇总网格在后。
    paths = [
        _write_static_timeline(render, events, headline, output / "exp1_static_timeline.pdf"),
        _write_motion_timeline(render, events, headline, output / "exp1_motion_timeline.pdf"),
        _write_occlusion_recovery(render, events, headline, output / "exp1_occlusion_recovery.pdf"),
        _write_system_summary(headline, output / "exp1_system_summary.pdf"),
    ]
    return paths


# ---------------------------------------------------------------------------
# 图一：按场景的系统行为网格。
# ---------------------------------------------------------------------------

_SUMMARY_METRICS = (
    ("translation_median_mm", "Translation median (mm)", 1.0),
    ("translation_p95_mm", "Translation P95 (mm)", 1.0),
    ("position_hp_rms_mm", "Static jitter HP-RMS (mm)", 1.0),
)
"""网格三列：中心误差、尾部误差、静止抖动，覆盖 EgoAnchor 的核心权衡。"""


def _write_system_summary(headline: pd.DataFrame, path: Path) -> Path:
    """绘制 5 场景 × 3 指标的分组条形网格，如实展示逐场景权衡。"""

    fs.apply_paper_style()
    import matplotlib.pyplot as plt

    scenarios = list(SCENARIO_ORDER)
    figure, axes = plt.subplots(
        len(scenarios),
        len(_SUMMARY_METRICS),
        figsize=(fs.TEXT_WIDTH_IN, 1.35 * len(scenarios)),
        squeeze=False,
    )
    bar_width = 0.7
    positions = np.arange(len(VARIANTS))
    for row, scenario in enumerate(scenarios):
        scenario_rows = headline.loc[headline["scenario_id"].astype(str).eq(scenario)]
        for column, (metric, metric_label, scale) in enumerate(_SUMMARY_METRICS):
            axes_cell = axes[row][column]
            fs.style_axes(axes_cell)
            values = [
                _headline_value(scenario_rows, variant, metric) * scale for variant in VARIANTS
            ]
            best_index = _best_variant_index(values)
            for index, (variant, value) in enumerate(zip(VARIANTS, values, strict=True)):
                axes_cell.bar(
                    index,
                    0.0 if not np.isfinite(value) else value,
                    width=bar_width,
                    color=fs.variant_color(variant),
                    edgecolor="#2A2A2A" if index == best_index else "none",
                    linewidth=0.8 if index == best_index else 0.0,
                    zorder=3,
                )
            _annotate_bars(axes_cell, values)
            axes_cell.set_xticks(positions)
            if row == len(scenarios) - 1:
                axes_cell.set_xticklabels(
                    [fs.VARIANT_SHORT[variant] for variant in VARIANTS],
                    rotation=20,
                    ha="right",
                )
            else:
                axes_cell.set_xticklabels([])
            if row == 0:
                axes_cell.set_title(metric_label, fontsize=8.0, pad=6.0)
            if column == 0:
                axes_cell.set_ylabel(
                    fs.SCENARIO_TITLE.get(scenario, scenario),
                    fontsize=7.5,
                )
            axes_cell.margins(x=0.06)

    fs.variant_legend(figure, VARIANTS, kind="variant", y=1.008)
    figure.tight_layout(rect=(0.0, 0.0, 1.0, 0.975), h_pad=0.7, w_pad=1.2)
    return fs.save_figure(figure, path)


# ---------------------------------------------------------------------------
# 图二/三/四：时间线 + 分布 + 场景关键指标的三面板复合图。
# ---------------------------------------------------------------------------


def _write_static_timeline(
    render: pd.DataFrame,
    events: pd.DataFrame,
    headline: pd.DataFrame,
    path: Path,
) -> Path:
    """静止头动：逐帧误差时间线 + 分布 glyph + 静止抖动条。"""

    return _write_composite_timeline(
        render,
        events,
        headline,
        path,
        scenario="static_head_motion",
        panel_c_metric="position_hp_rms_mm",
        panel_c_label="Static jitter\nHP-RMS (mm)",
        marker_roles=("generic_marker",),
        occlusion=False,
    )


def _write_motion_timeline(
    render: pd.DataFrame,
    events: pd.DataFrame,
    headline: pd.DataFrame,
    path: Path,
) -> Path:
    """起停 6DoF：逐帧误差时间线 + 转换标注 + 尾部 P95 分布。"""

    return _write_composite_timeline(
        render,
        events,
        headline,
        path,
        scenario="start_stop_6dof",
        panel_c_metric="translation_p95_mm",
        panel_c_label="Translation\nP95 (mm)",
        marker_roles=("transition_started",),
        occlusion=False,
    )


def _write_occlusion_recovery(
    render: pd.DataFrame,
    events: pd.DataFrame,
    headline: pd.DataFrame,
    path: Path,
) -> Path:
    """遮挡恢复：逐帧误差时间线 + 遮挡区间阴影 + 尾部 P95 分布。"""

    return _write_composite_timeline(
        render,
        events,
        headline,
        path,
        scenario="occlusion_recovery",
        panel_c_metric="translation_p95_mm",
        panel_c_label="Translation\nP95 (mm)",
        marker_roles=(),
        occlusion=True,
    )


def _write_composite_timeline(
    render: pd.DataFrame,
    events: pd.DataFrame,
    headline: pd.DataFrame,
    path: Path,
    *,
    scenario: str,
    panel_c_metric: str,
    panel_c_label: str,
    marker_roles: tuple[str, ...],
    occlusion: bool,
) -> Path:
    """通用三面板时间线图，供静止/起停/遮挡场景复用。

    Panel A 为主时间线（占宽），Panel B 为分布 glyph，Panel C 为场景关键指标条。
    版式对标示例金标准图，但把面板标号放到坐标轴外侧，避免压住子图标题。
    """

    fs.apply_paper_style()
    import matplotlib.pyplot as plt

    figure = plt.figure(figsize=(fs.TEXT_WIDTH_IN, 2.5))
    grid = figure.add_gridspec(1, 3, width_ratios=(3.1, 1.0, 1.0), wspace=0.42)
    axes_time = figure.add_subplot(grid[0, 0])
    axes_dist = figure.add_subplot(grid[0, 1])
    axes_bar = figure.add_subplot(grid[0, 2])
    for axes in (axes_time, axes_dist, axes_bar):
        fs.style_axes(axes)

    series = extract_timeline_series(render, scenario)
    trial_id = series["trial_id"]
    t0 = series["t0_ms"]

    # Panel A：逐帧显示误差时间线。
    if occlusion:
        fs.shade_intervals(
            axes_time,
            occlusion_intervals(events, trial_id, t0),
            label="Occluded",
        )
    elif marker_roles:
        from .metrics import extract_event_times

        annotations = extract_event_times(events, scenario, trial_id, t0, roles=marker_roles)
        marker_times = [value for values in annotations.values() for value in values]
        fs.event_markers(axes_time, marker_times)

    plotted = False
    for variant in VARIANTS:
        time_axis = series["time_s"].get(variant, np.empty(0))
        error_axis = series["translation_mm"].get(variant, np.empty(0))
        if time_axis.size == 0:
            continue
        style = fs.variant_style(variant)
        axes_time.plot(
            time_axis,
            error_axis,
            color=style.color,
            linestyle=style.linestyle,
            linewidth=style.linewidth,
            zorder=style.zorder,
            solid_capstyle="round",
        )
        plotted = True
    axes_time.set_xlabel("Time in trial (s)")
    axes_time.set_ylabel("Translation error (mm)")
    fs.panel_label(axes_time, "A")
    if not plotted:
        axes_time.text(0.5, 0.5, "No render series", transform=axes_time.transAxes, ha="center")

    # Panel B：该场景 4 配置的误差分布 glyph（median/IQR/P5–P95）。
    _draw_distribution_panel(axes_dist, render, scenario)
    fs.panel_label(axes_dist, "B")

    # Panel C：场景关键标量条。
    scenario_rows = headline.loc[headline["scenario_id"].astype(str).eq(scenario)]
    values = [_headline_value(scenario_rows, variant, panel_c_metric) for variant in VARIANTS]
    best_index = _best_variant_index(values)
    for index, (variant, value) in enumerate(zip(VARIANTS, values, strict=True)):
        axes_bar.bar(
            index,
            0.0 if not np.isfinite(value) else value,
            width=0.7,
            color=fs.variant_color(variant),
            edgecolor="#2A2A2A" if index == best_index else "none",
            linewidth=0.8 if index == best_index else 0.0,
            zorder=3,
        )
    _annotate_bars(axes_bar, values)
    axes_bar.set_xticks(range(len(VARIANTS)))
    axes_bar.set_xticklabels(
        [fs.VARIANT_SHORT[variant] for variant in VARIANTS], rotation=20, ha="right"
    )
    axes_bar.set_ylabel(panel_c_label, fontsize=7.0)
    fs.panel_label(axes_bar, "C")

    fs.variant_legend(figure, VARIANTS, kind="line", y=1.02)
    figure.subplots_adjust(left=0.07, right=0.99, top=0.88, bottom=0.22)
    return fs.save_figure(figure, path)


def _draw_distribution_panel(axes, render: pd.DataFrame, scenario: str) -> None:
    """在 Panel B 用分布 glyph 展示该场景内各配置的逐帧误差分布。"""

    from egoanchor.eval.metrics import pose_error

    scenario_rows = (
        render.loc[render["scenario_id"].astype(str).eq(scenario)]
        if not render.empty and "scenario_id" in render.columns
        else render.iloc[0:0]
    )
    for index, variant in enumerate(VARIANTS):
        variant_rows = scenario_rows.loc[
            scenario_rows["variant_label"].astype(str).eq(variant)
        ] if not scenario_rows.empty else scenario_rows
        errors: list[float] = []
        for _, row in variant_rows.iterrows():
            if not bool(row.get("reference_pose_valid")) or not bool(row.get("has_display_pose")):
                continue
            if row.get("reference_pos") is None or row.get("display_pos") is None:
                continue
            translation_m, _ = pose_error(
                row["reference_pos"], row["reference_rot"], row["display_pos"], row["display_rot"]
            )
            errors.append(translation_m * 1000.0)
        if not errors:
            continue
        data = np.asarray(errors, dtype=float)
        fs.distribution_glyph(
            axes,
            index,
            median=float(np.median(data)),
            q1=float(np.percentile(data, 25)),
            q3=float(np.percentile(data, 75)),
            p95=float(np.percentile(data, 95)),
            p5=float(np.percentile(data, 5)),
            color=fs.variant_color(variant),
        )
    axes.set_xticks(range(len(VARIANTS)))
    axes.set_xticklabels(
        [fs.VARIANT_SHORT[variant] for variant in VARIANTS], rotation=20, ha="right"
    )
    axes.set_ylabel("Translation error (mm)", fontsize=7.0)


# ---------------------------------------------------------------------------
# 共享小工具。
# ---------------------------------------------------------------------------


def _headline_value(scenario_rows: pd.DataFrame, variant: str, metric: str) -> float:
    """从场景切片读取一个配置的展示指标；缺失返回 NaN。"""

    if scenario_rows.empty or metric not in scenario_rows.columns:
        return np.nan
    selected = pd.to_numeric(
        scenario_rows.loc[scenario_rows["variant_label"].astype(str).eq(variant), metric],
        errors="coerce",
    ).dropna()
    return float(selected.iloc[0]) if not selected.empty else np.nan


def _best_variant_index(values: list[float]) -> int:
    """返回最小（最优）有限值的下标，用于高亮胜出配置；无有限值返回 -1。"""

    finite = [(index, value) for index, value in enumerate(values) if np.isfinite(value)]
    if not finite:
        return -1
    return min(finite, key=lambda item: item[1])[0]


def _annotate_bars(axes, values: list[float]) -> None:
    """在每根柱顶标注数值，保留两位有效小数，缺失写 ``--``。"""

    finite = [value for value in values if np.isfinite(value)]
    ceiling = max(finite) if finite else 1.0
    axes.set_ylim(0.0, ceiling * 1.28 if ceiling > 0 else 1.0)
    for index, value in enumerate(values):
        text = "--" if not np.isfinite(value) else (f"{value:.2f}" if value < 10 else f"{value:.1f}")
        height = 0.0 if not np.isfinite(value) else value
        axes.annotate(
            text,
            xy=(index, height),
            xytext=(0.0, 2.0),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=6.2,
            color="#333333",
        )


def _events_from_tables(tables: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """从分析产物获取事件表；当前分析层不下传 events 时返回空表。"""

    events = tables.get("events")
    if isinstance(events, pd.DataFrame):
        return events
    return pd.DataFrame(
        columns=["scenario_id", "trial_id", "event_type", "mono_ms", "payload"]
    )


__all__ = ["write_exp1_figures"]

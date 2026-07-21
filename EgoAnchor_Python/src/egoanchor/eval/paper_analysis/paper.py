"""实验一/二表格、绘图数据和中文主稿物化。"""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
from openpyxl import Workbook, load_workbook  # type: ignore[import-untyped]
from openpyxl.styles import Alignment, Font, PatternFill  # type: ignore[import-untyped]
from openpyxl.utils import get_column_letter  # type: ignore[import-untyped]

from .metrics import (
    FULL_VARIANT,
    HERMITE_VARIANT,
    METHODS,
    NO_STATIC_LOCK,
    NO_TEMPORAL_SYNTHESIS,
    NO_VCD,
    PaperResults,
    paired_metric_matrix,
    segment_identity,
)
from .settings import DEFAULT_SETTINGS_PATH, settings_sha256


def _fmt(value: float, digits: int = 3) -> str:
    """按论文表格习惯格式化有限数值。"""

    if not np.isfinite(value):
        return "--"
    return f"{value:.{digits}f}".rstrip("0").rstrip(".")


def _summary(rows: tuple[Mapping[str, Any], ...], key: str) -> tuple[float, float, float]:
    """返回片段值的 median、Q1 和 Q3。"""

    values = np.asarray([float(row[key]) for row in rows], dtype=float)
    values = values[np.isfinite(values)]
    if values.size == 0:
        raise ValueError(f"论文表缺少指标：{key}")
    return tuple(float(item) for item in np.quantile(values, (0.5, 0.25, 0.75)))  # type: ignore[return-value]


def _cell(summary: tuple[float, float, float], digits: int = 3) -> str:
    """写出 ``median [Q1, Q3]`` 读者表格单元格。"""

    median, q1, q3 = summary
    return f"{_fmt(median, digits)} [{_fmt(q1, digits)}, {_fmt(q3, digits)}]"


def _bold_median(cell: str) -> str:
    """只加粗 median，保留同一单元格中的四分位区间。"""

    median, interval = cell.split(" ", 1)
    return rf"\textbf{{{median}}} {interval}"


def _bold_value(value: str) -> str:
    """加粗不带区间的标量表格值。"""

    return rf"\textbf{{{value}}}"


def _sample_label(
    rows: Mapping[str, tuple[Mapping[str, Any], ...]],
    key: str,
    variants: tuple[str, ...] = METHODS,
) -> str:
    """生成不掩盖配置间缺失差异的样本量标签。"""

    counts = [
        sum(np.isfinite(float(row[key])) for row in rows.get(variant, ()))
        for variant in variants
    ]
    if min(counts) == max(counts):
        return f"n={counts[0]}"
    return f"n={min(counts)}--{max(counts)}"


def _exp1_table(results: PaperResults) -> str:
    """生成实验一八指标表。"""

    lines = [
        r"\begin{table*}[t]",
        r"\centering",
        r"\caption{新采集数据上的完整系统表征。连续指标报告重复动作片段或遮挡过程之间的 median [Q1, Q3]；指标名称中的 P95 先在每个片段内部对渲染帧计算，再在片段之间汇总。粗体标记每个数值列的最优中位数；绝对注册是护栏，平移与旋转的 lag / aligned RMSE 必须成对解释，Start-transition 是稳定优先策略的转换代价。}",
        r"\label{tab:exp1-final}",
        r"\scriptsize",
        r"\setlength{\tabcolsep}{2.1pt}",
        r"\renewcommand{\arraystretch}{1.18}",
        r"\resizebox{\textwidth}{!}{%",
        r"\begin{tabular}{lcccccccc}",
        r"\toprule",
        "& \\multicolumn{2}{c}{世界一致性} & 静止稳定性 & \\multicolumn{2}{c}{动态保真度} & \\multicolumn{2}{c}{失效控制} & 转换代价 \\\\",
        r"\cmidrule(lr){2-3}\cmidrule(lr){4-4}\cmidrule(lr){5-6}\cmidrule(lr){7-8}\cmidrule(lr){9-9}",
        "方法 & 头动泄漏 P95 $\\downarrow$ & 绝对注册 P95 $\\downarrow$ & 帧间增量 P95 $\\downarrow$ & 平移 Lag / RMSE & 旋转 Lag / RMSE & 遮挡 P95 $\\downarrow$ & $>40$~mm $\\downarrow$ & Start-transition $\\downarrow$ \\\\",
        "& (mm) & (mm) & (mm) & (ms / mm) & (ms / deg) & (mm) & (次数) & (ms) \\\\",
        f"& ${_sample_label(results.static_segments, 'centered_p95_mm')}$ & ${_sample_label(results.static_segments, 'absolute_p95_mm')}$ & ${_sample_label(results.static_segments, 'frame_increment_p95_mm')}$ & ${_sample_label(results.translation_segments, 'aligned_rmse_mm')}$ & ${_sample_label(results.rotation_segments, 'aligned_rmse_deg')}$ & ${_sample_label(results.occlusion_episodes, 'translation_p95_mm')}$ & $k/{len(results.occlusion_episodes[METHODS[0]])}$ & ${_sample_label(results.transition_segments, 'response_ms')}$ \\\\",
        r"\midrule",
    ]
    medians: dict[str, dict[str, float]] = {
        "centered": {method: _summary(results.static_segments[method], "centered_p95_mm")[0] for method in METHODS},
        "absolute": {method: _summary(results.static_segments[method], "absolute_p95_mm")[0] for method in METHODS},
        "increment": {method: _summary(results.static_segments[method], "frame_increment_p95_mm")[0] for method in METHODS},
        "translation_lag": {method: _summary(results.translation_segments[method], "effective_lag_ms")[0] for method in METHODS},
        "translation_rmse": {method: _summary(results.translation_segments[method], "aligned_rmse_mm")[0] for method in METHODS},
        "rotation_lag": {method: _summary(results.rotation_segments[method], "effective_lag_ms")[0] for method in METHODS},
        "rotation_rmse": {method: _summary(results.rotation_segments[method], "aligned_rmse_deg")[0] for method in METHODS},
        "occlusion": {method: _summary(results.occlusion_episodes[method], "translation_p95_mm")[0] for method in METHODS},
        "failures": {method: sum(bool(row["catastrophic_gt40"]) for row in results.occlusion_episodes[method]) for method in METHODS},
        "start": {method: _summary(results.transition_segments[method], "response_ms")[0] for method in METHODS},
    }
    best: dict[str, float] = {key: min(values.values()) for key, values in medians.items()}
    for method in METHODS:
        static = results.static_segments[method]
        translation = results.translation_segments[method]
        rotation = results.rotation_segments[method]
        occlusion = results.occlusion_episodes[method]
        transition = results.transition_segments[method]
        centered = _cell(_summary(static, "centered_p95_mm"))
        absolute = _cell(_summary(static, "absolute_p95_mm"))
        increment = _cell(_summary(static, "frame_increment_p95_mm"))
        lag = _summary(translation, "effective_lag_ms")[0]
        residual = _fmt(_summary(translation, "aligned_rmse_mm")[0])
        rotation_lag, rotation_residual = _summary(rotation, "effective_lag_ms")[0], _summary(rotation, "aligned_rmse_deg")[0]
        occlusion_p95 = _cell(_summary(occlusion, "translation_p95_mm"))
        failures = sum(bool(row["catastrophic_gt40"]) for row in occlusion)
        start = _cell(_summary(transition, "response_ms"), 1)
        if np.isclose(medians["centered"][method], best["centered"]):
            centered = _bold_median(centered)
        if np.isclose(medians["absolute"][method], best["absolute"]):
            absolute = _bold_median(absolute)
        if np.isclose(medians["increment"][method], best["increment"]):
            increment = _bold_median(increment)
        lag_text = _fmt(lag, 1)
        if np.isclose(medians["translation_lag"][method], best["translation_lag"]):
            lag_text = _bold_value(lag_text)
        if np.isclose(medians["translation_rmse"][method], best["translation_rmse"]):
            residual = _bold_value(residual)
        rotation_lag_text = _fmt(rotation_lag, 1)
        if np.isclose(medians["rotation_lag"][method], best["rotation_lag"]):
            rotation_lag_text = _bold_value(rotation_lag_text)
        rotation_residual_text = _fmt(rotation_residual)
        if np.isclose(medians["rotation_rmse"][method], best["rotation_rmse"]):
            rotation_residual_text = _bold_value(rotation_residual_text)
        if np.isclose(medians["occlusion"][method], best["occlusion"]):
            occlusion_p95 = _bold_median(occlusion_p95)
        failure_text = f"{failures}/{len(occlusion)}"
        if np.isclose(medians["failures"][method], best["failures"]):
            failure_text = _bold_value(failure_text)
        if np.isclose(medians["start"][method], best["start"]):
            start = _bold_median(start)
        lines.append(
            f"{method} & {centered} & {absolute} & {increment} & {lag_text} / {residual} & {rotation_lag_text} / {rotation_residual_text} & {occlusion_p95} & {failure_text} & {start} " + r"\\"
        )
    lines.extend([r"\bottomrule", r"\end{tabular}%", r"}", r"\end{table*}"])
    return "\n".join(lines)


def _paired_summary(
    rows: Mapping[str, tuple[Mapping[str, Any], ...]],
    disabled_variant: str,
    key: str,
) -> tuple[float, float, float, float]:
    """返回 Full、Disabled 和配对差值的中位数，以及差值方向一致数。"""

    matrix = paired_metric_matrix(rows, (FULL_VARIANT, disabled_variant), (key,))[:, :, 0]
    full = matrix[:, 0]
    disabled = matrix[:, 1]
    deltas = disabled - full
    return (
        float(np.median(full)),
        float(np.median(disabled)),
        float(np.median(deltas)),
        float(np.sum(deltas > 0)),
    )


def _exp2_table(results: PaperResults) -> str:
    """生成实验二四组件归因表。"""

    capture = np.asarray([float(row["capture_p95_mm"]) for row in results.capture_alignment])
    arrival = np.asarray([float(row["arrival_p95_mm"]) for row in results.capture_alignment])
    capture_text = f"{_fmt(float(np.median(capture)))} [{_fmt(float(np.quantile(capture, .25)))}, {_fmt(float(np.quantile(capture, .75)))}]"
    arrival_text = f"{_fmt(float(np.median(arrival)))} [{_fmt(float(np.quantile(arrival, .25)))}, {_fmt(float(np.quantile(arrival, .75)))}]"
    reduction = arrival - capture
    capture_effect = f"+{_fmt(float(np.median(reduction)))} [{_fmt(float(np.quantile(reduction, .25)))}, {_fmt(float(np.quantile(reduction, .75)))}]~mm; {int(np.sum(reduction > 0))}/{len(reduction)} 改善"
    full_static, disabled_static, static_delta, static_positive = _paired_summary(results.static_segments, NO_STATIC_LOCK, "centered_p95_mm")
    linear_lag, predict_lag, lag_delta, _ = _paired_summary(
        results.translation_segments,
        NO_TEMPORAL_SYNTHESIS,
        "effective_lag_ms",
    )
    linear_rmse, predict_rmse, rmse_delta, _ = _paired_summary(
        results.translation_segments,
        NO_TEMPORAL_SYNTHESIS,
        "aligned_rmse_mm",
    )
    linear_translation, hermite_translation, hermite_translation_delta, linear_translation_better = _paired_summary(
        results.translation_segments,
        HERMITE_VARIANT,
        "aligned_rmse_mm",
    )
    linear_rotation, hermite_rotation, hermite_rotation_delta, linear_rotation_better = _paired_summary(
        results.rotation_segments,
        HERMITE_VARIANT,
        "aligned_rmse_deg",
    )
    vcd_full = results.occlusion_episodes[FULL_VARIANT]
    vcd_disabled = results.occlusion_episodes[NO_VCD]
    full_failures = sum(bool(row["catastrophic_gt40"]) for row in vcd_full)
    disabled_failures = sum(bool(row["catastrophic_gt40"]) for row in vcd_disabled)
    lines = [
        r"\begin{table*}[t]",
        r"\centering",
        r"\caption{新数据上的目标化组件比较与插值器选择。稳定配置 ID EgoAnchor 及三个组件对照均采用 Kalman Linear/SLERP；效应为替代配置减完整系统。Hermite 仅作为相同状态估计与目标时间下的插值器对照。}",
        r"\label{tab:exp2-final}",
        r"\small",
        r"\setlength{\tabcolsep}{4.8pt}",
        r"\resizebox{\textwidth}{!}{%",
        r"\begin{tabular}{lllll}",
        r"\toprule",
        "组件 & 直接指标 & 启用 & 关闭 / 替代 & 效应 \\\\",
        r"\midrule",
        f"采集时刻对齐 & 同一候选的复合 P95 & {capture_text}~mm & {arrival_text}~mm & {capture_effect} \\\\",
        f"StaticLock & 中心化静止 P95 & {_fmt(full_static)}~mm & {_fmt(disabled_static)}~mm & +{_fmt(static_delta)}~mm；{int(static_positive)}/{len(results.static_segments[FULL_VARIANT])} 片段变差 \\\\",
        f"VCD 接纳 & 遮挡 P95 $>40$~mm & {full_failures}/{len(vcd_full)}；max {_fmt(max(float(row['translation_p95_mm']) for row in vcd_full))}~mm & {disabled_failures}/{len(vcd_disabled)}；max {_fmt(max(float(row['translation_p95_mm']) for row in vcd_disabled))}~mm & 消除本批次观测到的灾难性失效 \\\\",
        f"时序合成（实际 runtime） & fitted lag / aligned RMSE & {_fmt(linear_lag, 1)} / {_fmt(linear_rmse)} & {_fmt(predict_lag, 1)} / {_fmt(predict_rmse)} & {_fmt(lag_delta, 1)}~ms / +{_fmt(rmse_delta)}~mm \\\\",
        f"插值器选择 & 平移 / 旋转 aligned RMSE & {_fmt(linear_translation)}~mm / {_fmt(linear_rotation)}$^\\circ$ & {_fmt(hermite_translation)}~mm / {_fmt(hermite_rotation)}$^\\circ$ & Hermite--Linear: +{_fmt(hermite_translation_delta)}~mm / +{_fmt(hermite_rotation_delta)}$^\\circ$；{int(linear_translation_better)}/{len(results.translation_segments[FULL_VARIANT])}、{int(linear_rotation_better)}/{len(results.rotation_segments[FULL_VARIANT])} 个片段 Linear 更低 \\\\",
        r"\bottomrule",
        r"\end{tabular}%",
        r"}",
        r"\end{table*}",
    ]
    return "\n".join(lines)


def _exp1_text(results: PaperResults) -> str:
    """生成实验一正文。"""

    values = {
        "ego_centered": _summary(results.static_segments[FULL_VARIANT], "centered_p95_mm")[0],
        "arrival_centered": _summary(results.static_segments["Arrival-Hold"], "centered_p95_mm")[0],
        "capture_centered": _summary(results.static_segments["Capture-Hold"], "centered_p95_mm")[0],
        "one_euro_centered": _summary(results.static_segments["One-Euro Anchor"], "centered_p95_mm")[0],
        "ego_absolute": _summary(results.static_segments[FULL_VARIANT], "absolute_p95_mm")[0],
        "ego_increment": _summary(results.static_segments[FULL_VARIANT], "frame_increment_p95_mm")[0],
        "one_euro_increment": _summary(results.static_segments["One-Euro Anchor"], "frame_increment_p95_mm")[0],
        "ego_lag": _summary(results.translation_segments[FULL_VARIANT], "effective_lag_ms")[0],
        "ego_rmse": _summary(results.translation_segments[FULL_VARIANT], "aligned_rmse_mm")[0],
        "arrival_lag": _summary(results.translation_segments["Arrival-Hold"], "effective_lag_ms")[0],
        "arrival_rmse": _summary(results.translation_segments["Arrival-Hold"], "aligned_rmse_mm")[0],
        "one_euro_lag": _summary(results.translation_segments["One-Euro Anchor"], "effective_lag_ms")[0],
        "one_euro_rmse": _summary(results.translation_segments["One-Euro Anchor"], "aligned_rmse_mm")[0],
        "ego_rotation_lag": _summary(results.rotation_segments[FULL_VARIANT], "effective_lag_ms")[0],
        "ego_rotation_rmse": _summary(results.rotation_segments[FULL_VARIANT], "aligned_rmse_deg")[0],
        "one_euro_rotation_lag": _summary(results.rotation_segments["One-Euro Anchor"], "effective_lag_ms")[0],
        "one_euro_rotation_rmse": _summary(results.rotation_segments["One-Euro Anchor"], "aligned_rmse_deg")[0],
        "ego_occ": _summary(results.occlusion_episodes[FULL_VARIANT], "translation_p95_mm")[0],
        "one_euro_occ": _summary(results.occlusion_episodes["One-Euro Anchor"], "translation_p95_mm")[0],
        "ego_start": _summary(results.transition_segments[FULL_VARIANT], "response_ms")[0],
    }
    return f"""\\subsection{{实验一：应用侧锚点行为}}

实验一围绕五项应用可感知属性组织：\\emph{{world consistency}} 衡量主动头动是否被错误写入静止物体的世界位置；\\emph{{rest stability}} 衡量静止锚点的逐帧显示抖动；\\emph{{dynamic fidelity}} 将持续运动中的有效时延与时延对齐后的轨迹残差作为不可拆分的权衡；\\emph{{failure containment}} 衡量遮挡和坏观测是否破坏已建立锚点；\\emph{{transition cost}} 衡量稳定优先策略从静止锁定切换到可见运动跟随的代价。

{_exp1_table(results)}

\\textbf{{头动下的世界一致性与静止稳定性。}} 移除每个动作片段的固定注册偏置后，EgoAnchor 的中心化平移 P95 为 {_fmt(values['ego_centered'])}~mm，而 Arrival-Hold、Capture-Hold 与 One-Euro Anchor 分别为 {_fmt(values['arrival_centered'])}、{_fmt(values['capture_centered'])} 与 {_fmt(values['one_euro_centered'])}~mm。EgoAnchor 的绝对注册 P95 为 {_fmt(values['ego_absolute'])}~mm；其静止帧间位置增量 P95 为 {_fmt(values['ego_increment'])}~mm，One-Euro Anchor 为 {_fmt(values['one_euro_increment'])}~mm。

\\textbf{{持续运动中的时延--轨迹质量权衡。}} 持续平移中，EgoAnchor 的有效时延 / lag-aligned RMSE 为 {_fmt(values['ego_lag'], 1)}~ms / {_fmt(values['ego_rmse'])}~mm；Arrival-Hold 为 {_fmt(values['arrival_lag'], 1)}~ms / {_fmt(values['arrival_rmse'])}~mm，One-Euro Anchor 为 {_fmt(values['one_euro_lag'], 1)}~ms / {_fmt(values['one_euro_rmse'])}~mm。结果支持稳定优先的连续轨迹合成，而不是最低时延主张。

\\textbf{{持续旋转。}} EgoAnchor 的有效时延 / 对齐角 RMSE 为 {_fmt(values['ego_rotation_lag'], 1)}~ms / {_fmt(values['ego_rotation_rmse'])}$^\\circ$，One-Euro Anchor 为 {_fmt(values['one_euro_rotation_lag'], 1)}~ms / {_fmt(values['one_euro_rotation_rmse'])}$^\\circ$。旋转结果与平移结果分开报告，避免用位置通道的收益替代姿态通道证据；Hermite 与 Linear/SLERP 的直接比较在实验二的候选筛选中报告。

\\textbf{{遮挡期间的失效控制。}} 遮挡过程中，EgoAnchor 的 episode-level 平移 P95 中位数为 {_fmt(values['ego_occ'])}~mm，One-Euro Anchor 为 {_fmt(values['one_euro_occ'])}~mm。完整分布、40~mm 阈值超限率和最大值共同保留在图和审阅表中。

\\textbf{{起停转换代价。}} Start-transition response 使用片段前 250~ms 基线、5~mm 位移阈值和 100~ms 持续条件。EgoAnchor 的片段中位数为 {_fmt(values['ego_start'], 1)}~ms；该量包含 StaticLock 解锁证据、候选更新和延迟合成时间线，不是网络或视觉推理的原始时延。

\\begin{{figure*}}[t]
  \\centering
  \\begin{{subfigure}}[t]{{0.32\\textwidth}}
    \\centering
    \\includegraphics[width=\\linewidth]{{figures/panels/figure2a_head_motion.pdf}}
    \\caption{{头动下的中心化误差}}
    \\label{{fig:exp1-head-motion}}
  \\end{{subfigure}}\\hfill
  \\begin{{subfigure}}[t]{{0.32\\textwidth}}
    \\centering
    \\includegraphics[width=\\linewidth]{{figures/panels/figure2b_translation.pdf}}
    \\caption{{持续平移的时延与残差}}
    \\label{{fig:exp1-translation}}
  \\end{{subfigure}}\\hfill
  \\begin{{subfigure}}[t]{{0.32\\textwidth}}
    \\centering
    \\includegraphics[width=\\linewidth]{{figures/panels/figure2c_occlusion.pdf}}
    \\caption{{遮挡期间的平移误差}}
    \\label{{fig:exp1-occlusion}}
  \\end{{subfigure}}
  \\caption{{实验一的三项核心分布。小标记表示动作片段或遮挡过程，箱线给出中位数、四分位区间和全范围，实心标记表示中位数。图~(a) 和 (c) 的细线连接同一片段在不同方法下的结果；图~(b) 仅保留各方法散点及中位数/IQR，避免跨方法顺序造成视觉混淆。}}
  \\label{{fig:exp1-final}}
\\end{{figure*}}
"""


def _exp2_text(results: PaperResults) -> str:
    """生成实验二正文、表格和四面板图。"""

    capture = np.asarray([float(row["capture_p95_mm"]) for row in results.capture_alignment])
    arrival = np.asarray([float(row["arrival_p95_mm"]) for row in results.capture_alignment])
    reduction = arrival - capture
    full_static, disabled_static, static_delta, _ = _paired_summary(results.static_segments, NO_STATIC_LOCK, "centered_p95_mm")
    full_vcd = results.occlusion_episodes[FULL_VARIANT]
    disabled_vcd = results.occlusion_episodes[NO_VCD]
    linear_lag, predict_lag, lag_delta, _ = _paired_summary(
        results.translation_segments,
        NO_TEMPORAL_SYNTHESIS,
        "effective_lag_ms",
    )
    linear_rmse, predict_rmse, rmse_delta, _ = _paired_summary(
        results.translation_segments,
        NO_TEMPORAL_SYNTHESIS,
        "aligned_rmse_mm",
    )
    linear_translation, hermite_translation, hermite_translation_delta, linear_translation_better = _paired_summary(
        results.translation_segments,
        HERMITE_VARIANT,
        "aligned_rmse_mm",
    )
    linear_rotation, hermite_rotation, hermite_rotation_delta, linear_rotation_better = _paired_summary(
        results.rotation_segments,
        HERMITE_VARIANT,
        "aligned_rmse_deg",
    )
    _, _, candidate_lag_delta, _ = _paired_summary(
        results.translation_segments,
        HERMITE_VARIANT,
        "effective_lag_ms",
    )
    _, _, candidate_increment_delta, _ = _paired_summary(
        results.static_segments,
        HERMITE_VARIANT,
        "frame_increment_p95_mm",
    )
    _, _, candidate_response_delta, _ = _paired_summary(
        results.transition_segments,
        HERMITE_VARIANT,
        "response_ms",
    )
    return f"""\\subsection{{实验二：组件归因}}

实验二复用实验一的候选、参考轨迹和渲染时间线。原始日志完成策略身份统一后，稳定配置 ID EgoAnchor 及采集时刻对齐、VCD、StaticLock 三个组件对照均使用 Kalman Linear/SLERP；原完整 Hermite runtime 明确标记为 EgoAnchor Hermite，只用于插值器选择。采集时刻对齐比较同一原始候选在 capture-time 与 arrival-time 世界复合下的误差；StaticLock 使用中心化静止波动；VCD 使用超过 40~mm 的灾难性尾部失效率；时序合成比较 Kalman Linear/SLERP 与 Kalman Predict-to-Now runtime。

{_exp2_table(results)}

\\begin{{figure*}}[t]
  \\centering
  \\begin{{subfigure}}[t]{{0.18\\textwidth}}
    \\centering
    \\includegraphics[width=\\linewidth]{{figures/panels/figure3a_capture_alignment.pdf}}
    \\caption{{采集时刻对齐}}
    \\label{{fig:exp2-alignment}}
  \\end{{subfigure}}\\hfill
  \\begin{{subfigure}}[t]{{0.18\\textwidth}}
    \\centering
    \\includegraphics[width=\\linewidth]{{figures/panels/figure3b_static_lock.pdf}}
    \\caption{{StaticLock}}
    \\label{{fig:exp2-static-lock}}
  \\end{{subfigure}}\\hfill
  \\begin{{subfigure}}[t]{{0.18\\textwidth}}
    \\centering
    \\includegraphics[width=\\linewidth]{{figures/panels/figure3c_vcd.pdf}}
    \\caption{{VCD 接纳}}
    \\label{{fig:exp2-vcd}}
  \\end{{subfigure}}\\hfill
  \\begin{{subfigure}}[t]{{0.40\\textwidth}}
    \\centering
    \\includegraphics[width=\\linewidth]{{figures/panels/figure3d_temporal_strategies.pdf}}
    \\caption{{时序策略}}
    \\label{{fig:exp2-temporal}}
  \\end{{subfigure}}
  \\caption{{实验二的组件归因与插值器比较。图~(a)--(c) 分别比较采集时刻复合、StaticLock 和 VCD；图~(d) 比较本批次同步运行的 Kalman Predict-to-Now、Kalman Hermite 与 Kalman Linear/SLERP。细线只连接同一事件或片段的严格配对结果。}}
  \\label{{fig:exp2-final}}
\\end{{figure*}}

\\textbf{{采集时刻对齐。}} 对同一批原始候选直接应用两种世界复合后，片段级 candidate P95 由 arrival-time 的 {_fmt(float(np.median(arrival)))}~mm 降至 capture-time 的 {_fmt(float(np.median(capture)))}~mm；{int(np.sum(reduction > 0))}/{len(reduction)} 个片段改善，配对中位降幅为 {_fmt(float(np.median(reduction)))}~mm。

\\textbf{{StaticLock。}} 关闭 StaticLock 后，中心化静止 P95 从 {_fmt(full_static)} 增至 {_fmt(disabled_static)}~mm，配对差值为 +{_fmt(static_delta)}~mm。该结果表明 StaticLock 限制慢速静止漂移，而逐帧增量仍作为表格护栏报告。

\\textbf{{VCD 接纳。}} 启用 VCD 时，{sum(bool(row['catastrophic_gt40']) for row in full_vcd)}/{len(full_vcd)} 次遮挡过程超过 40~mm；关闭后为 {sum(bool(row['catastrophic_gt40']) for row in disabled_vcd)}/{len(disabled_vcd)}。该组件的主证据是尾部失效率，不是单独的中位数。

\\textbf{{时序合成。}} Kalman Predict-to-Now 的 fitted lag / lag-aligned RMSE 为 {_fmt(predict_lag, 1)}~ms / {_fmt(predict_rmse)}~mm，正式 Kalman Linear/SLERP 为 {_fmt(linear_lag, 1)}~ms / {_fmt(linear_rmse)}~mm。Predict-to-Now 的配对时延变化为 {_fmt(lag_delta, 1)}~ms，但对齐残差增加 {_fmt(rmse_delta)}~mm；这表明自适应历史目标时刻主要用于换取轨迹保真度，而不是降低显示延迟。Hermite 作为相同模型、接纳、目标时间与生命周期下的插值器对照单独报告。

\\textbf{{插值器选择。}} 在模型、VCD、StaticLock、自适应目标时间和生命周期均相同的条件下，Linear/SLERP 的平移 aligned RMSE 为 {_fmt(linear_translation)}~mm，Hermite 为 {_fmt(hermite_translation)}~mm，Hermite--Linear 配对中位差为 +{_fmt(hermite_translation_delta)}~mm，{int(linear_translation_better)}/{len(results.translation_segments[FULL_VARIANT])} 个片段中 Linear 更低；两者的旋转 aligned RMSE 分别为 {_fmt(linear_rotation)}$^\\circ$ 与 {_fmt(hermite_rotation)}$^\\circ$，差值为 +{_fmt(hermite_rotation_delta)}$^\\circ$，{int(linear_rotation_better)}/{len(results.rotation_segments[FULL_VARIANT])} 个片段中 Linear 更低。Hermite 相对 Linear 的平移时延、静止帧间增量和起停响应配对中位变化分别为 {_fmt(candidate_lag_delta, 1)}~ms、{_fmt(candidate_increment_delta)}~mm 和 {_fmt(candidate_response_delta, 1)}~ms。二者在这些护栏上没有可见差异，而 Linear/SLERP 的残差略低，因此本文将 Linear/SLERP 冻结为 EgoAnchor 的正式输出策略。

"""


def _replace_block(text: str, start: str, end: str, replacement: str) -> str:
    """按章节边界替换主稿中的实验块。"""

    pattern = re.compile(re.escape(start) + r".*?(?=" + re.escape(end) + r")", re.S)
    updated, count = pattern.subn(lambda _match: replacement.rstrip() + "\n\n", text, count=1)
    if count != 1:
        raise ValueError(f"主稿缺少章节边界：{start} -> {end}")
    return updated


def _write_strategy_candidate_data(
    results: PaperResults,
    data_root: Path,
) -> tuple[Path, Path]:
    """写出 Hermite 与 Linear/SLERP 的片段级配对数据和汇总。"""

    specifications = (
        ("static", results.static_segments, "centered_p95_mm", "mm"),
        ("static", results.static_segments, "frame_increment_p95_mm", "mm"),
        ("translation", results.translation_segments, "effective_lag_ms", "ms"),
        ("translation", results.translation_segments, "aligned_rmse_mm", "mm"),
        ("rotation", results.rotation_segments, "effective_lag_ms", "ms"),
        ("rotation", results.rotation_segments, "aligned_rmse_deg", "deg"),
        ("occlusion", results.occlusion_episodes, "translation_p95_mm", "mm"),
        ("transition", results.transition_segments, "response_ms", "ms"),
    )
    metrics_path = data_root / "strategy_comparison_segments.csv"
    summary_path = data_root / "strategy_comparison_summary.csv"
    metric_fields = (
        "family",
        "metric",
        "unit",
        "session_id",
        "trial_id",
        "segment_id",
        "hermite",
        "linear_slerp",
        "linear_minus_hermite",
        "linear_lower",
    )
    summary_fields = (
        "family",
        "metric",
        "unit",
        "n",
        "hermite_median",
        "hermite_q1",
        "hermite_q3",
        "linear_slerp_median",
        "linear_slerp_q1",
        "linear_slerp_q3",
        "paired_delta_median",
        "paired_delta_q1",
        "paired_delta_q3",
        "linear_lower_count",
    )
    summaries: list[dict[str, Any]] = []
    with metrics_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=metric_fields)
        writer.writeheader()
        for family, rows, metric, unit in specifications:
            matrix = paired_metric_matrix(
                rows,
                (HERMITE_VARIANT, FULL_VARIANT),
                (metric,),
            )[:, :, 0]
            identities = sorted(
                segment_identity(row)
                for row in rows[HERMITE_VARIANT]
                if np.isfinite(float(row[metric]))
            )
            if len(identities) != matrix.shape[0]:
                raise ValueError(f"插值器候选身份与配对矩阵不一致：{family}/{metric}")
            deltas = matrix[:, 1] - matrix[:, 0]
            for identity, values, delta in zip(identities, matrix, deltas, strict=True):
                writer.writerow(
                    {
                        "family": family,
                        "metric": metric,
                        "unit": unit,
                        "session_id": identity[0],
                        "trial_id": identity[1],
                        "segment_id": identity[2],
                        "hermite": values[0],
                        "linear_slerp": values[1],
                        "linear_minus_hermite": delta,
                        "linear_lower": bool(delta < 0),
                    }
                )
            hermite_quantiles = np.quantile(matrix[:, 0], (0.5, 0.25, 0.75))
            linear_quantiles = np.quantile(matrix[:, 1], (0.5, 0.25, 0.75))
            delta_quantiles = np.quantile(deltas, (0.5, 0.25, 0.75))
            summaries.append(
                {
                    "family": family,
                    "metric": metric,
                    "unit": unit,
                    "n": matrix.shape[0],
                    "hermite_median": hermite_quantiles[0],
                    "hermite_q1": hermite_quantiles[1],
                    "hermite_q3": hermite_quantiles[2],
                    "linear_slerp_median": linear_quantiles[0],
                    "linear_slerp_q1": linear_quantiles[1],
                    "linear_slerp_q3": linear_quantiles[2],
                    "paired_delta_median": delta_quantiles[0],
                    "paired_delta_q1": delta_quantiles[1],
                    "paired_delta_q3": delta_quantiles[2],
                    "linear_lower_count": int(np.sum(deltas < 0)),
                }
            )
    with summary_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=summary_fields)
        writer.writeheader()
        writer.writerows(summaries)
    return metrics_path, summary_path


def _write_plot_sheet(
    worksheet: Any,
    fields: tuple[str, ...],
    rows: list[dict[str, Any]],
) -> None:
    """写入一张可筛选、可直接核对的绘图长表。"""

    worksheet.append(fields)
    for row in rows:
        worksheet.append(tuple(row.get(field) for field in fields))
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    worksheet.sheet_view.showGridLines = False
    header_fill = PatternFill("solid", fgColor="1F4E78")
    for cell in worksheet[1]:
        cell.fill = header_fill
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for column_index, field in enumerate(fields, start=1):
        values = [field, *(row.get(field, "") for row in rows)]
        width = min(34, max(11, max(len(str(value)) for value in values) + 2))
        worksheet.column_dimensions[get_column_letter(column_index)].width = width
        if field in {"x_value", "y_value"}:
            for cell in worksheet.iter_cols(
                min_col=column_index,
                max_col=column_index,
                min_row=2,
                max_row=worksheet.max_row,
            ):
                for item in cell:
                    item.number_format = "0.000000"


def _workbooks_equivalent(first: Path, second: Path) -> bool:
    """比较两本绘图工作簿的可见数据与版式契约。"""

    left = load_workbook(first, read_only=False, data_only=False)
    right = load_workbook(second, read_only=False, data_only=False)
    try:
        if left.sheetnames != right.sheetnames:
            return False
        for sheet_name in left.sheetnames:
            left_sheet = left[sheet_name]
            right_sheet = right[sheet_name]
            if (
                left_sheet.max_row != right_sheet.max_row
                or left_sheet.max_column != right_sheet.max_column
                or left_sheet.freeze_panes != right_sheet.freeze_panes
                or left_sheet.auto_filter.ref != right_sheet.auto_filter.ref
            ):
                return False
            for row in range(1, left_sheet.max_row + 1):
                for column in range(1, left_sheet.max_column + 1):
                    left_cell = left_sheet.cell(row=row, column=column)
                    right_cell = right_sheet.cell(row=row, column=column)
                    if (
                        left_cell.value != right_cell.value
                        or left_cell.data_type != right_cell.data_type
                        or left_cell.number_format != right_cell.number_format
                        or left_cell.style_id != right_cell.style_id
                    ):
                        return False
            for column in range(1, left_sheet.max_column + 1):
                letter = get_column_letter(column)
                if left_sheet.column_dimensions[letter].width != right_sheet.column_dimensions[letter].width:
                    return False
        return True
    finally:
        left.close()
        right.close()


def _publish_plot_workbook(temporary: Path, destination: Path) -> None:
    """原子发布绘图工作簿；Windows 占用时仅复用完全等价的正式文件。"""

    try:
        temporary.replace(destination)
    except PermissionError:
        if not destination.exists() or not _workbooks_equivalent(temporary, destination):
            raise
        temporary.unlink()


def _write_figure_source_data(
    results: PaperResults,
    plot_root: Path,
) -> Path:
    """把图二和图三的全部可见数据点写入专用 XLSX。"""

    fields = (
        "figure",
        "panel",
        "series",
        "variant_id",
        "session_id",
        "trial_id",
        "segment_id",
        "x_metric",
        "x_value",
        "y_metric",
        "y_value",
    )

    def append_metric_rows(
        destination: list[dict[str, Any]],
        *,
        figure: str,
        panel: str,
        rows: Mapping[str, tuple[Mapping[str, Any], ...]],
        variants: tuple[str, ...],
        x_key: str | None,
        y_key: str,
    ) -> None:
        """把一个面板的各配置片段追加到统一长表。"""

        for index, variant in enumerate(variants):
            for row in sorted(rows[variant], key=segment_identity):
                y_value = float(row[y_key])
                x_value = float(row[x_key]) if x_key is not None else float(index)
                if not np.isfinite((x_value, y_value)).all():
                    continue
                identity = segment_identity(row)
                destination.append(
                    {
                        "figure": figure,
                        "panel": panel,
                        "series": variant,
                        "variant_id": variant,
                        "session_id": identity[0],
                        "trial_id": identity[1],
                        "segment_id": identity[2],
                        "x_metric": x_key or "category_index",
                        "x_value": x_value,
                        "y_metric": y_key,
                        "y_value": y_value,
                    }
                )

    figure2_rows: list[dict[str, Any]] = []
    append_metric_rows(
        figure2_rows,
        figure="Figure 2",
        panel="(a) Head-motion leakage",
        rows=results.static_segments,
        variants=METHODS,
        x_key=None,
        y_key="centered_p95_mm",
    )
    append_metric_rows(
        figure2_rows,
        figure="Figure 2",
        panel="(b) Dynamic translation",
        rows=results.translation_segments,
        variants=METHODS,
        x_key="effective_lag_ms",
        y_key="aligned_rmse_mm",
    )
    append_metric_rows(
        figure2_rows,
        figure="Figure 2",
        panel="(c) Failure containment",
        rows=results.occlusion_episodes,
        variants=METHODS,
        x_key=None,
        y_key="translation_p95_mm",
    )

    figure3_rows: list[dict[str, Any]] = []
    for row in sorted(results.capture_alignment, key=segment_identity):
        identity = segment_identity(row)
        for index, (series, key) in enumerate(
            (("Capture time", "capture_p95_mm"), ("Arrival time", "arrival_p95_mm"))
        ):
            figure3_rows.append(
                {
                    "figure": "Figure 3",
                    "panel": "(a) Capture-time alignment",
                    "series": series,
                    "variant_id": "",
                    "session_id": identity[0],
                    "trial_id": identity[1],
                    "segment_id": identity[2],
                    "x_metric": "condition_index",
                    "x_value": index,
                    "y_metric": key,
                    "y_value": float(row[key]),
                }
            )
    append_metric_rows(
        figure3_rows,
        figure="Figure 3",
        panel="(b) StaticLock",
        rows=results.static_segments,
        variants=(FULL_VARIANT, NO_STATIC_LOCK),
        x_key=None,
        y_key="centered_p95_mm",
    )
    append_metric_rows(
        figure3_rows,
        figure="Figure 3",
        panel="(c) VCD admission",
        rows=results.occlusion_episodes,
        variants=(FULL_VARIANT, NO_VCD),
        x_key=None,
        y_key="translation_p95_mm",
    )
    append_metric_rows(
        figure3_rows,
        figure="Figure 3",
        panel="(d) Runtime temporal strategies",
        rows=results.translation_segments,
        variants=(NO_TEMPORAL_SYNTHESIS, HERMITE_VARIANT, FULL_VARIANT),
        x_key="effective_lag_ms",
        y_key="aligned_rmse_mm",
    )

    plot_root.mkdir(parents=True, exist_ok=True)
    destination = plot_root / "figure_plot_data.xlsx"
    temporary = plot_root / "figure_plot_data.tmp.xlsx"
    workbook = Workbook()
    readme = workbook.active
    readme.title = "README"
    _write_plot_sheet(
        readme,
        ("项目", "说明"),
        [
            {"项目": "用途", "说明": "图 2 和图 3 的逐点绘图数据；每行是一条实际显示的片段/episode 记录。"},
            {"项目": "数据来源", "说明": "五本只读 Stage 1 工作簿，由 build-paper 重新计算，不回读 raw JSONL。"},
            {"项目": "配对语义", "说明": "session_id、trial_id、segment_id 相同的记录属于严格配对。"},
            {"项目": "图 2(b)", "说明": "只绘制散点与中位数/IQR，不连接跨方法折线。"},
            {"项目": "数值精度", "说明": "XLSX 保留计算得到的浮点值；论文表格另行格式化。"},
        ],
    )
    figure2 = workbook.create_sheet("Figure2")
    figure3 = workbook.create_sheet("Figure3")
    _write_plot_sheet(figure2, fields, figure2_rows)
    _write_plot_sheet(figure3, fields, figure3_rows)
    if temporary.exists():
        temporary.unlink()
    workbook.save(temporary)
    _publish_plot_workbook(temporary, destination)

    verification = load_workbook(destination, read_only=True, data_only=False)
    try:
        if verification.sheetnames != ["README", "Figure2", "Figure3"]:
            raise ValueError("绘图工作簿 sheet 集合不正确")
        if verification["Figure2"].max_row != len(figure2_rows) + 1:
            raise ValueError("绘图工作簿 Figure2 行数不正确")
        if verification["Figure3"].max_row != len(figure3_rows) + 1:
            raise ValueError("绘图工作簿 Figure3 行数不正确")
    finally:
        verification.close()
    return destination


def write_paper(
    results: PaperResults,
    paper_root: Path,
    output_root: Path,
) -> Mapping[str, Path]:
    """写出指标、绘图 XLSX、表格、主稿和 provenance。"""

    metrics_root = output_root / "metrics"
    plot_root = output_root / "plots"
    provenance_root = output_root / "provenance"
    metrics_root.mkdir(parents=True, exist_ok=True)
    provenance_root.mkdir(parents=True, exist_ok=True)
    summary_path = metrics_root / "experiment1_summary.csv"
    fields = (
        "method",
        "variant_id",
        "head_motion_leakage_p95_mm",
        "absolute_registration_p95_mm",
        "stationary_frame_increment_p95_mm",
        "translation_lag_ms",
        "translation_aligned_rmse_mm",
        "rotation_lag_ms",
        "rotation_aligned_rmse_deg",
        "occlusion_p95_mm",
        "catastrophic_failures_gt40",
        "occlusion_episodes",
        "start_transition_response_ms",
    )
    with summary_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for method in METHODS:
            writer.writerow(
                {
                    "method": method,
                    "variant_id": method,
                    "head_motion_leakage_p95_mm": _summary(results.static_segments[method], "centered_p95_mm")[0],
                    "absolute_registration_p95_mm": _summary(results.static_segments[method], "absolute_p95_mm")[0],
                    "stationary_frame_increment_p95_mm": _summary(results.static_segments[method], "frame_increment_p95_mm")[0],
                    "translation_lag_ms": _summary(results.translation_segments[method], "effective_lag_ms")[0],
                    "translation_aligned_rmse_mm": _summary(results.translation_segments[method], "aligned_rmse_mm")[0],
                    "rotation_lag_ms": _summary(results.rotation_segments[method], "effective_lag_ms")[0],
                    "rotation_aligned_rmse_deg": _summary(results.rotation_segments[method], "aligned_rmse_deg")[0],
                    "occlusion_p95_mm": _summary(results.occlusion_episodes[method], "translation_p95_mm")[0],
                    "catastrophic_failures_gt40": sum(bool(row["catastrophic_gt40"]) for row in results.occlusion_episodes[method]),
                    "occlusion_episodes": len(results.occlusion_episodes[method]),
                    "start_transition_response_ms": _summary(results.transition_segments[method], "response_ms")[0],
                }
            )
    capture_path = metrics_root / "capture_alignment.csv"
    with capture_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("session_id", "trial_id", "segment_id", "capture_p95_mm", "arrival_p95_mm", "paired_reduction_mm", "n_candidates"))
        writer.writeheader()
        writer.writerows(results.capture_alignment)
    performance_path = metrics_root / "runtime_performance.json"
    performance_path.write_text(json.dumps(results.performance, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    strategy_metrics_path, strategy_summary_path = _write_strategy_candidate_data(results, metrics_root)
    plot_data_path = _write_figure_source_data(results, plot_root)
    table_root = paper_root / "tables"
    table_root.mkdir(parents=True, exist_ok=True)
    exp1_table = _exp1_table(results)
    exp2_table = _exp2_table(results)
    exp1_table_path = table_root / "experiment1_system_characterization.tex"
    exp2_table_path = table_root / "experiment2_design_attribution.tex"
    exp1_table_path.write_text(exp1_table, encoding="utf-8")
    exp2_table_path.write_text(exp2_table, encoding="utf-8")

    manuscript = paper_root / "egoanchor_cn_v6.tex"
    text = manuscript.read_text(encoding="utf-8")
    text = _replace_block(text, r"\subsection{实验一：应用侧锚点行为}", r"\subsection{实验二：组件归因}", _exp1_text(results))
    text = _replace_block(
        text,
        r"\subsection{实验二：组件归因}",
        r"\subsection{评价指标与汇总契约}",
        _exp2_text(results),
    )
    provenance = "% Paper analysis from immutable Stage 1 XLSX; input SHA-256: " + ", ".join(f"{Path(path).name}={digest}" for path, digest in sorted(results.workbook_sha256.items())) + "\n"
    text = re.sub(
        r"^% Paper analysis from immutable Stage 1 XLSX; input SHA-256:.*\n",
        "",
        text,
        flags=re.M,
    )
    text = text.replace(r"\begin{document}", provenance + r"\begin{document}", 1)
    manuscript.write_text(text, encoding="utf-8")
    manifest = provenance_root / "analysis_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "inputs": dict(results.workbook_sha256),
                "parameters": DEFAULT_SETTINGS_PATH.name,
                "parameters_sha256": settings_sha256(),
                "temporal_evidence": "actual_runtime",
                "output_strategy": "linear_slerp",
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "manuscript": manuscript,
        "exp1_table": exp1_table_path,
        "exp2_table": exp2_table_path,
        "summary": summary_path,
        "capture": capture_path,
        "performance": performance_path,
        "plot_data": plot_data_path,
        "strategy_metrics": strategy_metrics_path,
        "strategy_summary": strategy_summary_path,
        "manifest": manifest,
    }


__all__ = ["write_paper"]

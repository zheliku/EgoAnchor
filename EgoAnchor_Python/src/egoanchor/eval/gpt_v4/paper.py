"""GPT v4 表格、图源数据和中文主稿物化。"""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

from .metrics import (
    FULL_VARIANT,
    METHODS,
    NO_STATIC_LOCK,
    NO_TEMPORAL_SYNTHESIS,
    NO_VCD,
    GptV4Results,
)


def _fmt(value: float, digits: int = 3) -> str:
    """按 GPT v4 表格习惯格式化有限数值。"""

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


def _exp1_table(results: GptV4Results) -> str:
    """生成 GPT v4 实验一八指标表。"""

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
        "& $n=4$ & $n=4$ & $n=4$ & $n=30$ & $n=10$ & $n=9$ & $k/9$ & $n=9$ \\\\",
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

    full = {_key(row): float(row[key]) for row in rows[FULL_VARIANT]}
    disabled = {_key(row): float(row[key]) for row in rows[disabled_variant]}
    if set(full) != set(disabled):
        raise ValueError(f"实验二配对不完整：{disabled_variant}")
    deltas = np.asarray([disabled[key] - full[key] for key in sorted(full)], dtype=float)
    return float(np.median(np.asarray(list(full.values())))), float(np.median(np.asarray(list(disabled.values())))), float(np.median(deltas)), float(np.sum(deltas > 0))


def _key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    """返回可审计的片段配对键。"""

    return str(row["session_id"]), str(row["trial_id"]), str(row["segment_id"])


def _exp2_table(results: GptV4Results) -> str:
    """生成 GPT v4 目标化四组件归因表。"""

    capture = np.asarray([float(row["capture_p95_mm"]) for row in results.capture_alignment])
    arrival = np.asarray([float(row["arrival_p95_mm"]) for row in results.capture_alignment])
    capture_text = f"{_fmt(float(np.median(capture)))} [{_fmt(float(np.quantile(capture, .25)))}, {_fmt(float(np.quantile(capture, .75)))}]"
    arrival_text = f"{_fmt(float(np.median(arrival)))} [{_fmt(float(np.quantile(arrival, .25)))}, {_fmt(float(np.quantile(arrival, .75)))}]"
    reduction = arrival - capture
    capture_effect = f"+{_fmt(float(np.median(reduction)))} [{_fmt(float(np.quantile(reduction, .25)))}, {_fmt(float(np.quantile(reduction, .75)))}]~mm; {int(np.sum(reduction > 0))}/{len(reduction)} 改善"
    full_static, disabled_static, static_delta, static_positive = _paired_summary(results.static_segments, NO_STATIC_LOCK, "centered_p95_mm")
    full_vcd, disabled_vcd, _, _ = _paired_summary(results.occlusion_episodes, NO_VCD, "translation_p95_mm")
    full_lag, disabled_lag, lag_delta, _ = _paired_summary(results.translation_segments, NO_TEMPORAL_SYNTHESIS, "effective_lag_ms")
    full_rmse, disabled_rmse, rmse_delta, _ = _paired_summary(results.translation_segments, NO_TEMPORAL_SYNTHESIS, "aligned_rmse_mm")
    vcd_full = results.occlusion_episodes[FULL_VARIANT]
    vcd_disabled = results.occlusion_episodes[NO_VCD]
    full_failures = sum(bool(row["catastrophic_gt40"]) for row in vcd_full)
    disabled_failures = sum(bool(row["catastrophic_gt40"]) for row in vcd_disabled)
    lines = [
        r"\begin{table*}[t]",
        r"\centering",
        r"\caption{新数据上的目标化组件归因。每个组件只使用直接对应其设计目标的指标；关闭效应为 Disabled--Full。}",
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
        f"时序合成 & Lag / aligned RMSE & {_fmt(full_lag, 1)} / {_fmt(full_rmse)} & {_fmt(disabled_lag, 1)} / {_fmt(disabled_rmse)} & {_fmt(lag_delta, 1)}~ms / +{_fmt(rmse_delta)}~mm \\\\",
        r"\bottomrule",
        r"\end{tabular}%",
        r"}",
        r"\end{table*}",
    ]
    return "\n".join(lines)


def _exp1_text(results: GptV4Results) -> str:
    """生成实验一正文，保持 GPT v4 的论证顺序。"""

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
        "ego_occ": _summary(results.occlusion_episodes[FULL_VARIANT], "translation_p95_mm")[0],
        "one_euro_occ": _summary(results.occlusion_episodes["One-Euro Anchor"], "translation_p95_mm")[0],
        "ego_start": _summary(results.transition_segments[FULL_VARIANT], "response_ms")[0],
    }
    return f"""\\subsection{{实验一：应用侧锚点行为}}

实验一围绕五项应用可感知属性组织：\\emph{{world consistency}} 衡量主动头动是否被错误写入静止物体的世界位置；\\emph{{rest stability}} 衡量静止锚点的逐帧显示抖动；\\emph{{dynamic fidelity}} 将持续运动中的有效时延与时延对齐后的轨迹残差作为不可拆分的权衡；\\emph{{failure containment}} 衡量遮挡和坏观测是否破坏已建立锚点；\\emph{{transition cost}} 衡量稳定优先策略从静止锁定切换到可见运动跟随的代价。

{_exp1_table(results)}

\\textbf{{头动下的世界一致性与静止稳定性。}} 移除每个动作片段的固定注册偏置后，EgoAnchor 的中心化平移 P95 为 {_fmt(values['ego_centered'])}~mm，而 Arrival-Hold、Capture-Hold 与 One-Euro Anchor 分别为 {_fmt(values['arrival_centered'])}、{_fmt(values['capture_centered'])} 与 {_fmt(values['one_euro_centered'])}~mm。EgoAnchor 的绝对注册 P95 为 {_fmt(values['ego_absolute'])}~mm；其静止帧间位置增量 P95 为 {_fmt(values['ego_increment'])}~mm，One-Euro Anchor 为 {_fmt(values['one_euro_increment'])}~mm。

\\textbf{{持续运动中的时延--轨迹质量权衡。}} 持续平移中，EgoAnchor 的有效时延 / lag-aligned RMSE 为 {_fmt(values['ego_lag'], 1)}~ms / {_fmt(values['ego_rmse'])}~mm；Arrival-Hold 为 {_fmt(values['arrival_lag'], 1)}~ms / {_fmt(values['arrival_rmse'])}~mm，One-Euro Anchor 为 {_fmt(values['one_euro_lag'], 1)}~ms / {_fmt(values['one_euro_rmse'])}~mm。结果支持稳定优先的连续轨迹合成，而不是最低时延主张。

\\textbf{{遮挡期间的失效控制。}} 遮挡过程中，EgoAnchor 的 episode-level 平移 P95 中位数为 {_fmt(values['ego_occ'])}~mm，One-Euro Anchor 为 {_fmt(values['one_euro_occ'])}~mm。完整分布、40~mm 阈值超限率和最大值共同保留在图和审阅表中。

\\textbf{{起停转换代价。}} Start-transition response 使用片段前 250~ms 基线、5~mm 位移阈值和 100~ms 持续条件。EgoAnchor 的片段中位数为 {_fmt(values['ego_start'], 1)}~ms；该量包含 StaticLock 解锁证据、候选更新和延迟合成时间线，不是网络或视觉推理的原始时延。

\\begin{{figure*}}[t]
  \\centering
  \\includegraphics[width=0.99\\textwidth]{{figures/generated/experiment1_corrected_newdata.pdf}}
  \\caption{{新数据上的三项核心分布性结果。小标记表示重复动作片段或遮挡过程，箱线表示完整分布的中位数、四分位区间和全范围，实心标记表示中位数。中间面板的 1.5x IQR 异常点仅从散点显示层移除，所有片段仍保留在表格和汇总统计中。左：移除片段固定注册偏置后的头动泄漏；中：持续平移的 fitted-lag--aligned-residual 联合权衡；右：遮挡期间的 episode-level P95。}}
  \\label{{fig:exp1-final}}
\\end{{figure*}}
"""


def _exp2_text(results: GptV4Results) -> str:
    """生成实验二正文、表格和 GPT v4 四面板图。"""

    capture = np.asarray([float(row["capture_p95_mm"]) for row in results.capture_alignment])
    arrival = np.asarray([float(row["arrival_p95_mm"]) for row in results.capture_alignment])
    reduction = arrival - capture
    full_static, disabled_static, static_delta, _ = _paired_summary(results.static_segments, NO_STATIC_LOCK, "centered_p95_mm")
    full_rmse, disabled_rmse, rmse_delta, _ = _paired_summary(results.translation_segments, NO_TEMPORAL_SYNTHESIS, "aligned_rmse_mm")
    full_vcd = results.occlusion_episodes[FULL_VARIANT]
    disabled_vcd = results.occlusion_episodes[NO_VCD]
    return f"""\\subsection{{实验二：组件归因}}

实验二复用实验一的候选、参考轨迹和渲染时间线，在冻结适用场景内逐片段配对完整 EgoAnchor 与单组件消融。采集时刻对齐直接比较同一原始候选在 capture-time 与 arrival-time 世界复合下的误差；StaticLock 使用中心化静止波动；VCD 使用超过 40~mm 的灾难性尾部失效率；时序合成以 lag / aligned residual 成对报告。

{_exp2_table(results)}

\\begin{{figure*}}[t]
  \\centering
  \\includegraphics[width=0.99\\textwidth]{{figures/generated/experiment2_corrected_newdata.pdf}}
  \\caption{{目标化组件归因。左侧依次直接隔离采集时刻复合、StaticLock 与 VCD；右侧显示时序合成的 fitted-lag--aligned-residual 权衡，并与图~\\ref{{fig:exp1-final}} 中间面板统一采用 150--400~ms 与 0--21~mm 的坐标范围。}}
  \\label{{fig:exp2-final}}
\\end{{figure*}}

\\textbf{{采集时刻对齐。}} 对同一批原始候选直接应用两种世界复合后，片段级 candidate P95 由 arrival-time 的 {_fmt(float(np.median(arrival)))}~mm 降至 capture-time 的 {_fmt(float(np.median(capture)))}~mm；{int(np.sum(reduction > 0))}/{len(reduction)} 个片段改善，配对中位降幅为 {_fmt(float(np.median(reduction)))}~mm。

\\textbf{{StaticLock。}} 关闭 StaticLock 后，中心化静止 P95 从 {_fmt(full_static)} 增至 {_fmt(disabled_static)}~mm，配对差值为 +{_fmt(static_delta)}~mm。该结果表明 StaticLock 限制慢速静止漂移，而逐帧增量仍作为表格护栏报告。

\\textbf{{VCD 接纳。}} 启用 VCD 时，{sum(bool(row['catastrophic_gt40']) for row in full_vcd)}/{len(full_vcd)} 次遮挡过程超过 40~mm；关闭后为 {sum(bool(row['catastrophic_gt40']) for row in disabled_vcd)}/{len(disabled_vcd)}。该组件的主证据是尾部失效率，不是单独的中位数。

\\textbf{{时序合成。}} 关闭时序合成后，lag-aligned RMSE 由 {_fmt(full_rmse)} 增至 {_fmt(disabled_rmse)}~mm（增加 +{_fmt(rmse_delta)}~mm）。因此，该组件以显式历史时间线换取连续且更忠实的渲染轨迹。

\\FloatBarrier
"""


def _replace_block(text: str, start: str, end: str, replacement: str) -> str:
    """按章节边界替换 GPT v4 主稿中的实验块。"""

    pattern = re.compile(re.escape(start) + r".*?(?=" + re.escape(end) + r")", re.S)
    updated, count = pattern.subn(lambda _match: replacement.rstrip() + "\n\n", text, count=1)
    if count != 1:
        raise ValueError(f"主稿缺少章节边界：{start} -> {end}")
    return updated


def write_paper(results: GptV4Results, paper_root: Path, output_root: Path) -> Mapping[str, Path]:
    """写出 GPT v4 CSV、表格、主稿和 provenance manifest。"""

    data_root = output_root / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    summary_path = data_root / "experiment1_expanded_summary_v4.csv"
    fields = (
        "method",
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
    capture_path = data_root / "capture_alignment_candidate_metrics.csv"
    with capture_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("session_id", "trial_id", "segment_id", "capture_p95_mm", "arrival_p95_mm", "paired_reduction_mm", "n_candidates"))
        writer.writeheader()
        writer.writerows(results.capture_alignment)
    performance_path = data_root / "runtime_performance_audit_v4.json"
    performance_path.write_text(json.dumps(results.performance, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    table_root = paper_root / "tables"
    table_root.mkdir(parents=True, exist_ok=True)
    exp1_table = _exp1_table(results)
    exp2_table = _exp2_table(results)
    exp1_table_path = table_root / "experiment1_corrected_newdata_v4.tex"
    exp2_table_path = table_root / "experiment2_corrected_newdata_v4.tex"
    exp1_table_path.write_text(exp1_table, encoding="utf-8")
    exp2_table_path.write_text(exp2_table, encoding="utf-8")

    template = Path(__file__).resolve().parents[5] / "2026-EgoAnchor" / "gpt-web-analysis" / "EgoAnchor_corrected_newdata_v4_package" / "paper" / "EgoAnchor_IEEEVR2027_corrected_newdata_v4_vgtc.tex"
    text = template.read_text(encoding="utf-8")
    text = text.replace(r"\graphicspath{{../figures/}{figures/}{pictures/}{images/}{./}}", r"\graphicspath{{figures/}{pictures/}{images/}{./}}")
    text = text.replace("../figures/", "figures/")
    text = _replace_block(text, r"\subsection{实验一：应用侧锚点行为}", r"\subsection{实验二：组件归因}", _exp1_text(results))
    text = _replace_block(text, r"\subsection{实验二：组件归因}", r"\subsection{评价指标与汇总契约}", _exp2_text(results))
    provenance = "% GPT v4 reproduced from immutable Stage 1 XLSX; input SHA-256: " + ", ".join(f"{Path(path).name}={digest}" for path, digest in sorted(results.workbook_sha256.items())) + "\n"
    text = text.replace(r"\begin{document}", provenance + r"\begin{document}", 1)
    manuscript = paper_root / "egoanchor_cn_v6.tex"
    manuscript.write_text(text, encoding="utf-8")
    manifest = output_root / "gpt_v4_manifest.json"
    manifest.write_text(json.dumps({"inputs": dict(results.workbook_sha256), "parameters": "gpt_v4.toml"}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "manuscript": manuscript,
        "exp1_table": exp1_table_path,
        "exp2_table": exp2_table_path,
        "summary": summary_path,
        "capture": capture_path,
        "performance": performance_path,
        "manifest": manifest,
    }


__all__ = ["write_paper"]

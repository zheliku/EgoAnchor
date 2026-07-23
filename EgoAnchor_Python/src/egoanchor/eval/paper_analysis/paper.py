"""实验一/二本地表格、绘图数据和手工引入用 TeX 片段物化。"""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
from openpyxl import Workbook, load_workbook  # type: ignore[import-untyped]
from openpyxl.styles import Alignment, Font, PatternFill  # type: ignore[import-untyped]
from openpyxl.utils import get_column_letter  # type: ignore[import-untyped]

from .figures import summarize_risk_coverage
from .metrics import (
    HERMITE_INTERPOLATION_VARIANT,
    LINEAR_SLERP_VARIANT,
    SMOOTHED_EXTRAPOLATION_VARIANT,
    FULL_VARIANT,
    METHODS,
    NO_STATIC_LOCK,
    NO_VCD,
    PaperResults,
    TEMPORAL_STRATEGY_VARIANTS,
    paired_metric_matrix,
    segment_identity,
)
from .settings import DEFAULT_SETTINGS_PATH, settings_sha256


# 关闭 StaticLock 后平滑外推与 Hermite 插值的片段级配对输出契约。
_STRATEGY_COMPARISON_METRICS = (
    ("static", "centered_p95_mm", "mm"),
    ("static", "frame_increment_p95_mm", "mm"),
    ("translation", "effective_lag_ms", "ms"),
    ("translation", "aligned_rmse_mm", "mm"),
    ("rotation", "effective_lag_ms", "ms"),
    ("rotation", "aligned_rmse_deg", "deg"),
    ("occlusion", "translation_p95_mm", "mm"),
    ("occlusion", "translation_max_mm", "mm"),
    ("occlusion", "catastrophic_gt40", "episode"),
    ("transition", "response_ms", "ms"),
    ("stop", "forward_overshoot_mm", "mm"),
    ("stop", "reverse_return_mm", "mm"),
    ("stop", "settling_time_ms", "ms"),
    ("correction", "position_step_p95_mm", "mm"),
    ("correction", "rotation_step_p95_deg", "deg"),
)


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
    alternative_variant: str,
    key: str,
    reference_variant: str = FULL_VARIANT,
) -> tuple[float, float, float, float]:
    """返回参考、替代和配对差值的中位数，以及替代值较大的片段数。"""

    matrix = paired_metric_matrix(rows, (reference_variant, alternative_variant), (key,))[:, :, 0]
    reference = matrix[:, 0]
    alternative = matrix[:, 1]
    deltas = alternative - reference
    return (
        float(np.median(reference)),
        float(np.median(alternative)),
        float(np.median(deltas)),
        float(np.sum(deltas > 0)),
    )


def _exp2_table(results: PaperResults) -> str:
    """生成实验二三项组件归因与配对时序策略表。"""

    capture = np.asarray([float(row["capture_p95_mm"]) for row in results.capture_alignment])
    arrival = np.asarray([float(row["arrival_p95_mm"]) for row in results.capture_alignment])
    capture_text = f"{_fmt(float(np.median(capture)))} [{_fmt(float(np.quantile(capture, .25)))}, {_fmt(float(np.quantile(capture, .75)))}]"
    arrival_text = f"{_fmt(float(np.median(arrival)))} [{_fmt(float(np.quantile(arrival, .25)))}, {_fmt(float(np.quantile(arrival, .75)))}]"
    reduction = arrival - capture
    capture_effect = f"+{_fmt(float(np.median(reduction)))} [{_fmt(float(np.quantile(reduction, .25)))}, {_fmt(float(np.quantile(reduction, .75)))}]~mm; {int(np.sum(reduction > 0))}/{len(reduction)} 改善"
    full_static, disabled_static, static_delta, static_positive = _paired_summary(results.static_segments, NO_STATIC_LOCK, "centered_p95_mm")
    linear_translation, extrapolation_translation, extrapolation_translation_delta, extrapolation_translation_higher = _paired_summary(
        results.translation_segments,
        SMOOTHED_EXTRAPOLATION_VARIANT,
        "aligned_rmse_mm",
        LINEAR_SLERP_VARIANT,
    )
    linear_rotation, extrapolation_rotation, extrapolation_rotation_delta, extrapolation_rotation_higher = _paired_summary(
        results.rotation_segments,
        SMOOTHED_EXTRAPOLATION_VARIANT,
        "aligned_rmse_deg",
        LINEAR_SLERP_VARIANT,
    )
    linear_overshoot, extrapolation_overshoot, extrapolation_overshoot_delta, _ = _paired_summary(
        results.stop_segments,
        SMOOTHED_EXTRAPOLATION_VARIANT,
        "forward_overshoot_mm",
        LINEAR_SLERP_VARIANT,
    )
    linear_settling, extrapolation_settling, extrapolation_settling_delta, _ = _paired_summary(
        results.stop_segments,
        SMOOTHED_EXTRAPOLATION_VARIANT,
        "settling_time_ms",
        LINEAR_SLERP_VARIANT,
    )
    hermite_translation = _summary(results.translation_segments[HERMITE_INTERPOLATION_VARIANT], "aligned_rmse_mm")[0]
    hermite_rotation = _summary(results.rotation_segments[HERMITE_INTERPOLATION_VARIANT], "aligned_rmse_deg")[0]
    vcd_full = results.occlusion_episodes[FULL_VARIANT]
    vcd_disabled = results.occlusion_episodes[NO_VCD]
    vcd_aurc = _cell(_summary(results.vcd_aurc_segments, "aurc_mm"))
    vcd_full_risk = _cell(_summary(results.vcd_aurc_segments, "full_coverage_risk_mm"))
    vcd_risk_gain = _cell(_summary(results.vcd_aurc_segments, "risk_gain_mm"))
    full_failures = sum(bool(row["catastrophic_gt40"]) for row in vcd_full)
    disabled_failures = sum(bool(row["catastrophic_gt40"]) for row in vcd_disabled)
    lines = [
        r"\begin{table*}[t]",
        r"\centering",
        r"\caption{新数据上的三项组件归因与逐帧输出策略比较。VCD score 行报告连续分数诱导顺序的 event 级 AURC；VCD admission 行报告冻结阈值的运行时效果。Smoothed KF Extrapolation、Linear/SLERP 与 Hermite Interpolation 均关闭 StaticLock，并保持 Kalman、VCD、生命周期和候选序列一致。}",
        r"\label{tab:exp2-final}",
        r"\small",
        r"\setlength{\tabcolsep}{4.8pt}",
        r"\resizebox{\textwidth}{!}{%",
        r"\begin{tabular}{lllll}",
        r"\toprule",
        "比较 & 直接指标 & 参照 & 对照 & 配对差 \\\\",
        r"\midrule",
        f"采集时刻对齐 & 同一候选的复合 P95 & {capture_text}~mm & {arrival_text}~mm & {capture_effect} \\\\",
        f"StaticLock & 中心化静止 P95 & {_fmt(full_static)}~mm & {_fmt(disabled_static)}~mm & +{_fmt(static_delta)}~mm；{int(static_positive)}/{len(results.static_segments[FULL_VARIANT])} 片段变差 \\\\",
        f"VCD score & event AURC（越低越好） & {vcd_aurc}~mm & 全覆盖风险 {vcd_full_risk}~mm & 相对全覆盖收益 {vcd_risk_gain}~mm \\\\",
        f"VCD 接纳 & 遮挡最大误差 $>40$~mm & {full_failures}/{len(vcd_full)}；max {_fmt(max(float(row['translation_max_mm']) for row in vcd_full))}~mm & {disabled_failures}/{len(vcd_disabled)}；max {_fmt(max(float(row['translation_max_mm']) for row in vcd_disabled))}~mm & 消除本批次观测到的灾难性失效 \\\\",
        f"时序策略（StaticLock off） & 平移 / 旋转 aligned RMSE & Linear/SLERP {_fmt(linear_translation)}~mm / {_fmt(linear_rotation)}$^\\circ$ & Smoothed KF {_fmt(extrapolation_translation)}~mm / {_fmt(extrapolation_rotation)}$^\\circ$ & Extrapolation--Linear: {_fmt(extrapolation_translation_delta)}~mm / {_fmt(extrapolation_rotation_delta)}$^\\circ$；{int(extrapolation_translation_higher)}/{len(results.translation_segments[LINEAR_SLERP_VARIANT])}、{int(extrapolation_rotation_higher)}/{len(results.rotation_segments[LINEAR_SLERP_VARIANT])} 个片段外推较高 \\\\",
        f"Hermite 补充（StaticLock off） & 平移 / 旋转 aligned RMSE & Linear/SLERP {_fmt(linear_translation)}~mm / {_fmt(linear_rotation)}$^\\circ$ & Hermite {_fmt(hermite_translation)}~mm / {_fmt(hermite_rotation)}$^\\circ$ & 与 Linear/SLERP 对照见图~3(d) \\\\",
        f"停止护栏（StaticLock off） & 前向过冲 / settling & Linear/SLERP {_fmt(linear_overshoot)}~mm / {_fmt(linear_settling, 1)}~ms & Smoothed KF {_fmt(extrapolation_overshoot)}~mm / {_fmt(extrapolation_settling, 1)}~ms & Extrapolation--Linear: {_fmt(extrapolation_overshoot_delta)}~mm / {_fmt(extrapolation_settling_delta, 1)}~ms \\\\",
        r"\bottomrule",
        r"\end{tabular}%",
        r"}",
        r"\end{table*}",
    ]
    return "\n".join(lines)


def _write_strategy_candidate_data(
    results: PaperResults,
    data_root: Path,
) -> tuple[Path, Path]:
    """写出关闭 StaticLock 后外推、Linear/SLERP 与 Hermite 的配对数据和汇总。"""

    rows_by_family = {
        "static": results.static_segments,
        "translation": results.translation_segments,
        "rotation": results.rotation_segments,
        "occlusion": results.occlusion_episodes,
        "transition": results.transition_segments,
        "stop": results.stop_segments,
        "correction": results.correction_segments,
    }
    metrics_path = data_root / "strategy_comparison_segments.csv"
    summary_path = data_root / "strategy_comparison_summary.csv"
    metric_fields = (
        "family",
        "metric",
        "unit",
        "session_id",
        "trial_id",
        "segment_id",
        "smoothed_kf_extrapolation",
        "linear_slerp_interpolation",
        "hermite_interpolation",
        "extrapolation_minus_linear",
        "hermite_minus_linear",
    )
    summary_fields = (
        "family",
        "metric",
        "unit",
        "n",
        "smoothed_kf_extrapolation_median",
        "smoothed_kf_extrapolation_q1",
        "smoothed_kf_extrapolation_q3",
        "linear_slerp_interpolation_median",
        "linear_slerp_interpolation_q1",
        "linear_slerp_interpolation_q3",
        "hermite_interpolation_median",
        "hermite_interpolation_q1",
        "hermite_interpolation_q3",
        "extrapolation_minus_linear_median",
        "extrapolation_minus_linear_q1",
        "extrapolation_minus_linear_q3",
        "hermite_minus_linear_median",
        "hermite_minus_linear_q1",
        "hermite_minus_linear_q3",
    )
    summaries: list[dict[str, Any]] = []
    with metrics_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=metric_fields)
        writer.writeheader()
        for family, metric, unit in _STRATEGY_COMPARISON_METRICS:
            rows = rows_by_family[family]
            matrix = paired_metric_matrix(
                rows,
                TEMPORAL_STRATEGY_VARIANTS,
                (metric,),
            )[:, :, 0]
            identities = sorted(
                segment_identity(row)
                for row in rows[SMOOTHED_EXTRAPOLATION_VARIANT]
                if np.isfinite(float(row[metric]))
            )
            if len(identities) != matrix.shape[0]:
                raise ValueError(f"时序策略身份与配对矩阵不一致：{family}/{metric}")
            extrapolation_minus_linear = matrix[:, 0] - matrix[:, 1]
            hermite_minus_linear = matrix[:, 2] - matrix[:, 1]
            for identity, values, extrapolation_delta, hermite_delta in zip(
                identities,
                matrix,
                extrapolation_minus_linear,
                hermite_minus_linear,
                strict=True,
            ):
                writer.writerow(
                    {
                        "family": family,
                        "metric": metric,
                        "unit": unit,
                        "session_id": identity[0],
                        "trial_id": identity[1],
                        "segment_id": identity[2],
                        "smoothed_kf_extrapolation": values[0],
                        "linear_slerp_interpolation": values[1],
                        "hermite_interpolation": values[2],
                        "extrapolation_minus_linear": extrapolation_delta,
                        "hermite_minus_linear": hermite_delta,
                    }
                )
            extrapolation_quantiles = np.quantile(matrix[:, 0], (0.5, 0.25, 0.75))
            linear_quantiles = np.quantile(matrix[:, 1], (0.5, 0.25, 0.75))
            hermite_quantiles = np.quantile(matrix[:, 2], (0.5, 0.25, 0.75))
            extrapolation_delta_quantiles = np.quantile(extrapolation_minus_linear, (0.5, 0.25, 0.75))
            hermite_delta_quantiles = np.quantile(hermite_minus_linear, (0.5, 0.25, 0.75))
            summaries.append(
                {
                    "family": family,
                    "metric": metric,
                    "unit": unit,
                    "n": matrix.shape[0],
                    "smoothed_kf_extrapolation_median": extrapolation_quantiles[0],
                    "smoothed_kf_extrapolation_q1": extrapolation_quantiles[1],
                    "smoothed_kf_extrapolation_q3": extrapolation_quantiles[2],
                    "linear_slerp_interpolation_median": linear_quantiles[0],
                    "linear_slerp_interpolation_q1": linear_quantiles[1],
                    "linear_slerp_interpolation_q3": linear_quantiles[2],
                    "hermite_interpolation_median": hermite_quantiles[0],
                    "hermite_interpolation_q1": hermite_quantiles[1],
                    "hermite_interpolation_q3": hermite_quantiles[2],
                    "extrapolation_minus_linear_median": extrapolation_delta_quantiles[0],
                    "extrapolation_minus_linear_q1": extrapolation_delta_quantiles[1],
                    "extrapolation_minus_linear_q3": extrapolation_delta_quantiles[2],
                    "hermite_minus_linear_median": hermite_delta_quantiles[0],
                    "hermite_minus_linear_q1": hermite_delta_quantiles[1],
                    "hermite_minus_linear_q3": hermite_delta_quantiles[2],
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
    for row in sorted(
        results.vcd_risk_coverage,
        key=lambda item: (*segment_identity(item), float(item["coverage"])),
    ):
        identity = segment_identity(row)
        figure3_rows.append(
            {
                "figure": "Figure 3",
                "panel": "(c) VCD score risk-coverage",
                "series": "Event curve",
                "variant_id": FULL_VARIANT,
                "session_id": identity[0],
                "trial_id": identity[1],
                "segment_id": identity[2],
                "x_metric": "coverage",
                "x_value": float(row["coverage"]),
                "y_metric": "selective_risk_mm",
                "y_value": float(row["selective_risk_mm"]),
            }
        )
    for row in summarize_risk_coverage(results.vcd_risk_coverage):
        for series, key in (
            ("Median", "selective_risk_median_mm"),
            ("IQR lower", "selective_risk_q1_mm"),
            ("IQR upper", "selective_risk_q3_mm"),
        ):
            figure3_rows.append(
                {
                    "figure": "Figure 3",
                    "panel": "(c) VCD score risk-coverage",
                    "series": series,
                    "variant_id": FULL_VARIANT,
                    "session_id": "",
                    "trial_id": "",
                    "segment_id": "",
                    "x_metric": "coverage",
                    "x_value": float(row["coverage"]),
                    "y_metric": key,
                    "y_value": float(row[key]),
                }
            )
    append_metric_rows(
        figure3_rows,
        figure="Figure 3",
        panel="(d) Runtime temporal strategies",
        rows=results.translation_segments,
        variants=TEMPORAL_STRATEGY_VARIANTS,
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
            {"项目": "数据来源", "说明": "五本只读 Stage 1 工作簿，由论文分析重新计算，不回读 raw JSONL。"},
            {"项目": "配对语义", "说明": "session_id、trial_id、segment_id 相同的记录属于严格配对。"},
            {"项目": "图 2(b)", "说明": "只绘制散点与中位数/IQR，不连接跨方法折线。"},
            {"项目": "图 3(c)", "说明": "event 曲线不拆分同分候选；固定 coverage 汇总取第一个不小于目标 coverage 的完整同分组。"},
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


def _figure_two_tex(figure_directory: str) -> str:
    """生成实验一图片的手工粘贴 TeX 片段。"""

    return f"""\\begin{{figure*}}[t]
  \\centering
  \\begin{{subfigure}}[t]{{0.32\\textwidth}}
    \\centering
    \\includegraphics[width=\\linewidth]{{{figure_directory}/figure2a_head_motion.pdf}}
    \\caption{{头动下的中心化误差}}
    \\label{{fig:exp1-head-motion}}
  \\end{{subfigure}}\\hfill
  \\begin{{subfigure}}[t]{{0.32\\textwidth}}
    \\centering
    \\includegraphics[width=\\linewidth]{{{figure_directory}/figure2b_translation.pdf}}
    \\caption{{持续平移的时延与残差}}
    \\label{{fig:exp1-translation}}
  \\end{{subfigure}}\\hfill
  \\begin{{subfigure}}[t]{{0.32\\textwidth}}
    \\centering
    \\includegraphics[width=\\linewidth]{{{figure_directory}/figure2c_occlusion.pdf}}
    \\caption{{遮挡期间的平移误差}}
    \\label{{fig:exp1-occlusion}}
  \\end{{subfigure}}
  \\caption{{实验一的三项核心分布。小标记表示动作片段或遮挡过程，箱线给出中位数、四分位区间和全范围，实心标记表示中位数。图~(a) 和 (c) 的细线连接同一片段在不同方法下的结果；图~(b) 仅保留各方法散点及中位数/IQR，并为比较可读性不显示超过 25~mm 的异常片段，完整数值保留在绘图审计表中。}}
  \\label{{fig:exp1-final}}
\\end{{figure*}}
"""


def _figure_three_tex(figure_directory: str) -> str:
    """生成实验二图片的手工粘贴 TeX 片段。"""

    return f"""\\begin{{figure*}}[t]
  \\centering
  \\begin{{subfigure}}[t]{{0.18\\textwidth}}
    \\centering
    \\includegraphics[width=\\linewidth]{{{figure_directory}/figure3a_capture_alignment.pdf}}
    \\caption{{采集时刻对齐}}
    \\label{{fig:exp2-alignment}}
  \\end{{subfigure}}\\hfill
  \\begin{{subfigure}}[t]{{0.18\\textwidth}}
    \\centering
    \\includegraphics[width=\\linewidth]{{{figure_directory}/figure3b_static_lock.pdf}}
    \\caption{{StaticLock}}
    \\label{{fig:exp2-static-lock}}
  \\end{{subfigure}}\\hfill
  \\begin{{subfigure}}[t]{{0.18\\textwidth}}
    \\centering
    \\includegraphics[width=\\linewidth]{{{figure_directory}/figure3c_vcd_risk_coverage.pdf}}
    \\caption{{VCD score 风险--覆盖率}}
    \\label{{fig:exp2-vcd}}
  \\end{{subfigure}}\\hfill
  \\begin{{subfigure}}[t]{{0.40\\textwidth}}
    \\centering
    \\includegraphics[width=\\linewidth]{{{figure_directory}/figure3d_temporal_strategies.pdf}}
    \\caption{{时序策略}}
    \\label{{fig:exp2-temporal}}
  \\end{{subfigure}}
  \\caption{{实验二的组件归因与逐帧输出策略比较。图~(a)、(b) 分别比较采集时刻复合和 StaticLock；图~(c) 展示 VCD 分数诱导的 event 级风险--覆盖率：从高 VCD 候选逐步加入低 VCD 候选，横轴表示保留候选比例。图~(d) 的主体是 Smoothed KF Extrapolation 与 Linear/SLERP，Hermite 为补充条件。三路均关闭 StaticLock，并共享模型、接纳、生命周期、候选序列和渲染时间线。为比较可读性，图~(d) 不显示超过 32~mm 的异常片段，完整数值保留在绘图审计表中。}}
  \\label{{fig:exp2-final}}
\\end{{figure*}}
"""


def write_analysis_artifacts(
    results: PaperResults,
    output_root: Path,
    figure_tex_directory: str,
) -> Mapping[str, Path]:
    """只在活动批次写出指标、绘图 XLSX、表格和手工粘贴用 TeX 片段。"""

    metrics_root = output_root / "metrics"
    plot_root = output_root / "plots"
    provenance_root = output_root / "provenance"
    tex_root = output_root / "tex"
    table_root = tex_root / "tables"
    figure_root = tex_root / "figures"
    metrics_root.mkdir(parents=True, exist_ok=True)
    provenance_root.mkdir(parents=True, exist_ok=True)
    table_root.mkdir(parents=True, exist_ok=True)
    figure_root.mkdir(parents=True, exist_ok=True)
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
        "occlusion_max_mm",
        "catastrophic_failures_gt40",
        "occlusion_episodes",
        "start_transition_response_ms",
        "stop_forward_overshoot_mm",
        "stop_reverse_return_mm",
        "stop_settling_time_ms",
        "correction_position_step_p95_mm",
        "correction_rotation_step_p95_deg",
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
                    "occlusion_max_mm": _summary(results.occlusion_episodes[method], "translation_max_mm")[0],
                    "catastrophic_failures_gt40": sum(bool(row["catastrophic_gt40"]) for row in results.occlusion_episodes[method]),
                    "occlusion_episodes": len(results.occlusion_episodes[method]),
                    "start_transition_response_ms": _summary(results.transition_segments[method], "response_ms")[0],
                    "stop_forward_overshoot_mm": _summary(results.stop_segments[method], "forward_overshoot_mm")[0],
                    "stop_reverse_return_mm": _summary(results.stop_segments[method], "reverse_return_mm")[0],
                    "stop_settling_time_ms": _summary(results.stop_segments[method], "settling_time_ms")[0],
                    "correction_position_step_p95_mm": _summary(results.correction_segments[method], "position_step_p95_mm")[0],
                    "correction_rotation_step_p95_deg": _summary(results.correction_segments[method], "rotation_step_p95_deg")[0],
                }
            )
    capture_path = metrics_root / "capture_alignment.csv"
    with capture_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("session_id", "trial_id", "segment_id", "capture_p95_mm", "arrival_p95_mm", "paired_reduction_mm", "n_candidates"))
        writer.writeheader()
        writer.writerows(results.capture_alignment)
    vcd_curve_path = metrics_root / "vcd_risk_coverage.csv"
    with vcd_curve_path.open("w", newline="", encoding="utf-8") as handle:
        vcd_curve_fields = (
            "session_id",
            "trial_id",
            "segment_id",
            "score_threshold",
            "score_tie_count",
            "retained_candidates",
            "evaluable_candidates",
            "coverage",
            "selective_risk_mm",
        )
        writer = csv.DictWriter(handle, fieldnames=vcd_curve_fields)
        writer.writeheader()
        writer.writerows(results.vcd_risk_coverage)
    vcd_aurc_path = metrics_root / "vcd_aurc_segments.csv"
    with vcd_aurc_path.open("w", newline="", encoding="utf-8") as handle:
        vcd_aurc_fields = (
            "session_id",
            "trial_id",
            "segment_id",
            "candidate_rows",
            "evaluable_candidates",
            "excluded_candidates",
            "score_levels",
            "full_coverage_risk_mm",
            "aurc_mm",
            "risk_gain_mm",
        )
        writer = csv.DictWriter(handle, fieldnames=vcd_aurc_fields)
        writer.writeheader()
        writer.writerows(results.vcd_aurc_segments)
    performance_path = metrics_root / "runtime_performance.json"
    performance_path.write_text(json.dumps(results.performance, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    strategy_metrics_path, strategy_summary_path = _write_strategy_candidate_data(results, metrics_root)
    plot_data_path = _write_figure_source_data(results, plot_root)
    exp1_table = _exp1_table(results)
    exp2_table = _exp2_table(results)
    exp1_table_path = table_root / "experiment1_system_characterization.tex"
    exp2_table_path = table_root / "experiment2_design_attribution.tex"
    exp1_table_path.write_text(exp1_table, encoding="utf-8")
    exp2_table_path.write_text(exp2_table, encoding="utf-8")

    figure_directory = figure_tex_directory.strip("/")
    if not figure_directory or ".." in Path(figure_directory).parts:
        raise ValueError("图片 TeX 路径必须是论文内相对目录")
    figure2_path = figure_root / "figure2_experiment1.tex"
    figure3_path = figure_root / "figure3_experiment2.tex"
    figure2_path.write_text(_figure_two_tex(figure_directory), encoding="utf-8")
    figure3_path.write_text(_figure_three_tex(figure_directory), encoding="utf-8")
    manifest = provenance_root / "analysis_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "inputs": dict(results.workbook_sha256),
                "parameters": DEFAULT_SETTINGS_PATH.name,
                "parameters_sha256": settings_sha256(),
                "publication_boundary": "analysis_only_manual_tex_copy",
                "figure_tex_directory": figure_directory,
                "temporal_evidence": "actual_runtime",
                "output_strategy": "temporal_strategy_comparison",
                "vcd_score_evidence": {
                    "risk": "capture_time_aligned_raw_translation_error_mm",
                    "score_direction": "descending",
                    "tie_policy": "same_score_group_is_indivisible",
                    "auc_integration": "right_continuous_step_over_event_coverage",
                    "unit": "occlusion_event",
                },
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "exp1_table": exp1_table_path,
        "exp2_table": exp2_table_path,
        "figure2_tex": figure2_path,
        "figure3_tex": figure3_path,
        "summary": summary_path,
        "capture": capture_path,
        "vcd_risk_coverage": vcd_curve_path,
        "vcd_aurc": vcd_aurc_path,
        "performance": performance_path,
        "plot_data": plot_data_path,
        "strategy_metrics": strategy_metrics_path,
        "strategy_summary": strategy_summary_path,
        "manifest": manifest,
    }


__all__ = ["write_analysis_artifacts"]

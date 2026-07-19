"""Stage 2 实验一行为图与实验二 VCD 图的 plot-ready 行。"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import math
from typing import Iterable, Sequence

import numpy as np

from .exp1 import (
    EXP1_VARIANTS,
    Exp1AnalysisResult,
    Exp1RenderSeries,
    Exp1Trial,
    MetricRow,
    ScenarioSummaryRow,
)
from .exp2 import EXP2_COMPONENTS, PairedDeltaRow, PairedDeltaSummaryRow
from .params import AnalysisParameters
from .pose import rotation_error_deg
from .vcd import VcdAnalysisResult, VcdCurvePoint
from .windows import EventWindow, OcclusionWindow, build_event_windows, detect_reference_motion, pair_occlusion_windows


@dataclass(frozen=True, slots=True)
class Exp1PlotRows:
    """保存实验一四面板行为图的 display-ready CSV 行。"""

    head_motion_trace: tuple[dict[str, object], ...]
    """代表静止头动事件的头动速度与三系统误差时间线。"""

    start_stop_trace: tuple[dict[str, object], ...]
    """代表起停事件的参考与四系统显示轨迹。"""

    lag_tradeoff: tuple[dict[str, object], ...]
    """持续平移全部 event 点与系统 median/IQR。"""

    occlusion_trace: tuple[dict[str, object], ...]
    """代表遮挡事件的四系统误差与 output 状态时间线。"""


def _representative_event(
    result: Exp1AnalysisResult,
    scenario_id: str,
    metric_key: str,
) -> tuple[str, str, str]:
    """选择 EgoAnchor 指标最接近全部事件中位数的稳定代表事件。

    参数：
        result: 已完成 event-first 分析的实验一结果。
        scenario_id: 需要选择代表事件的场景。
        metric_key: 用于代表性排序的冻结 event 指标。
    """

    candidates = tuple(
        row
        for row in result.event_metrics
        if row.scenario_id == scenario_id
        and row.variant_id == "EgoAnchor"
        and row.metric_key == metric_key
        and row.metric_value is not None
        and math.isfinite(row.metric_value)
    )
    if not candidates:
        raise ValueError(f"代表事件缺少有限 EgoAnchor 指标：{scenario_id}/{metric_key}")
    def metric_value(row: MetricRow) -> float:
        """返回已由候选筛选保证存在的有限指标值。"""

        if row.metric_value is None:
            raise ValueError("代表事件指标值意外为空")
        return float(row.metric_value)

    median = float(np.median([metric_value(row) for row in candidates]))
    selected = min(
        candidates,
        key=lambda row: (
            abs(metric_value(row) - median),
            row.session_id,
            row.trial_id,
            row.event_id,
        ),
    )
    return selected.session_id, selected.trial_id, selected.event_id


def _find_trial(
    trials: Sequence[Exp1Trial],
    scenario_id: str,
    key: tuple[str, str, str],
) -> Exp1Trial:
    """按代表事件键查找唯一 trial。

    参数：
        trials: 当前分析批次的完成 trial。
        scenario_id: 代表事件所属场景。
        key: ``session_id, trial_id, event_id`` 代表事件键。
    """

    matches = tuple(
        trial
        for trial in trials
        if trial.scenario_id == scenario_id
        and trial.session_id == key[0]
        and trial.trial_id == key[1]
    )
    if len(matches) != 1:
        raise ValueError(f"代表事件无法匹配唯一 trial：{scenario_id}/{key}")
    return matches[0]


def _event_window(trial: Exp1Trial, event_id: str) -> EventWindow:
    """返回普通场景代表事件的冻结窗口。"""

    matches = tuple(
        window
        for window in build_event_windows(trial.markers, trial.trial_end_ms)
        if window.marker.event_id == event_id
    )
    if len(matches) != 1:
        raise ValueError(f"代表事件无法匹配唯一普通窗口：{event_id}")
    return matches[0]


def _occlusion_window(trial: Exp1Trial, event_id: str) -> OcclusionWindow:
    """返回遮挡场景代表事件的成对窗口。"""

    matches = tuple(
        window
        for window in pair_occlusion_windows(trial.markers, trial.trial_end_ms)
        if window.event_id == event_id
    )
    if len(matches) != 1:
        raise ValueError(f"代表事件无法匹配唯一遮挡窗口：{event_id}")
    return matches[0]


def _series(trial: Exp1Trial, variant_id: str) -> Exp1RenderSeries:
    """返回 trial 中唯一指定系统的 render 序列。"""

    matches = tuple(item for item in trial.render_series if item.variant_id == variant_id)
    if len(matches) != 1:
        raise ValueError(f"代表事件缺少唯一 render 系统：{variant_id}")
    return matches[0]


def _indices(series: Exp1RenderSeries, start_ms: float, end_ms: float) -> np.ndarray:
    """返回半开 event 窗口内 render 索引并检查最少样本。"""

    selected = np.flatnonzero((series.times_ms >= start_ms) & (series.times_ms < end_ms))
    if len(selected) < 2:
        raise ValueError("代表事件 render 样本不足")
    return selected


def _translation_errors(series: Exp1RenderSeries, indices: np.ndarray) -> np.ndarray:
    """返回代表事件逐 tick 平移误差，无效 pose 写为 NaN。"""

    valid = (
        series.reference_pose_valid[indices]
        & series.has_display_pose[indices]
        & np.all(np.isfinite(series.reference_positions_m[indices]), axis=1)
        & np.all(np.isfinite(series.display_positions_m[indices]), axis=1)
    )
    values = np.full(len(indices), np.nan, dtype=np.float64)
    values[valid] = np.linalg.norm(
        series.display_positions_m[indices][valid]
        - series.reference_positions_m[indices][valid],
        axis=1,
    ) * 1000.0
    return values


def _head_speed_deg_s(
    series: Exp1RenderSeries,
    indices: np.ndarray,
    params: AnalysisParameters,
) -> np.ndarray:
    """计算代表事件相邻 head 四元数的描述性角速度。"""

    times = series.times_ms[indices]
    rotations = series.head_rotations[indices]
    values = np.full(len(indices), np.nan, dtype=np.float64)
    finite = np.all(np.isfinite(rotations), axis=1)
    pairs = finite[:-1] & finite[1:]
    intervals = np.diff(times)
    positive = intervals[np.isfinite(intervals) & (intervals > 0.0)]
    if len(positive):
        nominal_gap = float(np.median(positive))
        pairs &= intervals <= params.maximum_gap_factor * nominal_gap
    pair_indices = np.flatnonzero(pairs)
    if len(pair_indices):
        angles = rotation_error_deg(
            rotations[pair_indices + 1],
            rotations[pair_indices],
            params.quaternion_norm_tolerance,
        )
        values[pair_indices + 1] = angles * 1000.0 / np.diff(times)[pair_indices]
    return values


def _optional_float(value: float) -> float | None:
    """把非有限绘图值编码为空单元格。"""

    return float(value) if math.isfinite(float(value)) else None


def _head_motion_rows(
    result: Exp1AnalysisResult,
    trials: Sequence[Exp1Trial],
    params: AnalysisParameters,
) -> tuple[dict[str, object], ...]:
    """生成代表静止头动事件的三系统时间线。"""

    key = _representative_event(result, "static_head_motion", "translation_event_pninetyfive_mm")
    trial = _find_trial(trials, "static_head_motion", key)
    window = _event_window(trial, key[2])
    rows: list[dict[str, object]] = []
    for variant_id in ("Arrival-Hold", "Capture-Hold", "EgoAnchor"):
        series = _series(trial, variant_id)
        indices = _indices(series, window.start_ms, window.end_ms)
        errors = _translation_errors(series, indices)
        head_speed = _head_speed_deg_s(series, indices, params)
        for sample_index, (index, error, speed) in enumerate(zip(indices, errors, head_speed)):
            rows.append(
                {
                    "plot_id": "exp1_head_motion_trace",
                    "panel_id": "head_motion",
                    "session_id": trial.session_id,
                    "scenario_id": trial.scenario_id,
                    "trial_id": trial.trial_id,
                    "event_id": key[2],
                    "variant_id": variant_id,
                    "sample_index": sample_index,
                    "time_ms": float(series.times_ms[index] - window.start_ms),
                    "head_angular_speed_deg_s": _optional_float(speed),
                    "translation_error_mm": _optional_float(error),
                    "selection_rule": "egoanchor_metric_nearest_event_median",
                    "input_workbook_sha256": trial.workbook_sha256,
                }
            )
    return tuple(rows)


def _reference_motion(
    series: Exp1RenderSeries,
    indices: np.ndarray,
    params: AnalysisParameters,
):
    """在代表起停事件内检测平台参考运动窗口。"""

    valid = (
        series.reference_pose_valid[indices]
        & np.all(np.isfinite(series.reference_positions_m[indices]), axis=1)
        & np.all(np.isfinite(series.reference_rotations[indices]), axis=1)
        & np.isfinite(series.reference_linear_speed_m_s[indices])
        & np.isfinite(series.reference_angular_speed_deg_s[indices])
    )
    selected = indices[valid]
    motion = detect_reference_motion(
        series.times_ms[selected],
        series.reference_linear_speed_m_s[selected],
        series.reference_angular_speed_deg_s[selected],
        series.reference_positions_m[selected],
        series.reference_rotations[selected],
        params,
    )
    if motion is None:
        raise ValueError("代表起停事件没有可绘制的参考运动")
    return motion


def _start_stop_rows(
    result: Exp1AnalysisResult,
    trials: Sequence[Exp1Trial],
    params: AnalysisParameters,
) -> tuple[dict[str, object], ...]:
    """生成代表起停事件的参考与四系统显示轨迹。"""

    key = _representative_event(result, "start_stop_6dof", "motion_translation_pninetyfive_mm")
    trial = _find_trial(trials, "start_stop_6dof", key)
    window = _event_window(trial, key[2])
    ego = _series(trial, "EgoAnchor")
    ego_indices = _indices(ego, window.start_ms, window.end_ms)
    motion = _reference_motion(ego, ego_indices, params)
    post_start = motion.stop_ms + params.post_stop_guard_ms
    post_end = post_start + params.post_stop_window_ms
    rows: list[dict[str, object]] = []
    for variant_id in EXP1_VARIANTS:
        series = _series(trial, variant_id)
        indices = _indices(series, window.start_ms, window.end_ms)
        errors = _translation_errors(series, indices)
        reference_origin = series.reference_positions_m[indices[0]]
        display_origin = series.display_positions_m[indices[0]]
        reference_displacement = np.linalg.norm(
            series.reference_positions_m[indices] - reference_origin,
            axis=1,
        ) * 1000.0
        display_displacement = np.linalg.norm(
            series.display_positions_m[indices] - display_origin,
            axis=1,
        ) * 1000.0
        for sample_index, (index, error, reference_value, display_value) in enumerate(
            zip(indices, errors, reference_displacement, display_displacement)
        ):
            time = float(series.times_ms[index])
            phase = (
                "pre_motion"
                if time < motion.onset_ms
                else "motion"
                if time <= motion.stop_ms
                else "post_stop"
                if post_start <= time < post_end
                else "transition"
            )
            rows.append(
                {
                    "plot_id": "exp1_start_stop_trace",
                    "panel_id": "start_stop",
                    "session_id": trial.session_id,
                    "scenario_id": trial.scenario_id,
                    "trial_id": trial.trial_id,
                    "event_id": key[2],
                    "variant_id": variant_id,
                    "sample_index": sample_index,
                    "time_ms": time - window.start_ms,
                    "reference_displacement_mm": _optional_float(reference_value),
                    "display_displacement_mm": _optional_float(display_value),
                    "translation_error_mm": _optional_float(error),
                    "phase": phase,
                    "has_output_pose": bool(series.has_output_pose[index]),
                    "latest_static_locked": bool(series.latest_static_locked[index]),
                    "selection_rule": "egoanchor_metric_nearest_event_median",
                    "input_workbook_sha256": trial.workbook_sha256,
                }
            )
    return tuple(rows)


def _lag_tradeoff_rows(result: Exp1AnalysisResult) -> tuple[dict[str, object], ...]:
    """生成持续平移全部事件点和系统 median/IQR。"""

    lag_key = "effective_translation_lag_ms"
    residual_key = "translation_lag_pninetyfive_residual_mm"
    event_groups: dict[tuple[str, str, str, str], dict[str, MetricRow]] = {}
    for event_row in result.event_metrics:
        if event_row.scenario_id == "continuous_translation" and event_row.metric_key in {lag_key, residual_key}:
            event_groups.setdefault(
                (event_row.session_id, event_row.trial_id, event_row.event_id, event_row.variant_id),
                {},
            )[event_row.metric_key] = event_row
    rows: list[dict[str, object]] = []
    for key, event_metrics in sorted(event_groups.items()):
        if set(event_metrics) != {lag_key, residual_key}:
            raise ValueError(f"lag--fidelity event 指标不完整：{key}")
        lag = event_metrics[lag_key]
        residual = event_metrics[residual_key]
        rows.append(
            {
                "plot_id": "exp1_lag_tradeoff",
                "panel_id": "lag_tradeoff",
                "session_id": lag.session_id,
                "scenario_id": lag.scenario_id,
                "trial_id": lag.trial_id,
                "event_id": lag.event_id,
                "variant_id": lag.variant_id,
                "point_kind": "event",
                "effective_lag_ms": lag.metric_value,
                "p95_residual_mm": residual.metric_value,
                "lag_q1_ms": None,
                "lag_q3_ms": None,
                "residual_q1_mm": None,
                "residual_q3_mm": None,
                "input_workbook_sha256": lag.input_workbook_sha256,
            }
        )
    summary_groups: dict[str, dict[str, ScenarioSummaryRow]] = {}
    for summary_row in result.scenario_summary:
        if summary_row.scenario_id == "continuous_translation" and summary_row.metric_key in {lag_key, residual_key}:
            summary_groups.setdefault(summary_row.variant_id, {})[summary_row.metric_key] = summary_row
    for variant_id in EXP1_VARIANTS:
        summary_metrics = summary_groups.get(variant_id, {})
        if set(summary_metrics) != {lag_key, residual_key}:
            raise ValueError(f"lag--fidelity summary 指标不完整：{variant_id}")
        lag_summary = summary_metrics[lag_key]
        residual_summary = summary_metrics[residual_key]
        rows.append(
            {
                "plot_id": "exp1_lag_tradeoff",
                "panel_id": "lag_tradeoff",
                "session_id": "",
                "scenario_id": "continuous_translation",
                "trial_id": "",
                "event_id": "summary",
                "variant_id": variant_id,
                "point_kind": "summary",
                "effective_lag_ms": lag_summary.median,
                "p95_residual_mm": residual_summary.median,
                "lag_q1_ms": lag_summary.q1,
                "lag_q3_ms": lag_summary.q3,
                "residual_q1_mm": residual_summary.q1,
                "residual_q3_mm": residual_summary.q3,
                "input_workbook_sha256": lag_summary.input_workbook_sha256,
            }
        )
    return tuple(rows)


def _occlusion_rows(
    result: Exp1AnalysisResult,
    trials: Sequence[Exp1Trial],
) -> tuple[dict[str, object], ...]:
    """生成代表遮挡事件的四系统误差与 output 状态时间线。"""

    key = _representative_event(result, "occlusion_recovery", "occlusion_translation_pninetyfive_mm")
    trial = _find_trial(trials, "occlusion_recovery", key)
    window = _occlusion_window(trial, key[2])
    rows: list[dict[str, object]] = []
    for variant_id in EXP1_VARIANTS:
        series = _series(trial, variant_id)
        indices = _indices(series, window.occlusion_start_ms, window.end_ms)
        errors = _translation_errors(series, indices)
        for sample_index, (index, error) in enumerate(zip(indices, errors)):
            time = float(series.times_ms[index])
            rows.append(
                {
                    "plot_id": "exp1_occlusion_trace",
                    "panel_id": "occlusion",
                    "session_id": trial.session_id,
                    "scenario_id": trial.scenario_id,
                    "trial_id": trial.trial_id,
                    "event_id": key[2],
                    "variant_id": variant_id,
                    "sample_index": sample_index,
                    "time_ms": time - window.occlusion_start_ms,
                    "translation_error_mm": _optional_float(error),
                    "occluded": time < window.visible_start_ms,
                    "has_output_pose": bool(series.has_output_pose[index]),
                    "has_display_pose": bool(series.has_display_pose[index]),
                    "selection_rule": "egoanchor_metric_nearest_event_median",
                    "input_workbook_sha256": trial.workbook_sha256,
                }
            )
    return tuple(rows)


def build_exp1_plot_rows(
    result: Exp1AnalysisResult,
    trials: Iterable[Exp1Trial],
    params: AnalysisParameters,
) -> Exp1PlotRows:
    """在 Stage 2 生成实验一四面板图的全部数据行。

    参数：
        result: 已完成 event-first 计算和场景汇总的实验一结果。
        trials: 从 Stage 1 XLSX 联接得到的完成 trial。
        params: 唯一冻结分析参数。
    """

    materialized = tuple(trials)
    return Exp1PlotRows(
        _head_motion_rows(result, materialized, params),
        _start_stop_rows(result, materialized, params),
        _lag_tradeoff_rows(result),
        _occlusion_rows(result, materialized),
    )


def build_vcd_plot_rows(rows: Iterable[VcdCurvePoint]) -> tuple[dict[str, object], ...]:
    """只投影冻结 P95 tail-risk 曲线，并验证 VCD/random 成对。

    参数：
        rows: Task 8 同时生成的 mean 与 P95 risk-coverage 点。
    """

    selected = tuple(
        row
        for row in rows
        if row.scenario_id == "occlusion_recovery"
        and row.risk_kind == "tail_pninetyfive"
    )
    if not selected:
        raise ValueError("VCD 正式图缺少 P95 tail-risk 曲线")
    groups: dict[tuple[str, int, float], Counter[str]] = {}
    for row in selected:
        key = (row.scenario_id, row.point_index, row.coverage)
        groups.setdefault(key, Counter())[row.reference_kind] += 1
    expected = Counter(("vcd", "random"))
    invalid = [key for key, references in groups.items() if references != expected]
    if invalid:
        raise ValueError(f"VCD 正式图缺少成对参考曲线：point={invalid[0]}")
    return tuple(
        {
            **asdict(row),
            "plot_id": "exp2_vcd_curve",
            "panel_id": row.reference_kind,
        }
        for row in selected
    )


def build_exp2_mechanism_plot_rows(
    rows: Iterable[PairedDeltaRow],
    summaries: Iterable[PairedDeltaSummaryRow],
) -> tuple[dict[str, object], ...]:
    """投影实验二四组件主指标的 Full/Ablated/Delta 配对绘图行。

    参数：
        rows: Stage 2 已完成 exact join 的 paired event 行。
        summaries: Stage 2 已按冻结分位数规则汇总的 paired summary 行。
    """

    primary_metrics = {
        component.component_id: component.primary_metric_keys[0]
        for component in EXP2_COMPONENTS
    }
    selected = [
        row
        for row in rows
        if row.metric_key == primary_metrics.get(row.component_id)
    ]
    if not selected:
        raise ValueError("实验二机制归因图缺少主指标配对行")
    summary_by_key = {
        (row.component_id, row.metric_key): row
        for row in summaries
    }
    result = []
    for row in selected:
        summary = summary_by_key.get((row.component_id, row.metric_key))
        if summary is None or summary.median is None:
            raise ValueError(
                f"实验二机制归因图缺少 Stage 2 差值中位数：{row.component_id}/{row.metric_key}"
            )
        result.append(
            {
                **asdict(row),
                "delta_median": summary.median,
                "plot_id": "exp2_mechanism_attribution",
                "panel_id": row.component_id,
            }
        )
    return tuple(result)


def build_vcd_operating_plot_row(
    result: VcdAnalysisResult,
) -> dict[str, object] | None:
    """把 VCD 分析已经冻结的实际接纳工作点序列化为绘图行。

    参数：
        result: 已计算 actual admitted 统计与集合 lineage 的 VCD 结果。
    """

    if (
        result.operating_eligible_count <= 0
        or result.operating_accepted_count <= 0
        or result.operating_tail_risk_mm is None
    ):
        return None
    return {
        "scenario_id": "occlusion_recovery",
        "reference_kind": "actual_admitted",
        "risk_kind": "operating_pninetyfive",
        "point_index": 0,
        "threshold": None,
        "coverage": result.operating_coverage,
        "risk_mm": result.operating_tail_risk_mm,
        "group_count": result.operating_accepted_count,
        "cumulative_count": result.operating_accepted_count,
        "coverage_denominator": result.operating_eligible_count,
        "input_workbook_sha256": result.operating_input_workbook_sha256,
        "plot_id": "exp2_vcd_curve",
        "panel_id": "actual_operating",
    }


__all__ = [
    "Exp1PlotRows",
    "build_exp1_plot_rows",
    "build_exp2_mechanism_plot_rows",
    "build_vcd_operating_plot_row",
    "build_vcd_plot_rows",
]

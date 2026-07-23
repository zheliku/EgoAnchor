"""从五本 Stage 1 XLSX 计算实验一/二论文指标。"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from scipy.spatial.transform import Rotation, Slerp  # type: ignore[import-untyped]

from ..preprocess import (
    CURRENT_VARIANT_MATRIX_ID,
    FORMAL_METHODS,
    FORMAL_VARIANTS,
)
from .settings import PaperSettings, load_settings
from .xlsx import iter_rows, workbook_sha256


FULL_VARIANT = "EgoAnchor"
"""正式论文中完整 Linear/SLERP 系统的 variant ID。"""

CAUSAL_PREDICTION_VARIANT = "EgoAnchor Causal Prediction"
"""当前正式批次保留的有限时域因果预测配对 variant ID。"""

METHODS = ("Arrival-Hold", "Capture-Hold", "One-Euro Anchor", FULL_VARIANT)
"""实验一正式比较的四种系统配置。"""

NO_STATIC_LOCK = "EgoAnchor w/o StaticLock"
NO_VCD = "EgoAnchor w/o VCD"
NO_TEMPORAL_SYNTHESIS = "EgoAnchor w/o temporal synthesis"

TEMPORAL_STRATEGY_VARIANTS = (
    NO_TEMPORAL_SYNTHESIS,
    CAUSAL_PREDICTION_VARIANT,
    NO_STATIC_LOCK,
)
"""图 3(d) 中 Direct、Causal 与 Buffered 的固定 runtime 顺序。"""


def _validate_workbook_runtime_contract(workbook: Path) -> None:
    """确认 Stage 1 工作簿来自当前九路矩阵，拒绝把 v3 归档数据写入新论文。"""

    matrix_rows = [
        row
        for row in iter_rows(
            workbook,
            "metadata_kv",
            ("document", "json_path", "value_json"),
        )
        if row.get("document") == "manifest.json"
        and row.get("json_path") == "variant_matrix_id"
    ]
    if len(matrix_rows) != 1:
        raise ValueError(f"Stage 1 工作簿必须包含唯一 variant_matrix_id：{workbook}")
    try:
        matrix_id = json.loads(str(matrix_rows[0]["value_json"]))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"Stage 1 工作簿的 variant_matrix_id 无法解析：{workbook}") from exc
    if matrix_id != CURRENT_VARIANT_MATRIX_ID:
        raise ValueError(
            f"Stage 1 工作簿必须来自 {CURRENT_VARIANT_MATRIX_ID}，"
            f"当前为 {matrix_id or '<empty>'}：{workbook}"
        )

    columns = (
        "variant_id",
        "variant_label",
        "world_alignment_mode",
        "uses_capture_time_alignment",
        "uses_vcd_admission",
        "uses_temporal_synthesis",
        "uses_static_lock",
        "uses_low_score_reacquire",
        "uses_server_reacquire",
        "motion_model",
        "smoothing_strategy",
        "quality_gate",
    )
    rows = list(iter_rows(workbook, "variants", columns))
    indexed = {str(row.get("variant_id") or ""): row for row in rows}
    if len(indexed) != len(rows) or set(indexed) != set(FORMAL_VARIANTS):
        raise ValueError(
            f"Stage 1 工作簿的九路 runtime 集合与 {CURRENT_VARIANT_MATRIX_ID} 不一致：{workbook}"
        )
    for variant_id, expected_definition in FORMAL_VARIANTS.items():
        row = indexed[variant_id]
        definition = (
            str(row.get("world_alignment_mode") or ""),
            _truthy(row.get("uses_capture_time_alignment")),
            _truthy(row.get("uses_vcd_admission")),
            _truthy(row.get("uses_temporal_synthesis")),
            _truthy(row.get("uses_static_lock")),
            _truthy(row.get("uses_low_score_reacquire")),
            _truthy(row.get("uses_server_reacquire")),
        )
        method = (
            str(row.get("motion_model") or ""),
            str(row.get("smoothing_strategy") or ""),
            str(row.get("quality_gate") or ""),
        )
        if str(row.get("variant_label") or "") != variant_id:
            raise ValueError(f"Stage 1 工作簿的 variant label 不一致：{variant_id}: {workbook}")
        if definition != expected_definition or method != FORMAL_METHODS[variant_id]:
            raise ValueError(f"Stage 1 工作簿的 runtime 定义不一致：{variant_id}: {workbook}")


@dataclass(frozen=True, slots=True)
class PaperResults:
    """保存论文图、表和正文需要的全部片段级结果。"""

    workbook_sha256: Mapping[str, str]
    """五本只读 Stage 1 XLSX 的文件摘要。"""

    static_segments: Mapping[str, tuple[Mapping[str, Any], ...]]
    """静止头动片段的中心化、绝对和帧间增量 P95。"""

    translation_segments: Mapping[str, tuple[Mapping[str, Any], ...]]
    """持续平移片段的有效时延和对齐 RMSE。"""

    rotation_segments: Mapping[str, tuple[Mapping[str, Any], ...]]
    """持续旋转片段的有效角时延和对齐角 RMSE。"""

    occlusion_episodes: Mapping[str, tuple[Mapping[str, Any], ...]]
    """遮挡过程的平移 P95 与灾难性失效标识。"""

    transition_segments: Mapping[str, tuple[Mapping[str, Any], ...]]
    """起停片段的显示响应代价。"""

    stop_segments: Mapping[str, tuple[Mapping[str, Any], ...]]
    """停止边界后的前向过冲、反向回动与稳定时间。"""

    correction_segments: Mapping[str, tuple[Mapping[str, Any], ...]]
    """新候选生效边界处的显示位置与旋转步长。"""

    capture_alignment: tuple[Mapping[str, Any], ...]
    """同一候选 capture-time 与 arrival-time 世界复合的片段级比较。"""

    vcd_risk_coverage: tuple[Mapping[str, Any], ...]
    """VCD 分数诱导的 event 级风险--覆盖率阶梯曲线。"""

    vcd_aurc_segments: tuple[Mapping[str, Any], ...]
    """每个遮挡 event 的 AURC、全覆盖风险和候选排除审计。"""

    performance: Mapping[str, float | int]
    """Python 候选处理和发布间隔审计。"""


def segment_identity(row: Mapping[str, Any]) -> tuple[str, str, str]:
    """返回跨配置严格配对使用的片段身份。"""

    return str(row["session_id"]), str(row["trial_id"]), str(row["segment_id"])


def paired_metric_matrix(
    rows: Mapping[str, tuple[Mapping[str, Any], ...]],
    variants: Sequence[str],
    keys: Sequence[str],
) -> np.ndarray:
    """按片段身份组成 ``episode x variant x metric`` 矩阵。"""

    if not variants:
        raise ValueError("严格配对至少需要一个配置")
    per_variant: dict[str, dict[tuple[str, str, str], tuple[float, ...]]] = {}
    for variant in variants:
        values: dict[tuple[str, str, str], tuple[float, ...]] = {}
        for row in rows.get(variant, ()):
            identity = segment_identity(row)
            if identity in values:
                raise ValueError(f"片段键重复：{variant}/{identity}")
            metrics = tuple(float(row[key]) for key in keys)
            if all(np.isfinite(metrics)):
                values[identity] = metrics
        per_variant[variant] = values
    expected = set(per_variant[variants[0]])
    if not expected or any(set(per_variant[variant]) != expected for variant in variants[1:]):
        counts = ", ".join(f"{variant}={len(per_variant[variant])}" for variant in variants)
        raise ValueError(f"配置片段配对不完整：{counts}")
    return np.asarray(
        [
            [per_variant[variant][identity] for variant in variants]
            for identity in sorted(expected)
        ],
        dtype=float,
    )


def _truthy(value: Any) -> bool:
    """统一解释 XLSX 中的布尔值。"""

    return value is True or (isinstance(value, str) and value.lower() == "true") or value == 1


def _finite_vector(row: Mapping[str, Any], prefix: str, suffixes: Sequence[str]) -> np.ndarray | None:
    """读取固定长度向量；缺失或非有限值返回 ``None``。"""

    try:
        vector = np.asarray([float(row[f"{prefix}_{suffix}"]) for suffix in suffixes], dtype=float)
    except (KeyError, TypeError, ValueError):
        return None
    return vector if np.isfinite(vector).all() else None


def _quantile(values: np.ndarray, probability: float) -> float:
    """使用 NumPy linear 方法计算分位数。"""

    if values.size == 0:
        return math.nan
    return float(np.quantile(values, probability, method="linear"))


def risk_coverage_curve(
    scores: Sequence[float],
    risks_mm: Sequence[float],
) -> tuple[tuple[Mapping[str, float | int], ...], float]:
    """按分数降序计算 tie-aware 风险--覆盖率曲线及阶梯 AURC。

    同分候选不可拆分；该函数以同分组整体加入后的累计平均风险覆盖该组
    带来的 coverage 增量。VCD 分数只用于诱导顺序，不解释为正确概率。
    """

    score_array = np.asarray(scores, dtype=float)
    risk_array = np.asarray(risks_mm, dtype=float)
    if score_array.ndim != 1 or risk_array.ndim != 1 or score_array.size != risk_array.size:
        raise ValueError("VCD 分数与风险必须是一一对应的一维序列")
    if score_array.size == 0:
        raise ValueError("risk-coverage 至少需要一个可评价候选")
    if not np.isfinite(score_array).all() or np.any((score_array < 0.0) | (score_array > 1.0)):
        raise ValueError("VCD 分数必须是 [0,1] 内的有限值")
    if not np.isfinite(risk_array).all() or np.any(risk_array < 0.0):
        raise ValueError("候选风险必须是非负有限毫米值")

    order = np.argsort(-score_array, kind="stable")
    sorted_scores = score_array[order]
    sorted_risks = risk_array[order]
    total = int(score_array.size)
    retained = 0
    cumulative_risk = 0.0
    previous_coverage = 0.0
    aurc_mm = 0.0
    rows: list[Mapping[str, float | int]] = []
    index = 0
    while index < total:
        threshold = float(sorted_scores[index])
        end = index + 1
        while end < total and float(sorted_scores[end]) == threshold:
            end += 1
        tie_count = end - index
        retained += tie_count
        cumulative_risk = math.fsum(
            (cumulative_risk, math.fsum(float(value) for value in sorted_risks[index:end]))
        )
        coverage = retained / total
        selective_risk_mm = cumulative_risk / retained
        aurc_mm += (coverage - previous_coverage) * selective_risk_mm
        rows.append(
            {
                "score_threshold": threshold,
                "score_tie_count": tie_count,
                "retained_candidates": retained,
                "evaluable_candidates": total,
                "coverage": coverage,
                "selective_risk_mm": selective_risk_mm,
            }
        )
        previous_coverage = coverage
        index = end
    return tuple(rows), float(aurc_mm)


def _valid_event(row: Mapping[str, Any]) -> bool:
    """排除未处于人工动作片段内的空 event 行。"""

    event_id = row.get("event_id")
    return event_id not in {None, "", "@empty-text"}


def eligible_trials(workbooks: Sequence[Path]) -> frozenset[tuple[str, str]]:
    """只保留最终以 trial_ended 结束、之后没有被作废的 trial。"""

    grouped: defaultdict[tuple[str, str], list[tuple[float, str]]] = defaultdict(list)
    columns = (
        "session_id",
        "trial_id",
        "event",
        "event_type",
        "mono_ms",
        "created_unix_ms",
        "event_row_id",
    )
    row_index = 0
    for workbook in workbooks:
        for row in iter_rows(workbook, "events", columns):
            row_index += 1
            session_id = str(row.get("session_id") or "")
            trial_id = str(row.get("trial_id") or "")
            event_name = str(row.get("event") or row.get("event_type") or "")
            if not session_id or not trial_id or not event_name:
                continue
            order = _event_order(row, row_index)
            grouped[(session_id, trial_id)].append((order, event_name))

    eligible: set[tuple[str, str]] = set()
    for key, events in grouped.items():
        ended = [item for item in events if item[1] == "trial_ended"]
        if not ended:
            continue
        final_end = max(item[0] for item in ended)
        if any(name == "trial_rejected" and order > final_end for order, name in events):
            continue
        eligible.add(key)
    if not eligible:
        raise ValueError("五本 workbook 没有最终完成且未被作废的 trial")
    return frozenset(eligible)


def _event_order(row: Mapping[str, Any], fallback: int) -> float:
    """按 Unity 单调时钟、创建时钟和行号生成稳定事件顺序。"""

    for field in ("mono_ms", "created_unix_ms"):
        try:
            value = float(row[field])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(value):
            return value
    return float(fallback)


def _trial_is_eligible(
    row: Mapping[str, Any],
    eligible_trials: frozenset[tuple[str, str]],
) -> bool:
    """判断数据行是否属于最终有效 trial。"""

    return (str(row.get("session_id") or ""), str(row.get("trial_id") or "")) in eligible_trials


def _segment_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    """用 session、trial、event 和 variant 保持跨 workbook 片段唯一。"""

    return (
        str(row.get("session_id", "")),
        str(row.get("trial_id", "")),
        str(row.get("event_id", "")),
        str(row.get("variant_id", "")),
    )


def _scenario_matches(value: Any, token: str) -> bool:
    """允许代码和采集配置在 6DoF 拼写上存在大小写差异。"""

    return token in str(value or "").lower().replace("-", "_")


_RENDER_COLUMNS = (
    "session_id",
    "scenario_id",
    "trial_id",
    "event_id",
    "variant_id",
    "render_mono_ms",
    "has_display_pose",
    "reference_pose_valid",
    "display_pos_x_m",
    "display_pos_y_m",
    "display_pos_z_m",
    "reference_pos_x_m",
    "reference_pos_y_m",
    "reference_pos_z_m",
    "display_rot_x",
    "display_rot_y",
    "display_rot_z",
    "display_rot_w",
    "reference_rot_x",
    "reference_rot_y",
    "reference_rot_z",
    "reference_rot_w",
)


def _collect_render(
    workbooks: Sequence[Path],
    eligible_trials: frozenset[tuple[str, str]],
) -> Mapping[
    tuple[str, str, str, str, str],
    list[tuple[float, np.ndarray, np.ndarray, np.ndarray, np.ndarray]],
]:
    """读取有效 display/reference 行并按动作片段分组。"""

    grouped: defaultdict[
        tuple[str, str, str, str, str],
        list[tuple[float, np.ndarray, np.ndarray, np.ndarray, np.ndarray]],
    ] = defaultdict(list)
    for workbook in workbooks:
        for row in iter_rows(workbook, "unity_render", _RENDER_COLUMNS):
            if (
                not _valid_event(row)
                or not _trial_is_eligible(row, eligible_trials)
                or not _truthy(row.get("has_display_pose"))
            ):
                continue
            if not _truthy(row.get("reference_pose_valid")):
                continue
            display_position = _finite_vector(row, "display_pos", ("x_m", "y_m", "z_m"))
            reference_position = _finite_vector(row, "reference_pos", ("x_m", "y_m", "z_m"))
            display_rotation = _finite_vector(row, "display_rot", ("x", "y", "z", "w"))
            reference_rotation = _finite_vector(row, "reference_rot", ("x", "y", "z", "w"))
            try:
                time_ms = float(row["render_mono_ms"])
            except (KeyError, TypeError, ValueError):
                continue
            if any(
                value is None
                for value in (
                    display_position,
                    reference_position,
                    display_rotation,
                    reference_rotation,
                )
            ):
                continue
            key = _segment_key(row)
            scenario = str(row.get("scenario_id", ""))
            grouped[(scenario, *key)].append(
                (
                    time_ms,
                    display_position,  # type: ignore[arg-type]
                    reference_position,  # type: ignore[arg-type]
                    display_rotation,  # type: ignore[arg-type]
                    reference_rotation,  # type: ignore[arg-type]
                )
            )
    return grouped


def _event_roles(
    workbooks: Sequence[Path],
    eligible_trials: frozenset[tuple[str, str]],
) -> Mapping[tuple[str, str, str], str]:
    """从事件总表恢复每个动作片段的人工角色。"""

    roles: dict[tuple[str, str, str], str] = {}
    event_columns = ("event_row_id", "session_id", "trial_id", "event_id")
    payload_columns = ("event_row_id", "event_role")
    for workbook in workbooks:
        contexts = {
            str(row["event_row_id"]): (
                str(row.get("session_id", "")),
                str(row.get("trial_id", "")),
                str(row.get("event_id", "")),
            )
            for row in iter_rows(workbook, "events", event_columns)
            if _valid_event(row) and _trial_is_eligible(row, eligible_trials)
        }
        for row in iter_rows(workbook, "event_payload", payload_columns):
            role = str(row.get("event_role") or "")
            context = contexts.get(str(row.get("event_row_id", "")))
            if context is None or not role:
                continue
            previous = roles.setdefault(context, role)
            if previous != role:
                raise ValueError(f"同一动作片段存在冲突 event_role：{context}: {previous} / {role}")
    return roles


def _collect_correction_metrics(
    workbooks: Sequence[Path],
    eligible_trials: frozenset[tuple[str, str]],
) -> Mapping[str, tuple[Mapping[str, Any], ...]]:
    """按 source frame 切换识别候选生效边界，并计算实际显示步长。"""

    columns = (
        "session_id",
        "trial_id",
        "event_id",
        "variant_id",
        "render_mono_ms",
        "source_frame_id",
        "has_display_pose",
        "display_pos_x_m",
        "display_pos_y_m",
        "display_pos_z_m",
        "display_rot_x",
        "display_rot_y",
        "display_rot_z",
        "display_rot_w",
    )
    grouped: defaultdict[
        tuple[str, str, str, str],
        list[tuple[float, int, np.ndarray, np.ndarray]],
    ] = defaultdict(list)
    for workbook in workbooks:
        for row in iter_rows(workbook, "unity_render", columns):
            if (
                not _valid_event(row)
                or not _trial_is_eligible(row, eligible_trials)
                or not _truthy(row.get("has_display_pose"))
            ):
                continue
            position = _finite_vector(row, "display_pos", ("x_m", "y_m", "z_m"))
            rotation = _finite_vector(row, "display_rot", ("x", "y", "z", "w"))
            try:
                time_ms = float(row["render_mono_ms"])
                source_frame_id = int(row["source_frame_id"])
            except (KeyError, TypeError, ValueError):
                continue
            if position is None or rotation is None:
                continue
            grouped[_segment_key(row)].append((time_ms, source_frame_id, position, rotation))

    metrics: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for (session_id, trial_id, event_id, variant_id), rows in grouped.items():
        ordered = sorted(rows, key=lambda item: item[0])
        position_steps: list[float] = []
        rotation_steps: list[float] = []
        for previous, current in zip(ordered, ordered[1:]):
            if previous[1] < 0 or current[1] < 0 or previous[1] == current[1]:
                continue
            position_steps.append(1000.0 * float(np.linalg.norm(current[2] - previous[2])))
            relative = Rotation.from_quat(previous[3]).inv() * Rotation.from_quat(current[3])
            rotation_steps.append(float(np.degrees(relative.magnitude())))
        if not position_steps:
            continue
        metrics[variant_id].append(
            {
                "session_id": session_id,
                "trial_id": trial_id,
                "segment_id": event_id,
                "position_step_p95_mm": _quantile(np.asarray(position_steps), 0.95),
                "rotation_step_p95_deg": _quantile(np.asarray(rotation_steps), 0.95),
                "boundary_count": len(position_steps),
            }
        )
    return {key: tuple(value) for key, value in sorted(metrics.items())}


def _sorted_arrays(
    rows: Iterable[tuple[float, np.ndarray, np.ndarray, np.ndarray, np.ndarray]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """按时间排序并去除同一 render 时刻的重复样本。"""

    ordered = sorted(rows, key=lambda item: item[0])
    times = np.asarray([item[0] for item in ordered], dtype=float)
    unique_times, indices = np.unique(times, return_index=True)
    display_positions = np.asarray([ordered[index][1] for index in indices], dtype=float)
    reference_positions = np.asarray([ordered[index][2] for index in indices], dtype=float)
    display_rotations = np.asarray([ordered[index][3] for index in indices], dtype=float)
    reference_rotations = np.asarray([ordered[index][4] for index in indices], dtype=float)
    return unique_times, display_positions, reference_positions, display_rotations, reference_rotations


def _lag_grid(settings: PaperSettings) -> np.ndarray:
    """构造包含上界的冻结有效时延网格。"""

    return np.arange(
        settings.lag_minimum_ms,
        settings.lag_maximum_ms + settings.lag_step_ms * 0.5,
        settings.lag_step_ms,
    )


def _translation_lag(
    times: np.ndarray,
    display: np.ndarray,
    reference: np.ndarray,
    settings: PaperSettings,
) -> tuple[float, float]:
    """搜索使 display 与历史 reference 位置 RMSE 最小的有效时延。"""

    best = (math.inf, math.nan)
    for lag_ms in _lag_grid(settings):
        query_times = times - lag_ms
        valid = (query_times >= times[0]) & (query_times <= times[-1])
        if int(valid.sum()) < settings.lag_minimum_samples:
            continue
        interpolated = np.column_stack(
            [np.interp(query_times[valid], times, reference[:, axis]) for axis in range(3)]
        )
        distances_mm = 1000.0 * np.linalg.norm(display[valid] - interpolated, axis=1)
        rmse_mm = float(np.sqrt(np.mean(np.square(distances_mm))))
        if rmse_mm < best[0]:
            best = (rmse_mm, float(lag_ms))
    return best[1], best[0]


def _rotation_lag(
    times: np.ndarray,
    display: np.ndarray,
    reference: np.ndarray,
    settings: PaperSettings,
) -> tuple[float, float]:
    """使用四元数 Slerp 搜索角 RMSE 最小的有效时延。"""

    display = display / np.linalg.norm(display, axis=1, keepdims=True)
    reference = reference / np.linalg.norm(reference, axis=1, keepdims=True)
    display_rotation = Rotation.from_quat(display)
    reference_slerp = Slerp(times, Rotation.from_quat(reference))
    best = (math.inf, math.nan)
    for lag_ms in _lag_grid(settings):
        query_times = times - lag_ms
        valid = (query_times >= times[0]) & (query_times <= times[-1])
        if int(valid.sum()) < settings.lag_minimum_samples:
            continue
        relative = display_rotation[valid].inv() * reference_slerp(query_times[valid])
        errors_deg = np.degrees(relative.magnitude())
        rmse_deg = float(np.sqrt(np.mean(np.square(errors_deg))))
        if rmse_deg < best[0]:
            best = (rmse_deg, float(lag_ms))
    return best[1], best[0]


def _first_sustained(
    times: np.ndarray,
    values: np.ndarray,
    threshold: float,
    persistence_ms: float,
) -> int | None:
    """返回首次持续超过阈值的样本索引。"""

    above = values >= threshold
    for index in np.flatnonzero(above):
        end = int(np.searchsorted(times, times[index] + persistence_ms, side="left"))
        if end >= len(times):
            break
        if bool(above[index : end + 1].all()):
            return int(index)
    return None


def _transition_response(
    times: np.ndarray,
    display: np.ndarray,
    reference: np.ndarray,
    settings: PaperSettings,
) -> float:
    """按冻结的 250 ms 基线、5 mm、100 ms 持续条件计算响应。"""

    elapsed = times - times[0]
    baseline = elapsed <= settings.transition_baseline_ms
    if not bool(baseline.any()):
        return math.nan
    display_origin = np.median(display[baseline], axis=0)
    reference_origin = np.median(reference[baseline], axis=0)
    display_displacement = 1000.0 * np.linalg.norm(display - display_origin, axis=1)
    reference_displacement = 1000.0 * np.linalg.norm(reference - reference_origin, axis=1)
    reference_index = _first_sustained(
        times,
        reference_displacement,
        settings.transition_displacement_mm,
        settings.transition_persistence_ms,
    )
    display_index = _first_sustained(
        times,
        display_displacement,
        settings.transition_displacement_mm,
        settings.transition_persistence_ms,
    )
    if reference_index is None or display_index is None:
        return math.nan
    return max(0.0, float(times[display_index] - times[reference_index]))


def _first_sustained_below(
    times: np.ndarray,
    values: np.ndarray,
    threshold: float,
    persistence_ms: float,
) -> int | None:
    """返回首次持续低于阈值的样本索引。"""

    below = values <= threshold
    for index in np.flatnonzero(below):
        end = int(np.searchsorted(times, times[index] + persistence_ms, side="left"))
        if end >= len(times):
            break
        if bool(below[index : end + 1].all()):
            return int(index)
    return None


def _stop_costs(
    times: np.ndarray,
    display: np.ndarray,
    incoming_direction: np.ndarray | None,
    settings: PaperSettings,
) -> tuple[float, float, float]:
    """计算停止后的前向过冲、反向回动和到最终显示位置的稳定时间。"""

    elapsed = times - times[0]
    if elapsed[-1] < settings.transition_baseline_ms + settings.transition_persistence_ms:
        return math.nan, math.nan, math.nan
    final_window = elapsed >= max(0.0, elapsed[-1] - settings.transition_baseline_ms)
    if not bool(final_window.any()):
        return math.nan, math.nan, math.nan
    final_position = np.median(display[final_window], axis=0)
    settling_distance_mm = 1000.0 * np.linalg.norm(display - final_position, axis=1)
    settled_index = _first_sustained_below(
        times,
        settling_distance_mm,
        settings.transition_displacement_mm,
        settings.transition_persistence_ms,
    )
    settling_ms = math.nan if settled_index is None else float(times[settled_index] - times[0])

    if incoming_direction is None:
        return math.nan, math.nan, settling_ms
    norm = float(np.linalg.norm(incoming_direction))
    if not np.isfinite(norm) or norm <= 1e-9:
        return math.nan, math.nan, settling_ms
    direction = incoming_direction / norm
    projected_mm = 1000.0 * ((display - display[0]) @ direction)
    peak_index = int(np.argmax(projected_mm))
    peak = max(0.0, float(projected_mm[peak_index]))
    final_projection = float(np.median(projected_mm[final_window]))
    reverse_return = max(0.0, peak - final_projection)
    return peak, reverse_return, settling_ms


def _render_metrics(
    render: Mapping[tuple[str, str, str, str, str], list[tuple[float, np.ndarray, np.ndarray, np.ndarray, np.ndarray]]],
    event_roles: Mapping[tuple[str, str, str], str],
    settings: PaperSettings,
) -> tuple[
    Mapping[str, tuple[Mapping[str, Any], ...]],
    Mapping[str, tuple[Mapping[str, Any], ...]],
    Mapping[str, tuple[Mapping[str, Any], ...]],
    Mapping[str, tuple[Mapping[str, Any], ...]],
    Mapping[str, tuple[Mapping[str, Any], ...]],
    Mapping[str, tuple[Mapping[str, Any], ...]],
]:
    """一次遍历生成六类 render 片段指标。"""

    static: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    translation: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    rotation: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    occlusion: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    transition: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    stop: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    incoming_directions: dict[tuple[str, str, str], np.ndarray] = {}
    ordered_render = sorted(render.items(), key=lambda item: min(row[0] for row in item[1]))
    for key, rows in ordered_render:
        scenario, session_id, trial_id, event_id, variant_id = key
        times, display, reference, display_rotation, reference_rotation = _sorted_arrays(rows)
        identity = {"session_id": session_id, "trial_id": trial_id, "segment_id": event_id}
        if _scenario_matches(scenario, "static_head_motion"):
            errors = display - reference
            centered = errors - np.median(errors, axis=0)
            increments = 1000.0 * np.linalg.norm(np.diff(display, axis=0), axis=1)
            static[variant_id].append(
                {
                    **identity,
                    "centered_p95_mm": _quantile(1000.0 * np.linalg.norm(centered, axis=1), 0.95),
                    "absolute_p95_mm": _quantile(1000.0 * np.linalg.norm(errors, axis=1), 0.95),
                    "frame_increment_p95_mm": _quantile(increments, 0.95),
                }
            )
        elif _scenario_matches(scenario, "continuous_translation"):
            lag, residual = _translation_lag(times, display, reference, settings)
            translation[variant_id].append(
                {**identity, "effective_lag_ms": lag, "aligned_rmse_mm": residual}
            )
        elif _scenario_matches(scenario, "continuous_rotation"):
            lag, residual = _rotation_lag(times, display_rotation, reference_rotation, settings)
            rotation[variant_id].append(
                {**identity, "effective_lag_ms": lag, "aligned_rmse_deg": residual}
            )
        elif _scenario_matches(scenario, "occlusion_recovery"):
            if event_roles.get((session_id, trial_id, event_id)) != "occlusion_started":
                continue
            errors_mm = 1000.0 * np.linalg.norm(display - reference, axis=1)
            p95 = _quantile(errors_mm, 0.95)
            maximum = float(np.max(errors_mm)) if errors_mm.size else math.nan
            occlusion[variant_id].append(
                {
                    **identity,
                    "translation_p95_mm": p95,
                    "translation_max_mm": maximum,
                    "catastrophic_gt40": maximum > settings.occlusion_catastrophic_mm,
                }
            )
        elif _scenario_matches(scenario, "start_stop"):
            role = event_roles.get((session_id, trial_id, event_id))
            direction_key = (session_id, trial_id, variant_id)
            if role == "transition_started":
                incoming_directions[direction_key] = reference[-1] - reference[0]
                transition[variant_id].append(
                    {
                        **identity,
                        "response_ms": _transition_response(times, display, reference, settings),
                    }
                )
            elif role == "transition_stopped":
                overshoot, reverse_return, settling = _stop_costs(
                    times,
                    display,
                    incoming_directions.get(direction_key),
                    settings,
                )
                stop[variant_id].append(
                    {
                        **identity,
                        "forward_overshoot_mm": overshoot,
                        "reverse_return_mm": reverse_return,
                        "settling_time_ms": settling,
                    }
                )
    normalize = lambda rows: {key: tuple(value) for key, value in sorted(rows.items())}
    return (
        normalize(static),
        normalize(translation),
        normalize(rotation),
        normalize(occlusion),
        normalize(transition),
        normalize(stop),
    )


def _capture_alignment(
    workbooks: Sequence[Path],
    eligible_trials: frozenset[tuple[str, str]],
) -> tuple[Mapping[str, Any], ...]:
    """直接比较完整系统同一 raw candidate 的 capture/arrival 世界复合误差。"""

    references: dict[tuple[str, int], np.ndarray] = {}
    reference_columns = (
        "session_id",
        "frame_id",
        "reference_pose_valid",
        "reference_pos_x_m",
        "reference_pos_y_m",
        "reference_pos_z_m",
    )
    for workbook in workbooks:
        for row in iter_rows(workbook, "unity_reference", reference_columns):
            if not _truthy(row.get("reference_pose_valid")):
                continue
            position = _finite_vector(row, "reference_pos", ("x_m", "y_m", "z_m"))
            try:
                frame_id = int(row["frame_id"])
            except (KeyError, TypeError, ValueError):
                continue
            if position is not None:
                references[(str(row.get("session_id", "")), frame_id)] = position

    grouped: defaultdict[tuple[str, str, str], list[tuple[float, float]]] = defaultdict(list)
    admission_columns = (
        "session_id",
        "scenario_id",
        "trial_id",
        "event_id",
        "variant_id",
        "frame_id",
        "has_aligned_raw",
        "has_arrival_time_raw",
        "aligned_raw_pos_x_m",
        "aligned_raw_pos_y_m",
        "aligned_raw_pos_z_m",
        "arrival_time_raw_pos_x_m",
        "arrival_time_raw_pos_y_m",
        "arrival_time_raw_pos_z_m",
    )
    for workbook in workbooks:
        for row in iter_rows(workbook, "unity_admission", admission_columns):
            if (
                row.get("variant_id") != FULL_VARIANT
                or not _valid_event(row)
                or not _trial_is_eligible(row, eligible_trials)
            ):
                continue
            if not _scenario_matches(row.get("scenario_id"), "static_head_motion"):
                continue
            if not _truthy(row.get("has_aligned_raw")) or not _truthy(row.get("has_arrival_time_raw")):
                continue
            aligned = _finite_vector(row, "aligned_raw_pos", ("x_m", "y_m", "z_m"))
            arrival = _finite_vector(row, "arrival_time_raw_pos", ("x_m", "y_m", "z_m"))
            try:
                frame_id = int(row["frame_id"])
            except (KeyError, TypeError, ValueError):
                continue
            reference = references.get((str(row.get("session_id", "")), frame_id))
            if aligned is None or arrival is None or reference is None:
                continue
            key = (str(row.get("session_id", "")), str(row.get("trial_id", "")), str(row["event_id"]))
            grouped[key].append(
                (
                    1000.0 * float(np.linalg.norm(aligned - reference)),
                    1000.0 * float(np.linalg.norm(arrival - reference)),
                )
            )
    output: list[Mapping[str, Any]] = []
    for (session_id, trial_id, segment_id), values in sorted(grouped.items()):
        array = np.asarray(values, dtype=float)
        capture_p95 = _quantile(array[:, 0], 0.95)
        arrival_p95 = _quantile(array[:, 1], 0.95)
        output.append(
            {
                "session_id": session_id,
                "trial_id": trial_id,
                "segment_id": segment_id,
                "capture_p95_mm": capture_p95,
                "arrival_p95_mm": arrival_p95,
                "paired_reduction_mm": arrival_p95 - capture_p95,
                "n_candidates": int(len(array)),
            }
        )
    return tuple(output)


def _vcd_risk_coverage(
    workbooks: Sequence[Path],
    eligible_trials: frozenset[tuple[str, str]],
    event_roles: Mapping[tuple[str, str, str], str],
) -> tuple[tuple[Mapping[str, Any], ...], tuple[Mapping[str, Any], ...]]:
    """计算 VCD 连续分数的 event 级风险--覆盖率和 AURC。

    风险只使用完整 EgoAnchor 的 capture-time aligned raw pose 与同 frame
    平台参考之间的平移误差。冻结 admission 决策不参与筛选，以免只评价已被
    阈值接纳的候选而产生选择偏差。
    """

    references: dict[tuple[str, int], np.ndarray] = {}
    reference_columns = (
        "session_id",
        "frame_id",
        "reference_pose_valid",
        "reference_pos_x_m",
        "reference_pos_y_m",
        "reference_pos_z_m",
    )
    for workbook in workbooks:
        for row in iter_rows(workbook, "unity_reference", reference_columns):
            if not _truthy(row.get("reference_pose_valid")):
                continue
            position = _finite_vector(row, "reference_pos", ("x_m", "y_m", "z_m"))
            try:
                frame_id = int(row["frame_id"])
            except (KeyError, TypeError, ValueError):
                continue
            if position is None:
                continue
            key = (str(row.get("session_id") or ""), frame_id)
            previous = references.get(key)
            if previous is not None and not np.allclose(previous, position, rtol=0.0, atol=1e-9):
                raise ValueError(f"同一 frame 存在冲突平台参考：{key}")
            references[key] = position

    grouped: defaultdict[tuple[str, str, str], list[tuple[float, float]]] = defaultdict(list)
    candidate_rows: defaultdict[tuple[str, str, str], int] = defaultdict(int)
    excluded_rows: defaultdict[tuple[str, str, str], int] = defaultdict(int)
    seen_candidates: set[tuple[str, str, str, str]] = set()
    admission_columns = (
        "session_id",
        "scenario_id",
        "trial_id",
        "event_id",
        "candidate_id",
        "variant_id",
        "frame_id",
        "world_alignment_mode",
        "has_aligned_raw",
        "aligned_raw_pos_x_m",
        "aligned_raw_pos_y_m",
        "aligned_raw_pos_z_m",
        "vcd_score",
    )
    for workbook in workbooks:
        for row in iter_rows(workbook, "unity_admission", admission_columns):
            if (
                row.get("variant_id") != FULL_VARIANT
                or not _valid_event(row)
                or not _trial_is_eligible(row, eligible_trials)
                or not _scenario_matches(row.get("scenario_id"), "occlusion_recovery")
            ):
                continue
            session_id = str(row.get("session_id") or "")
            trial_id = str(row.get("trial_id") or "")
            segment_id = str(row.get("event_id") or "")
            segment = (session_id, trial_id, segment_id)
            if event_roles.get(segment) != "occlusion_started":
                continue
            if str(row.get("world_alignment_mode") or "") != "CaptureTime":
                raise ValueError(f"完整 EgoAnchor 的 VCD 风险候选不是 capture-time 对齐：{segment}")
            candidate_id = str(row.get("candidate_id") or "")
            if not candidate_id:
                raise ValueError(f"VCD 风险候选缺少 candidate_id：{segment}")
            candidate_key = (*segment, candidate_id)
            if candidate_key in seen_candidates:
                raise ValueError(f"VCD 风险候选重复：{candidate_key}")
            seen_candidates.add(candidate_key)
            candidate_rows[segment] += 1

            aligned = (
                _finite_vector(row, "aligned_raw_pos", ("x_m", "y_m", "z_m"))
                if _truthy(row.get("has_aligned_raw"))
                else None
            )
            try:
                frame_id = int(row["frame_id"])
            except (KeyError, TypeError, ValueError):
                frame_id = -1
            reference = references.get((session_id, frame_id))
            if aligned is None or reference is None:
                excluded_rows[segment] += 1
                continue
            try:
                score = float(row["vcd_score"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"可评价候选缺少 VCD 分数：{candidate_key}") from exc
            if not math.isfinite(score) or not 0.0 <= score <= 1.0:
                raise ValueError(f"可评价候选的 VCD 分数非法：{candidate_key}: {score}")
            risk_mm = 1000.0 * float(np.linalg.norm(aligned - reference))
            grouped[segment].append((score, risk_mm))

    empty_segments = sorted(set(candidate_rows) - set(grouped))
    if empty_segments:
        raise ValueError(f"遮挡 event 没有可评价的 VCD 候选：{empty_segments[0]}")
    if not grouped:
        raise ValueError("五本 workbook 缺少可计算 VCD risk-coverage 的遮挡候选")
    curve_rows: list[Mapping[str, Any]] = []
    segment_rows: list[Mapping[str, Any]] = []
    for segment, values in sorted(grouped.items()):
        scores = [item[0] for item in values]
        risks = [item[1] for item in values]
        curve, aurc_mm = risk_coverage_curve(scores, risks)
        for curve_point in curve:
            curve_rows.append(
                {
                    "session_id": segment[0],
                    "trial_id": segment[1],
                    "segment_id": segment[2],
                    **curve_point,
                }
            )
        full_coverage_risk_mm = float(curve[-1]["selective_risk_mm"])
        segment_rows.append(
            {
                "session_id": segment[0],
                "trial_id": segment[1],
                "segment_id": segment[2],
                "candidate_rows": candidate_rows[segment],
                "evaluable_candidates": len(values),
                "excluded_candidates": excluded_rows[segment],
                "score_levels": len(curve),
                "full_coverage_risk_mm": full_coverage_risk_mm,
                "aurc_mm": aurc_mm,
                "risk_gain_mm": full_coverage_risk_mm - aurc_mm,
            }
        )
    return tuple(curve_rows), tuple(segment_rows)


def _performance(workbooks: Sequence[Path]) -> Mapping[str, float | int]:
    """从 Python candidate 日志汇总运行时审计数字。"""

    track: list[float] = []
    register: list[float] = []
    intervals: list[float] = []
    columns = ("phase", "total_ms", "has_pose", "server_publish_mono_ms")
    for workbook in workbooks:
        published: list[float] = []
        for row in iter_rows(workbook, "python_candidates", columns):
            try:
                total_ms = float(row["total_ms"])
            except (KeyError, TypeError, ValueError):
                total_ms = math.nan
            if math.isfinite(total_ms):
                if row.get("phase") == "TRACK":
                    track.append(total_ms)
                elif row.get("phase") == "REGISTER":
                    register.append(total_ms)
            if _truthy(row.get("has_pose")):
                try:
                    published.append(float(row["server_publish_mono_ms"]))
                except (KeyError, TypeError, ValueError):
                    pass
        if len(published) > 1:
            intervals.extend(np.diff(np.asarray(sorted(published), dtype=float)).tolist())
    if not track or not register or not intervals:
        raise ValueError("五本 workbook 缺少 TRACK、REGISTER 或 pose publish 性能样本")
    return {
        "track_total_ms_median": float(np.median(track)),
        "track_total_ms_p95": _quantile(np.asarray(track), 0.95),
        "track_n": len(track),
        "register_total_ms_median": float(np.median(register)),
        "register_n": len(register),
        "pose_publish_interval_ms_median": float(np.median(intervals)),
        "pose_publish_rate_hz_from_median": float(1000.0 / np.median(intervals)),
        "pose_publish_interval_n": len(intervals),
    }


def analyze_workbooks(
    workbooks: Sequence[Path],
    settings: PaperSettings | None = None,
) -> PaperResults:
    """只读五本 Stage 1 XLSX，返回论文所需结果。"""

    normalized = tuple(path.expanduser().resolve() for path in workbooks)
    if not normalized:
        raise ValueError("至少需要一本 Stage 1 XLSX")
    for path in normalized:
        if path.suffix.lower() != ".xlsx":
            raise ValueError(f"论文分析只接受 Stage 1 XLSX：{path}")
        if not path.is_file():
            raise FileNotFoundError(path)
        _validate_workbook_runtime_contract(path)
    valid_trials = eligible_trials(normalized)
    active_settings = settings or load_settings()
    render = _collect_render(normalized, valid_trials)
    event_roles = _event_roles(normalized, valid_trials)
    static, translation, rotation, occlusion, transition, stop = _render_metrics(
        render,
        event_roles,
        active_settings,
    )
    vcd_risk_coverage, vcd_aurc_segments = _vcd_risk_coverage(
        normalized,
        valid_trials,
        event_roles,
    )
    return PaperResults(
        workbook_sha256={str(path): workbook_sha256(path) for path in normalized},
        static_segments=static,
        translation_segments=translation,
        rotation_segments=rotation,
        occlusion_episodes=occlusion,
        transition_segments=transition,
        stop_segments=stop,
        correction_segments=_collect_correction_metrics(normalized, valid_trials),
        capture_alignment=_capture_alignment(normalized, valid_trials),
        vcd_risk_coverage=vcd_risk_coverage,
        vcd_aurc_segments=vcd_aurc_segments,
        performance=_performance(normalized),
    )


__all__ = [
    "FULL_VARIANT",
    "PaperResults",
    "CAUSAL_PREDICTION_VARIANT",
    "METHODS",
    "NO_STATIC_LOCK",
    "NO_TEMPORAL_SYNTHESIS",
    "NO_VCD",
    "TEMPORAL_STRATEGY_VARIANTS",
    "analyze_workbooks",
    "paired_metric_matrix",
    "risk_coverage_curve",
    "segment_identity",
]

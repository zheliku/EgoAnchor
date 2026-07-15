"""起停转换与遮挡恢复的 event 级 schema-v2 指标。"""

from __future__ import annotations

from typing import Any, cast

import numpy as np
import pandas as pd

from .common import (
    METRIC_GROUP_COLUMNS,
    is_pose_vector,
    iter_metric_groups,
    pose_error,
    require_columns,
)
from .stats import finite_percentile


TRANSITION_ROLE = "transition_started"
OCCLUSION_STARTED_ROLE = "occlusion_started"
TARGET_VISIBLE_ROLE = "target_visible"

TRANSITION_SCENARIOS = frozenset(
    {"start_stop_6dof", "without_temporal_synthesis", "without_static_lock"}
)
OCCLUSION_SCENARIOS = frozenset({"occlusion_recovery", "without_vcd_admission"})

TRIAL_COLUMNS = ("session_id", "experiment_id", "scenario_id", "trial_id")
VARIANT_COLUMNS = ("condition_id", "variant_id", "variant_label")

TRANSITION_COLUMNS = [
    *METRIC_GROUP_COLUMNS,
    "event_mono_ms",
    "sample_count",
    "visible_response_time_ms",
    "unlock_success",
    "unlock_time_ms",
    "relock_success",
    "relock_time_ms",
    "peak_translation_error_mm",
    "peak_rotation_error_deg",
    "settling_time_ms",
    "insufficient_data",
]
"""每个起停 event×variant 的响应与重新稳定字段。"""

OCCLUSION_COLUMNS = [
    *METRIC_GROUP_COLUMNS,
    "event_mono_ms",
    "target_visible_event_id",
    "target_visible_mono_ms",
    "sample_count",
    "output_availability",
    "display_availability",
    "display_jump_p95_mm",
    "display_rotation_jump_p95_deg",
    "recovery_success",
    "recovery_time_ms",
    "insufficient_data",
]
"""每个遮挡恢复 event×variant 的可用性、跳变和恢复字段。"""


def compute_transition_metrics(
    unity_render: pd.DataFrame,
    events: pd.DataFrame,
    *,
    motion_linear_threshold_m_s: float = 0.03,
    motion_angular_threshold_deg_s: float = 5.0,
    response_translation_threshold_mm: float = 5.0,
    response_rotation_threshold_deg: float = 2.0,
    settled_translation_threshold_mm: float = 20.0,
    settled_rotation_threshold_deg: float = 5.0,
    hold_ms: float = 200.0,
    max_gap_ms: float = 100.0,
) -> pd.DataFrame:
    """计算 ``transition_started`` marker 后的可见响应、解锁和重新稳定。

    每个 ``event_marker`` 开启一个独立 ``event_id`` 分段。运动起点由平台参考
    速度首次越过冻结阈值确定；可见响应是 display pose 相对起点前显示位姿首次
    超过响应阈值。运动停止、relock 与 settling 均要求持续窗口，并拒绝跨越大于
    ``max_gap_ms`` 的日志缺口。
    """

    _validate_event_inputs(unity_render, events)
    _validate_thresholds(hold_ms, max_gap_ms)
    markers = _role_markers(events, {TRANSITION_ROLE})
    _require_known_scenario_roles(
        unity_render,
        markers,
        scenarios=TRANSITION_SCENARIOS,
        required_roles={TRANSITION_ROLE},
    )
    rows: list[dict[str, Any]] = []
    for marker in _marker_records(markers):
        trial_render = _trial_render(unity_render, marker)
        event_render = _marker_render(trial_render, marker)
        _require_variant_coverage(trial_render, event_render, marker)
        for context, group in iter_metric_groups(event_render):
            rows.append(
                _transition_row(
                    context,
                    group.sort_values("render_mono_ms", kind="stable"),
                    marker["mono_ms"],
                    motion_linear_threshold_m_s=motion_linear_threshold_m_s,
                    motion_angular_threshold_deg_s=motion_angular_threshold_deg_s,
                    response_translation_threshold_mm=response_translation_threshold_mm,
                    response_rotation_threshold_deg=response_rotation_threshold_deg,
                    settled_translation_threshold_mm=settled_translation_threshold_mm,
                    settled_rotation_threshold_deg=settled_rotation_threshold_deg,
                    hold_ms=hold_ms,
                    max_gap_ms=max_gap_ms,
                )
            )
    return pd.DataFrame.from_records(rows, columns=TRANSITION_COLUMNS)


def compute_occlusion_metrics(
    unity_render: pd.DataFrame,
    events: pd.DataFrame,
    *,
    recovery_translation_threshold_mm: float = 20.0,
    recovery_rotation_threshold_deg: float = 5.0,
    hold_ms: float = 200.0,
    max_gap_ms: float = 100.0,
) -> pd.DataFrame:
    """计算成对遮挡 marker 的可用性、跳变与稳定恢复。

    每个 trial 必须按顺序写入 ``occlusion_started`` 和 ``target_visible``。可用率从
    遮挡开始统计，恢复计时从目标重新可见开始；仅显示 hold-last 而没有 runtime
    output 不算恢复成功。
    """

    _validate_event_inputs(unity_render, events)
    _validate_thresholds(hold_ms, max_gap_ms)
    markers = _role_markers(events, {OCCLUSION_STARTED_ROLE, TARGET_VISIBLE_ROLE})
    _require_known_scenario_roles(
        unity_render,
        markers,
        scenarios=OCCLUSION_SCENARIOS,
        required_roles={OCCLUSION_STARTED_ROLE, TARGET_VISIBLE_ROLE},
    )
    rows: list[dict[str, Any]] = []
    for started, visible in _occlusion_pairs(markers):
        trial_render = _trial_render(unity_render, started)
        started_render = _marker_render(trial_render, started)
        visible_render = _marker_render(trial_render, visible)
        _require_variant_coverage(trial_render, started_render, started)
        _require_variant_coverage(trial_render, visible_render, visible)
        pair_render = pd.concat([started_render, visible_render], ignore_index=True)
        for context, group in iter_metric_groups(_with_pair_event_id(pair_render, started["event_id"])):
            rows.append(
                _occlusion_row(
                    context,
                    group.sort_values("render_mono_ms", kind="stable"),
                    started["mono_ms"],
                    target_visible_event_id=visible["event_id"],
                    target_visible_mono_ms=visible["mono_ms"],
                    recovery_translation_threshold_mm=recovery_translation_threshold_mm,
                    recovery_rotation_threshold_deg=recovery_rotation_threshold_deg,
                    hold_ms=hold_ms,
                    max_gap_ms=max_gap_ms,
                )
            )
    return pd.DataFrame.from_records(rows, columns=OCCLUSION_COLUMNS)


def _validate_event_inputs(render: pd.DataFrame, events: pd.DataFrame) -> None:
    """校验 event 级转换与恢复指标所需字段。"""

    require_columns(
        render,
        {
            *METRIC_GROUP_COLUMNS,
            "render_mono_ms",
            "reference_pose_valid",
            "reference_pos",
            "reference_rot",
            "reference_linear_speed_m_s",
            "reference_angular_speed_deg_s",
            "has_output_pose",
            "has_display_pose",
            "display_pos",
            "display_rot",
            "latest_static_locked",
        },
        table_name="unity_render",
    )
    require_columns(
        events,
        {
            "session_id",
            "experiment_id",
            "scenario_id",
            "trial_id",
            "event_id",
            "event_type",
            "mono_ms",
            "payload",
        },
        table_name="events",
    )


def _validate_thresholds(hold_ms: float, max_gap_ms: float) -> None:
    """拒绝无法形成持续窗口的非法时间阈值。"""

    if hold_ms < 0.0:
        raise ValueError("hold_ms 不得为负数。")
    if max_gap_ms <= 0.0:
        raise ValueError("max_gap_ms 必须大于零。")


def _role_markers(events: pd.DataFrame, roles: set[str]) -> pd.DataFrame:
    """提取 payload 中具有指定事件角色的人工 marker。"""

    marker = events[events["event_type"].astype(str).eq("event_marker")].copy()
    marker["event_role"] = marker["payload"].map(_event_role)
    marker = marker[marker["event_role"].isin(roles)]
    if marker.empty:
        return marker
    duplicate_columns = [*TRIAL_COLUMNS, "event_id", "event_role"]
    if marker.duplicated(duplicate_columns, keep=False).any():
        raise ValueError("同一 trial/event_id/event_role 只能有一个 event_marker。")
    return marker


def _event_role(payload: object) -> str:
    """从 schema-v2 payload 读取事件角色；非法 payload 不参与指标路由。"""

    return str(payload.get("event_role", "")) if isinstance(payload, dict) else ""


def _marker_records(markers: pd.DataFrame) -> list[dict[str, Any]]:
    """把 marker 转为已校验、按时间稳定排序的普通字典。"""

    records: list[dict[str, Any]] = []
    for _, row in markers.sort_values([*TRIAL_COLUMNS, "mono_ms"], kind="stable").iterrows():
        event_id = str(row["event_id"])
        mono_ms = _number(row["mono_ms"])
        if not event_id or not np.isfinite(mono_ms):
            raise ValueError("事件角色 marker 必须具有非空 event_id 和有限 mono_ms。")
        record: dict[str, Any] = {column: str(row[column]) for column in TRIAL_COLUMNS}
        record.update(event_id=event_id, event_role=str(row["event_role"]), mono_ms=mono_ms)
        records.append(record)
    return records


def _require_known_scenario_roles(
    render: pd.DataFrame,
    markers: pd.DataFrame,
    *,
    scenarios: frozenset[str],
    required_roles: set[str],
) -> None:
    """已知协议场景存在 render 时，严格要求 trial 具有全部必需角色。"""

    known = render[render["scenario_id"].astype(str).isin(scenarios)]
    for values, _ in known.groupby(list(TRIAL_COLUMNS), dropna=False, sort=True):
        trial = dict(zip(TRIAL_COLUMNS, values, strict=True))
        trial_markers = markers
        for column, value in trial.items():
            trial_markers = trial_markers[trial_markers[column].astype(str).eq(str(value))]
        present = set(trial_markers["event_role"].astype(str))
        missing = sorted(required_roles - present)
        if missing:
            context = "/".join(str(trial[column]) for column in TRIAL_COLUMNS)
            raise ValueError(f"trial {context} 缺少必需事件角色：{', '.join(missing)}")


def _trial_render(render: pd.DataFrame, marker: dict[str, Any]) -> pd.DataFrame:
    """按 marker 的四个 trial 键截取 render，禁止跨实验或 trial 串段。"""

    trial = render
    for column in TRIAL_COLUMNS:
        trial = trial[trial[column].astype(str).eq(marker[column])]
    if trial.empty:
        raise ValueError(f"事件 marker 没有匹配的 trial render：{marker}")
    return trial


def _marker_render(trial_render: pd.DataFrame, marker: dict[str, Any]) -> pd.DataFrame:
    """截取一个 marker 自身 event_id 且不早于 marker 的 render 行。"""

    times = pd.to_numeric(trial_render["render_mono_ms"], errors="coerce")
    return trial_render[
        trial_render["event_id"].astype(str).eq(marker["event_id"])
        & times.ge(marker["mono_ms"])
    ].copy()


def _require_variant_coverage(
    trial_render: pd.DataFrame,
    marker_render: pd.DataFrame,
    marker: dict[str, Any],
) -> None:
    """要求 marker 对 trial 中每个预期 variant 都具有 render 样本。"""

    expected = _variant_keys(trial_render)
    present = _variant_keys(marker_render)
    missing = sorted(expected - present)
    if missing:
        raise ValueError(
            f"事件 marker {marker['event_id']} ({marker['event_role']}) 缺少 variant render：{missing}"
        )


def _variant_keys(render: pd.DataFrame) -> set[tuple[str, str, str]]:
    """返回 condition/variant/label 三元组，供 marker 完整性检查。"""

    return {
        (str(row["condition_id"]), str(row["variant_id"]), str(row["variant_label"]))
        for _, row in render[list(VARIANT_COLUMNS)].drop_duplicates().iterrows()
    }


def _occlusion_pairs(markers: pd.DataFrame) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """按 trial 和时间配对遮挡开始/重新可见，拒绝乱序、悬空或重复角色。"""

    records = _marker_records(markers)
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for marker in records:
        key = tuple(marker[column] for column in TRIAL_COLUMNS)
        grouped.setdefault(key, []).append(marker)

    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for trial, trial_markers in grouped.items():
        started: dict[str, Any] | None = None
        for marker in trial_markers:
            if marker["event_role"] == OCCLUSION_STARTED_ROLE:
                if started is not None:
                    raise ValueError(f"trial {trial} 的遮挡事件角色顺序错误：连续 occlusion_started。")
                started = marker
                continue
            if started is None:
                raise ValueError(f"trial {trial} 的遮挡事件角色顺序错误：target_visible 缺少前导。")
            if marker["event_id"] == started["event_id"] or marker["mono_ms"] <= started["mono_ms"]:
                raise ValueError(f"trial {trial} 的 target_visible 必须晚于遮挡且使用不同 event_id。")
            pairs.append((started, marker))
            started = None
        if started is not None:
            raise ValueError(f"trial {trial} 的 occlusion_started 缺少后续 target_visible。")
    return pairs


def _with_pair_event_id(render: pd.DataFrame, event_id: str) -> pd.DataFrame:
    """合并遮挡两个 event_id 后，以遮挡开始 ID 作为指标主键。"""

    result = render.copy()
    result["event_id"] = event_id
    return result


def _transition_row(
    context: dict[str, str],
    segment: pd.DataFrame,
    event_mono_ms: float,
    *,
    motion_linear_threshold_m_s: float,
    motion_angular_threshold_deg_s: float,
    response_translation_threshold_mm: float,
    response_rotation_threshold_deg: float,
    settled_translation_threshold_mm: float,
    settled_rotation_threshold_deg: float,
    hold_ms: float,
    max_gap_ms: float,
) -> dict[str, Any]:
    """构造一个起停 event×variant 指标行。"""

    times = _numeric_array(segment, "render_mono_ms")
    translation_error_mm, rotation_error_deg = _display_errors(segment)
    moving = (
        _numeric_array(segment, "reference_linear_speed_m_s")
        >= motion_linear_threshold_m_s
    ) | (
        _numeric_array(segment, "reference_angular_speed_deg_s")
        >= motion_angular_threshold_deg_s
    )
    motion_start_ms = _first_true_time(times, moving, event_mono_ms)
    motion_stop_ms = _final_motion_stop(
        times,
        moving,
        motion_start_ms=motion_start_ms,
        hold_ms=hold_ms,
        max_gap_ms=max_gap_ms,
    ) if np.isfinite(motion_start_ms) else np.nan

    visible_response_ms = _visible_response_time(
        segment,
        motion_start_ms,
        response_translation_threshold_mm=response_translation_threshold_mm,
        response_rotation_threshold_deg=response_rotation_threshold_deg,
    )
    locked = _bool_array(segment, "latest_static_locked")
    unlock_ms = _unlock_time(times, locked, motion_start_ms)
    relock_ms = _first_sustained_time(
        times,
        locked,
        start_ms=motion_stop_ms,
        hold_ms=hold_ms,
        max_gap_ms=max_gap_ms,
    ) if np.isfinite(motion_stop_ms) else np.nan
    settled = (
        np.isfinite(translation_error_mm)
        & np.isfinite(rotation_error_deg)
        & (translation_error_mm <= settled_translation_threshold_mm)
        & (rotation_error_deg <= settled_rotation_threshold_deg)
    )
    settled_ms = _first_sustained_time(
        times,
        settled,
        start_ms=motion_stop_ms,
        hold_ms=hold_ms,
        max_gap_ms=max_gap_ms,
    ) if np.isfinite(motion_stop_ms) else np.nan

    return {
        **context,
        "event_mono_ms": event_mono_ms,
        "sample_count": int(len(segment)),
        "visible_response_time_ms": _elapsed(visible_response_ms, motion_start_ms),
        "unlock_success": bool(np.isfinite(unlock_ms)),
        "unlock_time_ms": _elapsed(unlock_ms, motion_start_ms),
        "relock_success": bool(np.isfinite(relock_ms)),
        "relock_time_ms": _elapsed(relock_ms, motion_stop_ms),
        "peak_translation_error_mm": _finite_max(translation_error_mm),
        "peak_rotation_error_deg": _finite_max(rotation_error_deg),
        "settling_time_ms": _elapsed(settled_ms, motion_stop_ms),
        "insufficient_data": not (
            np.isfinite(motion_start_ms)
            and np.isfinite(motion_stop_ms)
            and np.isfinite(visible_response_ms)
            and np.isfinite(settled_ms)
            and np.isfinite(translation_error_mm).any()
        ),
    }


def _occlusion_row(
    context: dict[str, str],
    segment: pd.DataFrame,
    event_mono_ms: float,
    *,
    target_visible_event_id: str,
    target_visible_mono_ms: float,
    recovery_translation_threshold_mm: float,
    recovery_rotation_threshold_deg: float,
    hold_ms: float,
    max_gap_ms: float,
) -> dict[str, Any]:
    """构造一个遮挡恢复 event×variant 指标行。"""

    times = _numeric_array(segment, "render_mono_ms")
    output_available = _bool_array(segment, "has_output_pose")
    display_available = _bool_array(segment, "has_display_pose")
    translation_error_mm, rotation_error_deg = _display_errors(segment)
    recovered = (
        output_available
        & display_available
        & np.isfinite(translation_error_mm)
        & np.isfinite(rotation_error_deg)
        & (translation_error_mm <= recovery_translation_threshold_mm)
        & (rotation_error_deg <= recovery_rotation_threshold_deg)
    )
    recovered_ms = _first_sustained_time(
        times,
        recovered,
        start_ms=target_visible_mono_ms,
        hold_ms=hold_ms,
        max_gap_ms=max_gap_ms,
    )
    translation_jumps_mm, rotation_jumps_deg = _display_jumps(segment)
    return {
        **context,
        "event_mono_ms": event_mono_ms,
        "target_visible_event_id": target_visible_event_id,
        "target_visible_mono_ms": target_visible_mono_ms,
        "sample_count": int(len(segment)),
        "output_availability": _availability(output_available),
        "display_availability": _availability(display_available),
        "display_jump_p95_mm": finite_percentile(translation_jumps_mm, 95),
        "display_rotation_jump_p95_deg": finite_percentile(rotation_jumps_deg, 95),
        "recovery_success": bool(np.isfinite(recovered_ms)),
        "recovery_time_ms": _elapsed(recovered_ms, target_visible_mono_ms),
        "insufficient_data": segment.empty or not np.isfinite(translation_error_mm).any(),
    }


def _display_errors(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """逐行计算 display pose 相对平台参考的平移毫米误差与旋转角误差。"""

    translation = np.full(len(frame), np.nan, dtype=float)
    rotation = np.full(len(frame), np.nan, dtype=float)
    for index, (_, row) in enumerate(frame.iterrows()):
        if not bool(row["reference_pose_valid"]) or not bool(row["has_display_pose"]):
            continue
        if not (
            is_pose_vector(row["reference_pos"], 3)
            and is_pose_vector(row["reference_rot"], 4)
            and is_pose_vector(row["display_pos"], 3)
            and is_pose_vector(row["display_rot"], 4)
        ):
            continue
        translation_m, rotation_deg = pose_error(
            row["reference_pos"],
            row["reference_rot"],
            row["display_pos"],
            row["display_rot"],
        )
        translation[index] = translation_m * 1000.0
        rotation[index] = rotation_deg
    return translation, rotation


def _visible_response_time(
    frame: pd.DataFrame,
    motion_start_ms: float,
    *,
    response_translation_threshold_mm: float,
    response_rotation_threshold_deg: float,
) -> float:
    """查找 display pose 相对运动起点前基线首次产生可见变化的时刻。"""

    if not np.isfinite(motion_start_ms) or frame.empty:
        return np.nan
    times = _numeric_array(frame, "render_mono_ms")
    valid = _display_pose_mask(frame)
    baseline_indices = np.flatnonzero(valid & (times < motion_start_ms))
    if baseline_indices.size == 0:
        return np.nan
    baseline = frame.iloc[int(baseline_indices[-1])]
    for index in np.flatnonzero(valid & (times >= motion_start_ms)):
        row = frame.iloc[int(index)]
        translation_m, rotation_deg = pose_error(
            baseline["display_pos"],
            baseline["display_rot"],
            row["display_pos"],
            row["display_rot"],
        )
        if (
            translation_m * 1000.0 >= response_translation_threshold_mm
            or rotation_deg >= response_rotation_threshold_deg
        ):
            return float(times[index])
    return np.nan


def _display_pose_mask(frame: pd.DataFrame) -> np.ndarray:
    """返回同时具有合法 display position/rotation 的行掩码。"""

    available = _bool_array(frame, "has_display_pose")
    valid = np.zeros(len(frame), dtype=bool)
    for index, (_, row) in enumerate(frame.iterrows()):
        valid[index] = available[index] and is_pose_vector(
            row["display_pos"], 3
        ) and is_pose_vector(row["display_rot"], 4)
    return valid


def _display_jumps(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """计算相邻可见 display pose 的逐更新跳变。"""

    valid_indices = np.flatnonzero(_display_pose_mask(frame))
    if len(valid_indices) < 2:
        return np.empty(0, dtype=float), np.empty(0, dtype=float)
    translations: list[float] = []
    rotations: list[float] = []
    for previous, current in zip(valid_indices[:-1], valid_indices[1:], strict=True):
        previous_row = frame.iloc[int(previous)]
        current_row = frame.iloc[int(current)]
        translation_m, rotation_deg = pose_error(
            previous_row["display_pos"],
            previous_row["display_rot"],
            current_row["display_pos"],
            current_row["display_rot"],
        )
        translations.append(translation_m * 1000.0)
        rotations.append(rotation_deg)
    return np.asarray(translations, dtype=float), np.asarray(rotations, dtype=float)


def _unlock_time(times: np.ndarray, locked: np.ndarray, motion_start_ms: float) -> float:
    """仅在运动开始前确实处于 StaticLock 时报告首次解锁。"""

    if not np.isfinite(motion_start_ms):
        return np.nan
    before = np.flatnonzero((times <= motion_start_ms) & locked)
    if before.size == 0:
        return np.nan
    return _first_true_time(times, ~locked, motion_start_ms)


def _first_true_time(times: np.ndarray, flags: np.ndarray, start_ms: float) -> float:
    """返回指定时刻后首个 true 样本的时刻。"""

    indices = np.flatnonzero(np.isfinite(times) & (times >= start_ms) & flags)
    return float(times[indices[0]]) if indices.size else np.nan


def _first_sustained_time(
    times: np.ndarray,
    good: np.ndarray,
    *,
    start_ms: float,
    hold_ms: float,
    max_gap_ms: float,
) -> float:
    """查找首个连续 good 窗口，并拒绝跨越过大的采样缺口。"""

    if not np.isfinite(start_ms) or len(times) == 0:
        return np.nan
    for start in np.flatnonzero(np.isfinite(times) & (times >= start_ms) & good):
        if hold_ms == 0.0:
            return float(times[start])
        previous_time = float(times[start])
        for stop in range(int(start) + 1, len(times)):
            current_time = float(times[stop])
            if (
                not np.isfinite(current_time)
                or current_time - previous_time > max_gap_ms
                or not good[stop]
            ):
                break
            if current_time - float(times[start]) >= hold_ms:
                return float(times[start])
            previous_time = current_time
    return np.nan


def _final_motion_stop(
    times: np.ndarray,
    moving: np.ndarray,
    *,
    motion_start_ms: float,
    hold_ms: float,
    max_gap_ms: float,
) -> float:
    """以最后一个运动 run 之后的持续静止作为本事件停止时刻。"""

    motion_indices = np.flatnonzero(np.isfinite(times) & (times >= motion_start_ms) & moving)
    if motion_indices.size == 0:
        return np.nan
    final_motion_ms = float(times[motion_indices[-1]])
    return _first_sustained_time(
        times,
        ~moving,
        start_ms=np.nextafter(final_motion_ms, np.inf),
        hold_ms=hold_ms,
        max_gap_ms=max_gap_ms,
    )


def _numeric_array(frame: pd.DataFrame, column: str) -> np.ndarray:
    """把数值列转换为 float 数组，非法值写为 NaN。"""

    return pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=float)


def _bool_array(frame: pd.DataFrame, column: str) -> np.ndarray:
    """把 schema-v2 bool 列转换为布尔数组。"""

    return frame[column].fillna(False).astype(bool).to_numpy(dtype=bool)


def _availability(flags: np.ndarray) -> float:
    """计算 event 内可用 tick 比例；空分段返回 NaN。"""

    return float(np.mean(flags)) if len(flags) else np.nan


def _finite_max(values: np.ndarray) -> float:
    """返回有限值最大值；无有限值时返回 NaN。"""

    finite = values[np.isfinite(values)]
    return float(np.max(finite)) if finite.size else np.nan


def _elapsed(later: float, earlier: float) -> float:
    """计算非负事件耗时；任一时刻不可用时返回 NaN。"""

    if not np.isfinite(later) or not np.isfinite(earlier):
        return np.nan
    elapsed = float(later - earlier)
    return elapsed if elapsed >= 0.0 else np.nan


def _number(value: object) -> float:
    """把日志数值转换成有限 float。"""

    try:
        number = float(cast(Any, value))
    except (TypeError, ValueError):
        return np.nan
    return number if np.isfinite(number) else np.nan


__all__ = ["compute_occlusion_metrics", "compute_transition_metrics"]

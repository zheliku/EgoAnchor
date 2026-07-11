"""RQ2 source-frame 感知误差与时延关联样本。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from egoanchor.eval.io import SessionLogs
from egoanchor.eval.metrics import is_pose_value, pose_error

from .contract import (
    ACTIVE_ROTATION_MIN_DEG_S,
    ACTIVE_TRANSLATION_MIN_M_S,
    MODEL_MAX_SPEED_CV,
    MODEL_MIN_AXIS_CONSISTENCY,
    MOTION_COLUMNS,
    SOURCE_COLUMNS,
)
from .trajectory import (
    active_at_times,
    annotate_active_motion,
    build_gt_trajectory,
    fit_pre_image_motion,
    interpolate_gt,
    world_rotation_vector,
)


def build_source_observations(
    logs: SessionLogs | pd.DataFrame,
    *,
    session_id: str | None = None,
) -> pd.DataFrame:
    """构造按 trial 和 source frame 去重的 image-time raw 诊断表。"""

    output = logs.output if isinstance(logs, SessionLogs) else logs
    resolved_session = _session_id(logs, session_id)
    if output.empty:
        return pd.DataFrame(columns=SOURCE_COLUMNS)
    motion = annotate_active_motion(output) if "active_motion" not in output else output.copy()
    motion = _trial_rows(motion)
    required = (
        "label",
        "is_primary",
        "source_frame_id",
        "source_capture_mono_ms",
        "render_mono_ms",
        "has_aligned_raw",
        "aligned_raw_pos",
        "aligned_raw_rot",
    )
    if motion.empty or any(column not in motion.columns for column in required):
        return pd.DataFrame(columns=SOURCE_COLUMNS)
    motion = motion.loc[motion["is_primary"].fillna(False).astype(bool)].copy()
    if motion.empty:
        return pd.DataFrame(columns=SOURCE_COLUMNS)

    frame_id = pd.to_numeric(motion["source_frame_id"], errors="coerce")
    image_ms = pd.to_numeric(motion["source_capture_mono_ms"], errors="coerce")
    candidates = motion.loc[
        motion["has_aligned_raw"].fillna(False).astype(bool)
        & frame_id.notna()
        & (frame_id >= 0)
        & image_ms.notna()
        & motion["aligned_raw_pos"].map(is_pose_value)
        & motion["aligned_raw_rot"].map(is_pose_value)
    ].copy()
    if candidates.empty:
        return pd.DataFrame(columns=SOURCE_COLUMNS)
    candidates["source_frame_id"] = pd.to_numeric(
        candidates["source_frame_id"], errors="raise"
    ).astype(int)
    sort_columns = ["rq2_trial_id", "source_frame_id", "render_mono_ms"]
    if "tick_index" in candidates.columns:
        sort_columns.append("tick_index")
    first = candidates.sort_values(sort_columns, kind="stable").drop_duplicates(
        ["rq2_trial_id", "source_frame_id"], keep="first"
    )
    trajectory = build_gt_trajectory(output)

    records: list[dict[str, Any]] = []
    for _, row in first.iterrows():
        image_time = _finite_float(row.get("source_capture_mono_ms"))
        condition = str(row["rq2_condition"])
        trial_id = int(row["rq2_trial_id"])
        active = bool(
            active_at_times(
                motion,
                condition,
                trial_id,
                np.asarray([image_time], dtype=float),
            )[0]
        )
        gt_pos, gt_rot = interpolate_gt(trajectory, image_time)
        raw_pos = np.asarray(row["aligned_raw_pos"], dtype=float)
        raw_rot = np.asarray(row["aligned_raw_rot"], dtype=float)
        translation_error, rotation_error = _pose_error_or_nan(
            gt_pos, gt_rot, raw_pos, raw_rot
        )
        records.append(
            {
                "session_id": resolved_session,
                "condition": condition,
                "rq2_trial_id": trial_id,
                "label": str(row["label"]),
                "source_frame_id": int(row["source_frame_id"]),
                "active_motion": active,
                "image_mono_ms": image_time,
                "unity_pose_handle_mono_ms": _finite_float(
                    row.get("unity_pose_handle_mono_ms")
                ),
                "first_render_mono_ms": _finite_float(row.get("render_mono_ms")),
                "policy_output_target_mono_ms": _finite_float(
                    row.get("policy_output_target_mono_ms")
                ),
                "observation_age_ms": _finite_float(row.get("observation_age_ms")),
                "smoothing_delay_ms": _finite_float(row.get("smoothing_delay_ms")),
                "rq2_target_linear_speed_m_s": _finite_float(
                    row.get("rq2_target_linear_speed_m_s")
                ),
                "rq2_target_angular_speed_deg_s": _finite_float(
                    row.get("rq2_target_angular_speed_deg_s")
                ),
                "aligned_raw_pos": raw_pos,
                "aligned_raw_rot": raw_rot,
                "gt_image_pos": gt_pos,
                "gt_image_rot": gt_rot,
                "raw_translation_error_image_m": translation_error,
                "raw_rotation_error_image_deg": rotation_error,
            }
        )
    return pd.DataFrame.from_records(records, columns=SOURCE_COLUMNS)


def compute_motion_delay(source: pd.DataFrame, output: pd.DataFrame) -> pd.DataFrame:
    """计算 raw 有符号滞后残差和 pre-image 运动关联量。"""

    if source.empty:
        return pd.DataFrame(columns=MOTION_COLUMNS)
    trajectory = build_gt_trajectory(output)
    records: list[dict[str, Any]] = []
    for _, row in source.iterrows():
        record = row.to_dict()
        image_ms = _finite_float(row.get("image_mono_ms"))
        handle_ms = _finite_float(row.get("unity_pose_handle_mono_ms"))
        render_ms = _finite_float(row.get("first_render_mono_ms"))
        raw_pos = np.asarray(row["aligned_raw_pos"], dtype=float)
        raw_rot = np.asarray(row["aligned_raw_rot"], dtype=float)
        gt_image_pos, gt_image_rot = interpolate_gt(trajectory, image_ms)
        gt_handle_pos, gt_handle_rot = interpolate_gt(trajectory, handle_ms)
        gt_render_pos, gt_render_rot = interpolate_gt(trajectory, render_ms)
        fit = fit_pre_image_motion(trajectory, image_ms)
        linear_velocity = fit.linear_velocity_m_s
        angular_velocity = fit.angular_velocity_rad_s
        linear_speed = _vector_norm_or_nan(linear_velocity)
        angular_speed_rad = _vector_norm_or_nan(angular_velocity)
        angular_speed_deg = (
            float(np.degrees(angular_speed_rad))
            if np.isfinite(angular_speed_rad)
            else np.nan
        )
        direction = _unit_vector_or_none(linear_velocity)
        rotation_axis = _unit_vector_or_none(angular_velocity)
        handle_delay = _nonnegative_difference(handle_ms, image_ms)
        render_delay = _nonnegative_difference(render_ms, image_ms)
        handle_error = _pose_error_or_nan(
            gt_handle_pos, gt_handle_rot, raw_pos, raw_rot
        )
        render_error = _pose_error_or_nan(
            gt_render_pos, gt_render_rot, raw_pos, raw_rot
        )
        capture_rotation = _signed_rotation_residual_rad(
            raw_rot, gt_image_rot, rotation_axis
        )
        handle_rotation = _signed_rotation_residual_rad(
            raw_rot, gt_handle_rot, rotation_axis
        )
        render_rotation = _signed_rotation_residual_rad(
            raw_rot, gt_render_rot, rotation_axis
        )
        reference_handle_rotation = _signed_rotation_motion_rad(
            gt_image_rot, gt_handle_rot, rotation_axis
        )
        reference_render_rotation = _signed_rotation_motion_rad(
            gt_image_rot, gt_render_rot, rotation_axis
        )
        expected_rotation_handle = _speed_displacement(angular_speed_rad, handle_delay)
        expected_rotation_render = _speed_displacement(angular_speed_rad, render_delay)
        condition = str(row.get("condition", ""))
        active = bool(row.get("active_motion", False))
        translation_eligible = bool(
            active
            and condition != "rotation"
            and _fit_is_eligible(
                linear_speed,
                fit.linear_speed_cv,
                fit.linear_axis_consistency,
                ACTIVE_TRANSLATION_MIN_M_S,
            )
            and np.isfinite(handle_delay)
        )
        rotation_eligible = bool(
            active
            and condition == "rotation"
            and _fit_is_eligible(
                angular_speed_deg,
                fit.angular_speed_cv,
                fit.angular_axis_consistency,
                ACTIVE_ROTATION_MIN_DEG_S,
            )
            and np.isfinite(handle_delay)
        )
        record.update(
            {
                "handle_delay_ms": handle_delay,
                "render_delay_ms": render_delay,
                "gt_handle_pos": gt_handle_pos,
                "gt_handle_rot": gt_handle_rot,
                "gt_render_pos": gt_render_pos,
                "gt_render_rot": gt_render_rot,
                "raw_translation_error_handle_m": handle_error[0],
                "raw_rotation_error_handle_deg": handle_error[1],
                "raw_translation_error_render_m": render_error[0],
                "raw_rotation_error_render_deg": render_error[1],
                "pre_image_linear_velocity_m_s": linear_velocity,
                "pre_image_angular_velocity_rad_s": angular_velocity,
                "pre_image_rotation_axis_world": rotation_axis,
                "pre_image_linear_speed_m_s": linear_speed,
                "pre_image_angular_speed_rad_s": angular_speed_rad,
                "pre_image_angular_speed_deg_s": angular_speed_deg,
                "pre_image_linear_speed_cv": fit.linear_speed_cv,
                "pre_image_angular_speed_cv": fit.angular_speed_cv,
                "pre_image_linear_axis_consistency": fit.linear_axis_consistency,
                "pre_image_angular_axis_consistency": fit.angular_axis_consistency,
                "translation_model_eligible": translation_eligible,
                "rotation_model_eligible": rotation_eligible,
                "reference_translation_motion_handle_m": _signed_motion(
                    gt_image_pos, gt_handle_pos, direction
                ),
                "reference_translation_motion_render_m": _signed_motion(
                    gt_image_pos, gt_render_pos, direction
                ),
                "reference_rotation_motion_handle_rad": reference_handle_rotation,
                "reference_rotation_motion_render_rad": reference_render_rotation,
                "reference_rotation_motion_handle_deg": _degrees_or_nan(
                    reference_handle_rotation
                ),
                "reference_rotation_motion_render_deg": _degrees_or_nan(
                    reference_render_rotation
                ),
                "raw_translation_lag_error_capture_m": _signed_translation_residual(
                    raw_pos, gt_image_pos, direction
                ),
                "raw_translation_lag_error_handle_m": _signed_translation_residual(
                    raw_pos, gt_handle_pos, direction
                ),
                "raw_translation_lag_error_render_m": _signed_translation_residual(
                    raw_pos, gt_render_pos, direction
                ),
                "raw_rotation_lag_error_capture_rad": capture_rotation,
                "raw_rotation_lag_error_handle_rad": handle_rotation,
                "raw_rotation_lag_error_render_rad": render_rotation,
                "raw_rotation_lag_error_capture_deg": _degrees_or_nan(capture_rotation),
                "raw_rotation_lag_error_handle_deg": _degrees_or_nan(handle_rotation),
                "raw_rotation_lag_error_render_deg": _degrees_or_nan(render_rotation),
                "expected_translation_handle_m": _speed_displacement(
                    linear_speed, handle_delay
                ),
                "expected_translation_render_m": _speed_displacement(
                    linear_speed, render_delay
                ),
                "expected_rotation_handle_rad": expected_rotation_handle,
                "expected_rotation_render_rad": expected_rotation_render,
                "expected_rotation_handle_deg": _degrees_or_nan(
                    expected_rotation_handle
                ),
                "expected_rotation_render_deg": _degrees_or_nan(
                    expected_rotation_render
                ),
            }
        )
        records.append(record)
    return pd.DataFrame.from_records(records, columns=MOTION_COLUMNS)


def _trial_rows(output: pd.DataFrame) -> pd.DataFrame:
    """筛出合法 RQ2 试次行。"""

    required = ("rq2_condition", "rq2_trial_id", "label")
    if output.empty or any(column not in output.columns for column in required):
        return output.iloc[0:0].copy()
    trial = pd.to_numeric(output["rq2_trial_id"], errors="coerce")
    mask = (
        output["rq2_condition"]
        .fillna("none")
        .astype(str)
        .isin(("slow_translation", "fast_motion", "rotation"))
        & (trial > 0)
    )
    return output.loc[mask].copy()


def _session_id(logs: SessionLogs | pd.DataFrame, explicit: str | None) -> str:
    """解析 source 表使用的 session 标识。"""

    if explicit is not None:
        return str(explicit)
    if isinstance(logs, SessionLogs):
        return str(logs.manifest.get("session_id", ""))
    if "session_id" in logs.columns and not logs.empty:
        return str(logs.iloc[0]["session_id"])
    return ""


def _pose_error_or_nan(
    gt_pos: np.ndarray | None,
    gt_rot: np.ndarray | None,
    pose_pos: np.ndarray,
    pose_rot: np.ndarray,
) -> tuple[float, float]:
    """参考 pose 不可得时返回 NaN。"""

    if gt_pos is None or gt_rot is None:
        return np.nan, np.nan
    return pose_error(gt_pos, gt_rot, pose_pos, pose_rot)


def _signed_motion(
    start: np.ndarray | None,
    end: np.ndarray | None,
    direction: np.ndarray | None,
) -> float:
    """计算两参考时刻间沿局部运动方向的有符号位移。"""

    if start is None or end is None or direction is None:
        return np.nan
    return float(np.dot(end - start, direction))


def _signed_translation_residual(
    raw: np.ndarray,
    reference: np.ndarray | None,
    direction: np.ndarray | None,
) -> float:
    """计算使沿运动方向落后的 raw 为正的平移残差。"""

    if reference is None or direction is None:
        return np.nan
    return float(-np.dot(raw - reference, direction))


def _signed_rotation_motion_rad(
    start: np.ndarray | None,
    end: np.ndarray | None,
    axis: np.ndarray | None,
) -> float:
    """把参考旋转增量投影到 pre-image 世界旋转轴。"""

    increment = world_rotation_vector(start, end)
    if increment is None or axis is None:
        return np.nan
    return float(np.dot(increment, axis))


def _signed_rotation_residual_rad(
    raw: np.ndarray,
    reference: np.ndarray | None,
    axis: np.ndarray | None,
) -> float:
    """把 ``Log(R_reference R_raw^-1)`` 投影到世界旋转轴。"""

    increment = world_rotation_vector(raw, reference)
    if increment is None or axis is None:
        return np.nan
    return float(np.dot(increment, axis))


def _fit_is_eligible(
    speed: float,
    speed_cv: float,
    axis_consistency: float,
    min_speed: float,
) -> bool:
    """判断 pre-image 局部运动是否满足稳态关联条件。"""

    return bool(
        np.isfinite(speed)
        and speed >= min_speed
        and np.isfinite(speed_cv)
        and speed_cv <= MODEL_MAX_SPEED_CV
        and np.isfinite(axis_consistency)
        and axis_consistency >= MODEL_MIN_AXIS_CONSISTENCY
    )


def _vector_norm_or_nan(vector: np.ndarray | None) -> float:
    """返回向量模长。"""

    return float(np.linalg.norm(vector)) if vector is not None else np.nan


def _unit_vector_or_none(vector: np.ndarray | None) -> np.ndarray | None:
    """返回单位向量。"""

    if vector is None:
        return None
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 1e-12 else None


def _speed_displacement(speed: float, delay_ms: float) -> float:
    """将速度和毫秒延迟相乘。"""

    if not np.isfinite(speed) or not np.isfinite(delay_ms):
        return np.nan
    return float(speed * delay_ms / 1000.0)


def _nonnegative_difference(later: float, earlier: float) -> float:
    """计算非负时间差。"""

    if not np.isfinite(later) or not np.isfinite(earlier) or later < earlier:
        return np.nan
    return float(later - earlier)


def _finite_float(value: Any) -> float:
    """宽容读取有限浮点数。"""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return np.nan
    return number if np.isfinite(number) else np.nan


def _degrees_or_nan(value_rad: float) -> float:
    """将有限弧度值转换成度。"""

    return float(np.degrees(value_rad)) if np.isfinite(value_rad) else np.nan


__all__ = ["build_source_observations", "compute_motion_delay"]

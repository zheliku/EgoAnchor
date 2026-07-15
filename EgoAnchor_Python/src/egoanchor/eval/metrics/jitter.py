"""schema-v2 静止段的显示抖动、绝对误差与漂移指标。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation

from .common import (
    METRIC_GROUP_COLUMNS,
    angle_deg,
    highpass,
    is_pose_vector,
    iter_metric_groups,
    pose_error,
    relative_rotation_quat,
    require_columns,
)
from .stats import finite_percentile, rms


_STATIC_COLUMNS = (
    *METRIC_GROUP_COLUMNS,
    "render_mono_ms",
    "reference_pose_valid",
    "reference_pos",
    "reference_rot",
    "reference_linear_speed_m_s",
    "reference_angular_speed_deg_s",
    "has_display_pose",
    "display_pos",
    "display_rot",
)
"""静止指标依赖的 schema-v2 render 列。"""

SUMMARY_COLUMNS = [
    *METRIC_GROUP_COLUMNS,
    "n",
    "segment_count",
    "static_duration_ms",
    "position_hp_rms_mm",
    "rotation_hp_rms_deg",
    "translation_error_mm_median",
    "translation_error_mm_p95",
    "rotation_error_deg_median",
    "rotation_error_deg_p95",
    "position_drift_mm",
    "rotation_drift_deg",
    "insufficient_data",
]
"""trial/event/variant 级静止质量字段。"""


def compute_static_metrics(
    render: pd.DataFrame,
    *,
    linear_speed_threshold_m_s: float = 0.03,
    angular_speed_threshold_deg_s: float = 5.0,
    cutoff_hz: float = 1.0,
) -> pd.DataFrame:
    """在连续静止段内计算 display pose 的 HP-RMS、绝对误差和漂移。"""

    require_columns(render, _STATIC_COLUMNS, table_name="unity_render")
    rows: list[dict[str, Any]] = []
    for context, group in iter_metric_groups(render):
        ordered = group.sort_values("render_mono_ms", kind="stable").reset_index(drop=True)
        static = _static_mask(
            ordered,
            linear_speed_threshold_m_s=linear_speed_threshold_m_s,
            angular_speed_threshold_deg_s=angular_speed_threshold_deg_s,
        )
        segments = _static_segments(ordered, static)
        rows.append(_summarize_segments(context, segments, cutoff_hz=cutoff_hz))
    return pd.DataFrame.from_records(rows, columns=SUMMARY_COLUMNS)


def _static_mask(
    group: pd.DataFrame,
    *,
    linear_speed_threshold_m_s: float,
    angular_speed_threshold_deg_s: float,
) -> np.ndarray:
    """同时依据参考速度与位姿有效性标记可用于静止分析的行。"""

    pose_valid = (
        group["reference_pose_valid"].fillna(False).astype(bool)
        & group["has_display_pose"].fillna(False).astype(bool)
        & group["reference_pos"].map(lambda value: is_pose_vector(value, 3))
        & group["reference_rot"].map(lambda value: is_pose_vector(value, 4))
        & group["display_pos"].map(lambda value: is_pose_vector(value, 3))
        & group["display_rot"].map(lambda value: is_pose_vector(value, 4))
    )
    linear_speed = pd.to_numeric(group["reference_linear_speed_m_s"], errors="coerce")
    angular_speed = pd.to_numeric(group["reference_angular_speed_deg_s"], errors="coerce")
    return (
        pose_valid
        & linear_speed.between(0.0, linear_speed_threshold_m_s, inclusive="both")
        & angular_speed.between(0.0, angular_speed_threshold_deg_s, inclusive="both")
    ).to_numpy(dtype=bool)


def _static_segments(group: pd.DataFrame, static: np.ndarray) -> list[pd.DataFrame]:
    """按静止 mask 的连续 run 和时间缺口切段，禁止跨动态或无显示行拼接。"""

    if group.empty:
        return []
    times = pd.to_numeric(group["render_mono_ms"], errors="coerce").to_numpy(dtype=float)
    maximum_gap_ms = _maximum_gap_ms(times)
    segments: list[pd.DataFrame] = []
    start: int | None = None
    for index, is_static in enumerate(static):
        time_break = (
            start is not None
            and (
                not np.isfinite(times[index])
                or not np.isfinite(times[index - 1])
                or times[index] <= times[index - 1]
                or times[index] - times[index - 1] > maximum_gap_ms
            )
        )
        if not is_static or time_break:
            _append_segment(segments, group, start, index)
            start = None
        if is_static and start is None:
            start = index
    _append_segment(segments, group, start, len(group))
    return segments


def _append_segment(
    segments: list[pd.DataFrame],
    group: pd.DataFrame,
    start: int | None,
    end: int,
) -> None:
    """只保留至少三个采样点的连续静止段。"""

    if start is not None and end - start >= 3:
        segments.append(group.iloc[start:end].copy())


def _maximum_gap_ms(times: np.ndarray) -> float:
    """根据本组 render 周期估计允许的最大连续采样间隔。"""

    intervals = np.diff(times)
    positive = intervals[np.isfinite(intervals) & (intervals > 0.0)]
    return max(100.0, 2.5 * float(np.median(positive))) if len(positive) else 100.0


def _summarize_segments(
    context: dict[str, str],
    segments: list[pd.DataFrame],
    *,
    cutoff_hz: float,
) -> dict[str, Any]:
    """分别计算每个连续段后汇总，漂移不跨段连接。"""

    if not segments:
        return _insufficient(context)

    position_residuals: list[np.ndarray] = []
    rotation_residuals: list[np.ndarray] = []
    translation_errors_mm: list[float] = []
    rotation_errors_deg: list[float] = []
    position_drifts_mm: list[float] = []
    rotation_drifts_deg: list[float] = []
    duration_ms = 0.0
    sample_count = 0

    for segment in segments:
        times = segment["render_mono_ms"].to_numpy(dtype=float)
        dt = _median_dt_seconds(times)
        display_pos = np.vstack(segment["display_pos"].to_numpy())
        display_rot = np.vstack(segment["display_rot"].to_numpy())
        position_residuals.append(
            np.linalg.norm(highpass(display_pos, dt=dt, cutoff_hz=cutoff_hz), axis=1)
            * 1000.0
        )
        rotation_residuals.append(
            _rotation_residual_deg(display_rot, dt=dt, cutoff_hz=cutoff_hz)
        )
        segment_translation, segment_rotation = _absolute_errors(segment)
        translation_errors_mm.extend(segment_translation)
        rotation_errors_deg.extend(segment_rotation)
        position_drift, rotation_drift = _segment_drift(segment)
        position_drifts_mm.append(position_drift)
        rotation_drifts_deg.append(rotation_drift)
        duration_ms += float(times[-1] - times[0])
        sample_count += len(segment)

    position_hp = np.concatenate(position_residuals)
    rotation_hp = np.concatenate(rotation_residuals)
    translation = np.asarray(translation_errors_mm, dtype=float)
    rotation = np.asarray(rotation_errors_deg, dtype=float)
    return {
        **context,
        "n": int(sample_count),
        "segment_count": int(len(segments)),
        "static_duration_ms": duration_ms,
        "position_hp_rms_mm": rms(position_hp),
        "rotation_hp_rms_deg": rms(rotation_hp),
        "translation_error_mm_median": finite_percentile(translation, 50),
        "translation_error_mm_p95": finite_percentile(translation, 95),
        "rotation_error_deg_median": finite_percentile(rotation, 50),
        "rotation_error_deg_p95": finite_percentile(rotation, 95),
        "position_drift_mm": float(np.nanmax(position_drifts_mm)),
        "rotation_drift_deg": float(np.nanmax(rotation_drifts_deg)),
        "insufficient_data": False,
    }


def _absolute_errors(segment: pd.DataFrame) -> tuple[list[float], list[float]]:
    """计算一个静止段内逐行 display pose 绝对误差。"""

    translation: list[float] = []
    rotation: list[float] = []
    for _, row in segment.iterrows():
        translation_m, rotation_deg = pose_error(
            row["reference_pos"], row["reference_rot"], row["display_pos"], row["display_rot"]
        )
        translation.append(translation_m * 1000.0)
        rotation.append(rotation_deg)
    return translation, rotation


def _segment_drift(segment: pd.DataFrame) -> tuple[float, float]:
    """计算一个连续静止段首尾的位姿误差变化。"""

    first = segment.iloc[0]
    last = segment.iloc[-1]
    first_offset = np.asarray(first["display_pos"], dtype=float) - np.asarray(
        first["reference_pos"], dtype=float
    )
    last_offset = np.asarray(last["display_pos"], dtype=float) - np.asarray(
        last["reference_pos"], dtype=float
    )
    position_drift_mm = float(np.linalg.norm(last_offset - first_offset) * 1000.0)
    first_error = relative_rotation_quat(first["reference_rot"], first["display_rot"])
    last_error = relative_rotation_quat(last["reference_rot"], last["display_rot"])
    rotation_drift_deg = angle_deg(relative_rotation_quat(first_error, last_error))
    return position_drift_mm, rotation_drift_deg


def _median_dt_seconds(time_ms: np.ndarray) -> float:
    """估计连续段的中位采样间隔。"""

    intervals = np.diff(time_ms) * 0.001
    positive = intervals[np.isfinite(intervals) & (intervals > 0.0)]
    return float(np.median(positive)) if len(positive) else 1.0 / 30.0


def _rotation_residual_deg(
    quaternions: np.ndarray,
    *,
    dt: float,
    cutoff_hz: float,
) -> np.ndarray:
    """把姿态转换为 SO(3) 对数向量并返回高通残差范数。"""

    rotations = Rotation.from_quat(quaternions)
    rotation_vectors_deg = np.rad2deg((rotations * rotations[0].inv()).as_rotvec())
    residual = highpass(rotation_vectors_deg, dt=dt, cutoff_hz=cutoff_hz)
    return np.linalg.norm(residual, axis=1)


def _insufficient(context: dict[str, str]) -> dict[str, Any]:
    """构造静止数据不足的上下文行。"""

    return {
        **context,
        "n": 0,
        "segment_count": 0,
        "static_duration_ms": 0.0,
        "position_hp_rms_mm": np.nan,
        "rotation_hp_rms_deg": np.nan,
        "translation_error_mm_median": np.nan,
        "translation_error_mm_p95": np.nan,
        "rotation_error_deg_median": np.nan,
        "rotation_error_deg_p95": np.nan,
        "position_drift_mm": np.nan,
        "rotation_drift_deg": np.nan,
        "insufficient_data": True,
    }


__all__ = ["compute_static_metrics"]

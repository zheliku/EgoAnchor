"""RQ2 参考轨迹、active-motion 与局部运动拟合。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation

from egoanchor.eval.metrics import is_pose_value, slerp_lerp_resample

from .contract import (
    ACTIVE_GAP_FILL_MS,
    ACTIVE_MIN_RUN_MS,
    ACTIVE_ROTATION_MIN_DEG_S,
    ACTIVE_TARGET_RATIO,
    ACTIVE_TRANSLATION_MIN_M_S,
    LAG_GAP_ABSOLUTE_CAP_MS,
    LAG_GAP_FACTOR,
    LAG_GAP_MIN_MS,
    PRE_IMAGE_FIT_WINDOW_MS,
    PRE_IMAGE_MIN_SAMPLES,
)


@dataclass(frozen=True)
class MotionFit:
    """图像前局部参考运动的稳健拟合结果。"""

    linear_velocity_m_s: np.ndarray | None
    angular_velocity_rad_s: np.ndarray | None
    linear_speed_cv: float
    angular_speed_cv: float
    linear_axis_consistency: float
    angular_axis_consistency: float


def annotate_active_motion(output: pd.DataFrame) -> pd.DataFrame:
    """按 trial 的参考轨迹生成 active-motion 标记和稳健速度列。"""

    out = output.copy()
    out["active_motion"] = False
    out["gt_linear_speed_smooth_m_s"] = np.nan
    out["gt_angular_speed_smooth_rad_s"] = np.nan
    if out.empty or not {"rq2_condition", "rq2_trial_id"}.issubset(out.columns):
        return out

    trial_id = pd.to_numeric(out["rq2_trial_id"], errors="coerce")
    trial_rows = out[
        out["rq2_condition"].fillna("none").astype(str).isin(
            ("slow_translation", "fast_motion", "rotation")
        )
        & (trial_id > 0)
    ]
    for (condition, current_trial), group in trial_rows.groupby(
        ["rq2_condition", "rq2_trial_id"], sort=True
    ):
        frames = _unique_trial_frames(group)
        if frames.empty:
            continue
        linear_speed, angular_speed = _smoothed_speed(frames)
        target_linear = _single_finite(frames.get("rq2_target_linear_speed_m_s"))
        target_angular = _single_finite(frames.get("rq2_target_angular_speed_deg_s"))
        if str(condition) == "rotation":
            threshold = np.deg2rad(
                max(
                    ACTIVE_ROTATION_MIN_DEG_S,
                    ACTIVE_TARGET_RATIO * target_angular if np.isfinite(target_angular) else 0.0,
                )
            )
            active = angular_speed >= threshold
        else:
            threshold = max(
                ACTIVE_TRANSLATION_MIN_M_S,
                ACTIVE_TARGET_RATIO * target_linear if np.isfinite(target_linear) else 0.0,
            )
            active = linear_speed >= threshold
        times = frames["render_mono_ms"].to_numpy(dtype=float)
        active = _bridge_short_gaps(active, times, ACTIVE_GAP_FILL_MS)
        active = _remove_short_runs(active, times, ACTIVE_MIN_RUN_MS)
        key = "tick_index" if "tick_index" in frames.columns else "render_mono_ms"
        key_to_index = {
            value: index for index, value in enumerate(frames[key].to_numpy())
        }
        mask = (
            out["rq2_condition"].astype(str).eq(str(condition))
            & pd.to_numeric(out["rq2_trial_id"], errors="coerce").eq(float(current_trial))
        )
        mapped = out.loc[mask, key].map(key_to_index)
        valid = mapped.notna()
        indices = mapped.loc[valid].astype(int).to_numpy()
        target_index = mapped.index[valid]
        out.loc[target_index, "active_motion"] = active[indices]
        out.loc[target_index, "gt_linear_speed_smooth_m_s"] = linear_speed[indices]
        out.loc[target_index, "gt_angular_speed_smooth_rad_s"] = angular_speed[indices]
    return out


def build_gt_trajectory(output: pd.DataFrame) -> pd.DataFrame:
    """提取按渲染时间去重的参考轨迹，并保留显式有效连续段。"""

    needed = ("render_mono_ms", "gt_pos", "gt_rot")
    columns = [*needed, "_gt_segment"]
    if output.empty or any(column not in output.columns for column in needed):
        return pd.DataFrame(columns=columns)
    valid = reference_valid_mask(output)
    work = output[list(needed)].copy()
    work["_gt_valid"] = (
        valid.fillna(False).astype(bool)
        & output["gt_pos"].map(is_pose_value)
        & output["gt_rot"].map(is_pose_value)
    )
    work["render_mono_ms"] = pd.to_numeric(work["render_mono_ms"], errors="coerce")
    work = work[work["render_mono_ms"].notna()].sort_values(
        "render_mono_ms", kind="stable"
    )
    work = work.drop_duplicates("render_mono_ms", keep="first").reset_index(drop=True)
    if work.empty:
        return pd.DataFrame(columns=columns)

    times = work["render_mono_ms"].to_numpy(dtype=float)
    valid_values = work["_gt_valid"].to_numpy(dtype=bool)
    segment_ids = np.full(len(work), -1, dtype=int)
    segment_id = -1
    previous_valid = False
    gap_limit = gap_threshold(times)
    for index, is_valid in enumerate(valid_values):
        if not is_valid:
            previous_valid = False
            continue
        has_gap = index > 0 and times[index] - times[index - 1] > gap_limit
        if not previous_valid or has_gap:
            segment_id += 1
        segment_ids[index] = segment_id
        previous_valid = True
    work["_gt_segment"] = segment_ids
    return work.loc[work["_gt_valid"], columns].reset_index(drop=True)


def interpolate_gt(
    trajectory: pd.DataFrame,
    mono_ms: float,
) -> tuple[np.ndarray | None, np.ndarray | None]:
    """在有效连续段内插值参考 pose；不做边界外外推。"""

    if trajectory.empty or not np.isfinite(mono_ms):
        return None, None
    times = trajectory["render_mono_ms"].to_numpy(dtype=float)
    if mono_ms < times[0] or mono_ms > times[-1]:
        return None, None
    right = int(np.searchsorted(times, mono_ms, side="left"))
    if right < len(times) and np.isclose(times[right], mono_ms, atol=1e-9):
        return (
            np.asarray(trajectory.iloc[right]["gt_pos"], dtype=float),
            np.asarray(trajectory.iloc[right]["gt_rot"], dtype=float),
        )
    if right == 0 or right >= len(times) or gt_segment_at(trajectory, mono_ms) is None:
        return None, None
    positions = np.vstack(trajectory["gt_pos"].to_numpy())
    rotations = np.vstack(trajectory["gt_rot"].to_numpy())
    pos, rot = slerp_lerp_resample(times, positions, rotations, np.array([mono_ms]))
    return pos[0], rot[0]


def gt_segment_at(trajectory: pd.DataFrame, mono_ms: float) -> int | None:
    """返回时刻所在的参考有效连续段。"""

    if trajectory.empty or "_gt_segment" not in trajectory.columns:
        return None
    times = trajectory["render_mono_ms"].to_numpy(dtype=float)
    right = int(np.searchsorted(times, mono_ms, side="left"))
    if right < len(times) and np.isclose(times[right], mono_ms, atol=1e-9):
        return int(trajectory.iloc[right]["_gt_segment"])
    if right == 0 or right >= len(times):
        return None
    left = int(trajectory.iloc[right - 1]["_gt_segment"])
    right_segment = int(trajectory.iloc[right]["_gt_segment"])
    return left if left == right_segment else None


def fit_pre_image_motion(trajectory: pd.DataFrame, image_ms: float) -> MotionFit:
    """用固定 pre-image 窗口拟合速度，并量化稳态与轴一致性。"""

    empty = MotionFit(None, None, np.nan, np.nan, np.nan, np.nan)
    if trajectory.empty or not np.isfinite(image_ms):
        return empty
    start_ms = image_ms - PRE_IMAGE_FIT_WINDOW_MS
    times = trajectory["render_mono_ms"].to_numpy(dtype=float)
    if start_ms < float(times[0]) or image_ms > float(times[-1]):
        return empty
    window = trajectory[
        (trajectory["render_mono_ms"] >= start_ms)
        & (trajectory["render_mono_ms"] <= image_ms)
    ].copy()
    window = _with_interpolated_boundary(window, trajectory, start_ms)
    window = _with_interpolated_boundary(window, trajectory, image_ms)
    window = window.sort_values("render_mono_ms", kind="stable").drop_duplicates(
        "render_mono_ms", keep="first"
    )
    if len(window) < PRE_IMAGE_MIN_SAMPLES:
        return empty
    segments = window["_gt_segment"].dropna().astype(int).unique()
    if len(segments) != 1:
        return empty
    window_times = window["render_mono_ms"].to_numpy(dtype=float)
    if np.any(np.diff(window_times) > gap_threshold(times)):
        return empty
    positions = np.vstack(window["gt_pos"].to_numpy())
    rotations = np.vstack(window["gt_rot"].to_numpy())
    linear_velocity = _theil_sen_velocity(window_times, positions)
    angular_velocity = _median_world_angular_velocity(window_times, rotations)
    linear_steps = _linear_step_velocities(window_times, positions)
    angular_steps = _angular_step_velocities(window_times, rotations)
    return MotionFit(
        linear_velocity,
        angular_velocity,
        _speed_cv(linear_steps),
        _speed_cv(angular_steps),
        _axis_consistency(linear_steps, linear_velocity),
        _axis_consistency(angular_steps, angular_velocity),
    )


def active_at_times(
    annotated_output: pd.DataFrame,
    condition: str,
    trial_id: int,
    times_ms: np.ndarray,
) -> np.ndarray:
    """按最近参考渲染 tick 查询给定时刻是否处于 active-motion。"""

    group = annotated_output[
        annotated_output["rq2_condition"].astype(str).eq(str(condition))
        & pd.to_numeric(annotated_output["rq2_trial_id"], errors="coerce").eq(trial_id)
    ]
    frames = _unique_trial_frames(group)
    if frames.empty:
        return np.zeros(len(times_ms), dtype=bool)
    frame_times = frames["render_mono_ms"].to_numpy(dtype=float)
    active = frames["active_motion"].fillna(False).to_numpy(dtype=bool)
    right = np.searchsorted(frame_times, times_ms, side="left")
    right = np.clip(right, 0, len(frame_times) - 1)
    left = np.clip(right - 1, 0, len(frame_times) - 1)
    use_left = np.abs(times_ms - frame_times[left]) <= np.abs(frame_times[right] - times_ms)
    nearest = np.where(use_left, left, right)
    inside = (times_ms >= frame_times[0]) & (times_ms <= frame_times[-1])
    result = np.zeros(len(times_ms), dtype=bool)
    result[inside] = active[nearest[inside]]
    return result


def active_duration_seconds(frames: pd.DataFrame) -> float:
    """按相邻渲染间隔累计 active-motion 时长。"""

    if frames.empty or len(frames) < 2:
        return 0.0
    work = frames.sort_values("render_mono_ms", kind="stable")
    times = work["render_mono_ms"].to_numpy(dtype=float)
    active = work["active_motion"].fillna(False).to_numpy(dtype=bool)
    intervals = np.diff(times)
    valid = active[:-1] & np.isfinite(intervals) & (intervals > 0.0)
    return float(np.sum(intervals[valid]) / 1000.0)


def world_rotation_vector(
    start: np.ndarray | None,
    end: np.ndarray | None,
) -> np.ndarray | None:
    """返回 ``Log(R_end R_start^-1)`` 的世界系旋转向量。"""

    if start is None or end is None:
        return None
    start_rotation = Rotation.from_quat(start)
    end_rotation = Rotation.from_quat(end)
    return np.asarray((end_rotation * start_rotation.inv()).as_rotvec(), dtype=float)


def gap_threshold(times_ms: np.ndarray) -> float:
    """根据有效样本间隔计算连续轨迹允许的最大缺口。"""

    intervals = np.diff(times_ms)
    positive = intervals[np.isfinite(intervals) & (intervals > 0.0)]
    if len(positive) == 0:
        return LAG_GAP_MIN_MS
    return min(
        max(LAG_GAP_MIN_MS, LAG_GAP_FACTOR * float(np.median(positive))),
        LAG_GAP_ABSOLUTE_CAP_MS,
    )


def unique_trial_frames(group: pd.DataFrame) -> pd.DataFrame:
    """返回按 tick 去重并按时间排序的 trial 帧。"""

    return _unique_trial_frames(group)


def reference_valid_mask(frames: pd.DataFrame) -> pd.Series:
    """返回动态参考轨迹的有效掩码，优先要求真实的新鲜追踪样本。"""

    valid = frames.get("gt_pose_valid", frames.get("valid", False))
    if not isinstance(valid, pd.Series):
        valid = pd.Series(False, index=frames.index)
    result = valid.fillna(False).astype(bool)
    fresh = frames.get("gt_pose_fresh")
    if isinstance(fresh, pd.Series):
        result &= fresh.fillna(False).astype(bool)
    return result


def _unique_trial_frames(group: pd.DataFrame) -> pd.DataFrame:
    """从长表中保留每个渲染 tick 的一行。"""

    if group.empty:
        return group.copy()
    work = group.sort_values(
        [column for column in ("render_mono_ms", "tick_index") if column in group],
        kind="stable",
    )
    key = "tick_index" if "tick_index" in work.columns else "render_mono_ms"
    return work.drop_duplicates(key, keep="first").reset_index(drop=True)


def _smoothed_speed(frames: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """从 GT pose 计算中值平滑后的线速度和角速度。"""

    count = len(frames)
    linear = np.full(count, np.nan, dtype=float)
    angular = np.full(count, np.nan, dtype=float)
    valid_values = reference_valid_mask(frames).to_numpy(dtype=bool)
    times = frames["render_mono_ms"].to_numpy(dtype=float)
    positions = frames["gt_pos"].to_numpy()
    rotations = frames["gt_rot"].to_numpy()
    for index in range(1, count):
        dt_s = (times[index] - times[index - 1]) / 1000.0
        if (
            dt_s <= 0.0
            or not valid_values[index - 1]
            or not valid_values[index]
            or not is_pose_value(positions[index - 1])
            or not is_pose_value(positions[index])
            or not is_pose_value(rotations[index - 1])
            or not is_pose_value(rotations[index])
        ):
            continue
        linear[index] = np.linalg.norm(
            np.asarray(positions[index], dtype=float)
            - np.asarray(positions[index - 1], dtype=float)
        ) / dt_s
        increment = world_rotation_vector(
            np.asarray(rotations[index - 1], dtype=float),
            np.asarray(rotations[index], dtype=float),
        )
        if increment is not None:
            angular[index] = np.linalg.norm(increment) / dt_s
    linear = _rolling_median(linear, window=7)
    angular = _rolling_median(angular, window=7)
    return np.nan_to_num(linear, nan=0.0), np.nan_to_num(angular, nan=0.0)


def _rolling_median(values: np.ndarray, window: int) -> np.ndarray:
    """对速度序列执行居中滚动中值。"""

    return (
        pd.Series(values, dtype=float)
        .rolling(window=window, center=True, min_periods=2)
        .median()
        .to_numpy(dtype=float)
    )


def _bridge_short_gaps(mask: np.ndarray, times: np.ndarray, max_gap_ms: float) -> np.ndarray:
    """填充被 active 段包围的短暂低速间隙。"""

    result = mask.copy()
    intervals = np.diff(times)
    positive = intervals[np.isfinite(intervals) & (intervals > 0.0)]
    nominal_interval = float(np.median(positive)) if len(positive) else 0.0
    index = 0
    while index < len(result):
        if result[index]:
            index += 1
            continue
        start = index
        while index < len(result) and not result[index]:
            index += 1
        end = index
        gap_duration = times[end - 1] - times[start] + nominal_interval
        if start > 0 and end < len(result) and gap_duration <= max_gap_ms:
            result[start:end] = True
    return result


def _remove_short_runs(mask: np.ndarray, times: np.ndarray, min_run_ms: float) -> np.ndarray:
    """删除持续时间不足阈值的孤立 active 段。"""

    result = mask.copy()
    index = 0
    while index < len(result):
        if not result[index]:
            index += 1
            continue
        start = index
        while index < len(result) and result[index]:
            index += 1
        end = index
        duration = times[end - 1] - times[start] if end - start > 1 else 0.0
        if duration < min_run_ms:
            result[start:end] = False
    return result


def _single_finite(values: object) -> float:
    """返回序列中的首个有限值。"""

    if values is None:
        return np.nan
    numeric = pd.to_numeric(values, errors="coerce")
    finite = numeric[np.isfinite(numeric)]
    return float(finite.iloc[0]) if len(finite) else np.nan


def _with_interpolated_boundary(
    window: pd.DataFrame,
    trajectory: pd.DataFrame,
    mono_ms: float,
) -> pd.DataFrame:
    """在局部拟合窗口中补入精确边界采样。"""

    if np.any(np.isclose(window["render_mono_ms"].to_numpy(dtype=float), mono_ms)):
        return window
    pos, rot = interpolate_gt(trajectory, mono_ms)
    segment = gt_segment_at(trajectory, mono_ms)
    if pos is None or rot is None or segment is None:
        return window
    row = pd.DataFrame.from_records(
        [
            {
                "render_mono_ms": mono_ms,
                "gt_pos": pos,
                "gt_rot": rot,
                "_gt_segment": segment,
            }
        ]
    )
    return pd.concat([window, row], ignore_index=True)


def _theil_sen_velocity(times_ms: np.ndarray, positions: np.ndarray) -> np.ndarray | None:
    """用所有样本对斜率的分量中位数估计线速度。"""

    slopes: list[np.ndarray] = []
    for first in range(len(times_ms) - 1):
        elapsed_s = (times_ms[first + 1 :] - times_ms[first]) / 1000.0
        valid = elapsed_s > 0.0
        if np.any(valid):
            delta = positions[first + 1 :] - positions[first]
            slopes.extend(delta[valid] / elapsed_s[valid, None])
    if not slopes:
        return None
    return np.median(np.vstack(slopes), axis=0)


def _median_world_angular_velocity(
    times_ms: np.ndarray,
    rotations: np.ndarray,
) -> np.ndarray | None:
    """用相邻 SO(3) 增量的分量中位数估计角速度。"""

    velocities = _angular_step_velocities(times_ms, rotations)
    return np.median(velocities, axis=0) if len(velocities) else None


def _linear_step_velocities(times_ms: np.ndarray, positions: np.ndarray) -> np.ndarray:
    """构造相邻参考位置的线速度向量。"""

    dt = np.diff(times_ms) / 1000.0
    valid = dt > 0.0
    if not np.any(valid):
        return np.empty((0, 3), dtype=float)
    return np.diff(positions, axis=0)[valid] / dt[valid, None]


def _angular_step_velocities(times_ms: np.ndarray, rotations: np.ndarray) -> np.ndarray:
    """构造相邻参考姿态的世界系角速度向量。"""

    values: list[np.ndarray] = []
    for index in range(1, len(times_ms)):
        elapsed_s = (times_ms[index] - times_ms[index - 1]) / 1000.0
        if elapsed_s <= 0.0:
            continue
        increment = world_rotation_vector(rotations[index - 1], rotations[index])
        if increment is not None:
            values.append(increment / elapsed_s)
    return np.vstack(values) if values else np.empty((0, 3), dtype=float)


def _speed_cv(vectors: np.ndarray) -> float:
    """用 MAD/median 量化局部速度稳定性。"""

    if len(vectors) == 0:
        return np.nan
    speeds = np.linalg.norm(vectors, axis=1)
    median = float(np.median(speeds))
    if median <= 1e-9:
        return np.nan
    mad = float(np.median(np.abs(speeds - median)))
    return mad / median


def _axis_consistency(vectors: np.ndarray, direction: np.ndarray | None) -> float:
    """量化局部速度向量与稳健主方向的同向程度。"""

    if direction is None or len(vectors) == 0:
        return np.nan
    direction_norm = float(np.linalg.norm(direction))
    speeds = np.linalg.norm(vectors, axis=1)
    valid = speeds > 1e-9
    if direction_norm <= 1e-9 or not np.any(valid):
        return np.nan
    axis = direction / direction_norm
    dots = (vectors[valid] / speeds[valid, None]) @ axis
    return float(np.median(dots))


__all__ = [
    "MotionFit",
    "active_at_times",
    "active_duration_seconds",
    "annotate_active_motion",
    "build_gt_trajectory",
    "fit_pre_image_motion",
    "gap_threshold",
    "gt_segment_at",
    "interpolate_gt",
    "unique_trial_frames",
    "reference_valid_mask",
    "world_rotation_vector",
]

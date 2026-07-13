"""RQ2 平台参考速度与有效运动区间。"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation

from egoanchor.eval.metrics import is_pose_value

from .contract import (
    ACTIVE_GAP_FILL_MS,
    ACTIVE_MIN_RUN_MS,
    ACTIVE_ROTATION_MIN_DEG_S,
    ACTIVE_TARGET_RATIO,
    ACTIVE_TRANSLATION_MIN_M_S,
    RQ2_CONDITIONS,
    RQ2Config,
)


def annotate_active_motion(
    output: pd.DataFrame,
    config: RQ2Config | None = None,
) -> pd.DataFrame:
    """按试次标出运动段，并应用论文声明的速度上限。"""

    settings = config or RQ2Config()
    out = output.copy()
    out["active_motion"] = False
    out["analysis_motion"] = False
    out["gt_linear_speed_smooth_m_s"] = np.nan
    out["gt_angular_speed_smooth_deg_s"] = np.nan
    if out.empty or not {"rq2_condition", "rq2_trial_id"}.issubset(out.columns):
        return out

    trial_id = pd.to_numeric(out["rq2_trial_id"], errors="coerce")
    trials = out[
        out["rq2_condition"].fillna("none").astype(str).isin(RQ2_CONDITIONS)
        & (trial_id > 0)
    ]
    group_columns = ["rq2_condition", "rq2_trial_id"]
    if "session_id" in trials.columns:
        group_columns.insert(0, "session_id")
    for key, group in trials.groupby(group_columns, sort=True):
        if "session_id" in trials.columns:
            session_id, condition, current_trial = key
        else:
            session_id = None
            condition, current_trial = key
        frames = unique_trial_frames(group)
        if frames.empty:
            continue
        linear_speed, angular_speed = _smoothed_speed(frames)
        target_linear = _single_finite(frames.get("rq2_target_linear_speed_m_s"))
        target_angular = _single_finite(frames.get("rq2_target_angular_speed_deg_s"))
        if str(condition) == "rotation":
            threshold = max(
                ACTIVE_ROTATION_MIN_DEG_S,
                ACTIVE_TARGET_RATIO * target_angular if np.isfinite(target_angular) else 0.0,
            )
            active = angular_speed >= threshold
            within_speed = angular_speed <= settings.max_rotation_speed_deg_s
        else:
            threshold = max(
                ACTIVE_TRANSLATION_MIN_M_S,
                ACTIVE_TARGET_RATIO * target_linear if np.isfinite(target_linear) else 0.0,
            )
            active = linear_speed >= threshold
            within_speed = linear_speed <= settings.max_translation_speed_m_s

        times = frames["render_mono_ms"].to_numpy(dtype=float)
        active = _bridge_short_gaps(active, times, ACTIVE_GAP_FILL_MS)
        active = _remove_short_runs(active, times, ACTIVE_MIN_RUN_MS)
        reference_valid = reference_valid_mask(frames).to_numpy(dtype=bool)
        analysis = active & within_speed & reference_valid
        _map_trial_values(
            out,
            frames,
            str(session_id) if session_id is not None else None,
            str(condition),
            int(current_trial),
            active,
            analysis,
            linear_speed,
            angular_speed,
        )
    return out


def active_duration_seconds(
    frames: pd.DataFrame,
    mask_column: str = "analysis_motion",
) -> float:
    """累计标记帧到下一渲染帧之间的运动时长。"""

    if frames.empty or len(frames) < 2 or mask_column not in frames.columns:
        return 0.0
    work = frames.sort_values("render_mono_ms", kind="stable")
    times = pd.to_numeric(work["render_mono_ms"], errors="coerce").to_numpy(dtype=float)
    marked = work[mask_column].fillna(False).to_numpy(dtype=bool)
    intervals = np.diff(times)
    valid = marked[:-1] & marked[1:] & np.isfinite(intervals) & (intervals > 0.0)
    return float(np.sum(intervals[valid]) / 1000.0)


def unique_trial_frames(group: pd.DataFrame) -> pd.DataFrame:
    """从双变体长表中保留每个渲染 tick 的一行。"""

    if group.empty:
        return group.copy()
    sort_columns = [
        column for column in ("render_mono_ms", "tick_index") if column in group.columns
    ]
    work = group.sort_values(sort_columns, kind="stable")
    key = "tick_index" if "tick_index" in work.columns else "render_mono_ms"
    return work.drop_duplicates(key, keep="first").reset_index(drop=True)


def reference_valid_mask(frames: pd.DataFrame) -> pd.Series:
    """返回动态参考位姿有效掩码，并拒绝静止 keep-alive。"""

    valid = frames.get("gt_pose_valid", frames.get("valid", False))
    if not isinstance(valid, pd.Series):
        valid = pd.Series(False, index=frames.index)
    result = valid.fillna(False).astype(bool)
    fresh = frames.get("gt_pose_fresh")
    if not isinstance(fresh, pd.Series):
        return pd.Series(False, index=frames.index)
    keep_alive = frames.get("gt_pose_keep_alive")
    if not isinstance(keep_alive, pd.Series):
        return pd.Series(False, index=frames.index)
    return result & fresh.fillna(False).astype(bool) & ~keep_alive.fillna(False).astype(bool)


def world_rotation_vector(
    start: np.ndarray | None,
    end: np.ndarray | None,
) -> np.ndarray | None:
    """返回世界系 ``Log(R_end R_start^-1)`` 旋转向量。"""

    if start is None or end is None:
        return None
    start_rotation = Rotation.from_quat(start)
    end_rotation = Rotation.from_quat(end)
    return np.asarray((end_rotation * start_rotation.inv()).as_rotvec(), dtype=float)


def world_rotation_vectors_from_reference(
    reference: np.ndarray,
    rotations: np.ndarray,
) -> np.ndarray:
    """返回各姿态相对共同起点的精确世界系 SO(3) 对数向量。"""

    return np.vstack(
        [world_rotation_vector(reference, rotation) for rotation in rotations]
    ) if len(rotations) else np.empty((0, 3), dtype=float)


def _map_trial_values(
    output: pd.DataFrame,
    frames: pd.DataFrame,
    session_id: str | None,
    condition: str,
    trial_id: int,
    active: np.ndarray,
    analysis: np.ndarray,
    linear_speed: np.ndarray,
    angular_speed: np.ndarray,
) -> None:
    """把去重帧上的标记映射回双变体长表。"""

    key = "tick_index" if "tick_index" in frames.columns else "render_mono_ms"
    positions = {value: index for index, value in enumerate(frames[key].to_numpy())}
    mask = (
        output["rq2_condition"].astype(str).eq(condition)
        & pd.to_numeric(output["rq2_trial_id"], errors="coerce").eq(trial_id)
    )
    if session_id is not None:
        mask &= output["session_id"].astype(str).eq(session_id)
    mapped = output.loc[mask, key].map(positions)
    valid = mapped.notna()
    indices = mapped.loc[valid].astype(int).to_numpy()
    target = mapped.index[valid]
    output.loc[target, "active_motion"] = active[indices]
    output.loc[target, "analysis_motion"] = analysis[indices]
    output.loc[target, "gt_linear_speed_smooth_m_s"] = linear_speed[indices]
    output.loc[target, "gt_angular_speed_smooth_deg_s"] = angular_speed[indices]


def _smoothed_speed(frames: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """由参考 pose 计算七帧中值平滑后的线速度与角速度。"""

    count = len(frames)
    linear = np.full(count, np.nan, dtype=float)
    angular = np.full(count, np.nan, dtype=float)
    valid = reference_valid_mask(frames).to_numpy(dtype=bool)
    times = pd.to_numeric(frames["render_mono_ms"], errors="coerce").to_numpy(dtype=float)
    positions = frames["gt_pos"].to_numpy()
    rotations = frames["gt_rot"].to_numpy()
    for index in range(1, count):
        elapsed_s = (times[index] - times[index - 1]) / 1000.0
        if (
            elapsed_s <= 0.0
            or not valid[index - 1]
            or not valid[index]
            or not all(
                is_pose_value(value)
                for value in (
                    positions[index - 1],
                    positions[index],
                    rotations[index - 1],
                    rotations[index],
                )
            )
        ):
            continue
        linear[index] = np.linalg.norm(
            np.asarray(positions[index], dtype=float)
            - np.asarray(positions[index - 1], dtype=float)
        ) / elapsed_s
        increment = world_rotation_vector(
            np.asarray(rotations[index - 1], dtype=float),
            np.asarray(rotations[index], dtype=float),
        )
        if increment is not None:
            angular[index] = np.rad2deg(np.linalg.norm(increment) / elapsed_s)
    return _rolling_median(linear), _rolling_median(angular)


def _rolling_median(values: np.ndarray) -> np.ndarray:
    """执行居中的七帧滚动中值，并把无效速度置零。"""

    smoothed = (
        pd.Series(values, dtype=float)
        .rolling(window=7, center=True, min_periods=2)
        .median()
        .to_numpy(dtype=float)
    )
    return np.nan_to_num(smoothed, nan=0.0)


def _bridge_short_gaps(mask: np.ndarray, times: np.ndarray, max_gap_ms: float) -> np.ndarray:
    """填充被活动段包围的短暂低速间隙。"""

    result = mask.copy()
    positive = np.diff(times)
    positive = positive[np.isfinite(positive) & (positive > 0.0)]
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
        duration = times[end - 1] - times[start] + nominal_interval
        if start > 0 and end < len(result) and duration <= max_gap_ms:
            result[start:end] = True
    return result


def _remove_short_runs(mask: np.ndarray, times: np.ndarray, min_run_ms: float) -> np.ndarray:
    """删除持续时间不足阈值的孤立活动段。"""

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


__all__ = [
    "active_duration_seconds",
    "annotate_active_motion",
    "reference_valid_mask",
    "unique_trial_frames",
    "world_rotation_vector",
    "world_rotation_vectors_from_reference",
]

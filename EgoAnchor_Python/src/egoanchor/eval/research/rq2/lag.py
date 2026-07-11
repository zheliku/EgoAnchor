"""RQ2 轨迹滞后估计与可辨识性诊断。"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation

from egoanchor.eval.metrics import is_pose_value, slerp_lerp_resample

from .contract import (
    LAG_MIN_PEAK_CORRELATION,
    LAG_MIN_PROMINENCE,
    LAG_MIN_SIGNAL_SAMPLES,
    LAG_MIN_SIGNAL_STD,
)
from .trajectory import gap_threshold


@dataclass(frozen=True)
class LagEstimate:
    """单个运动通道的 lag 与可辨识性诊断。"""

    lag_ms: float = np.nan
    peak_correlation: float = np.nan
    peak_prominence: float = np.nan
    status: str = "insufficient_samples"
    sample_count: int = 0


@dataclass(frozen=True)
class StreamLag:
    """一个 pose 流的平移、旋转 lag 诊断。"""

    translation: LagEstimate
    rotation: LagEstimate
    segment_count: int


def estimate_stream_lag(
    trajectory: pd.DataFrame,
    times: pd.Series,
    positions: pd.Series,
    rotations: pd.Series,
    *,
    valid_mask: pd.Series | None = None,
    max_lag_ms: float = 500.0,
) -> StreamLag:
    """按 runtime 有效连续段估计平移与旋转响应滞后。"""

    empty = StreamLag(LagEstimate(), LagEstimate(), 0)
    if trajectory.empty or len(times) < 6:
        return empty
    time_values = pd.to_numeric(times, errors="coerce").to_numpy(dtype=float)
    allowed = (
        valid_mask.fillna(False).to_numpy(dtype=bool)
        if isinstance(valid_mask, pd.Series)
        else np.ones(len(time_values), dtype=bool)
    )
    usable = np.zeros(len(time_values), dtype=bool)
    runtime_segment = np.full(len(time_values), -1, dtype=int)
    segment_id = -1
    previous_usable = False
    for index in range(len(time_values)):
        current_usable = bool(
            allowed[index]
            and np.isfinite(time_values[index])
            and is_pose_value(positions.iloc[index])
            and is_pose_value(rotations.iloc[index])
        )
        usable[index] = current_usable
        if not current_usable:
            previous_usable = False
            continue
        if not previous_usable:
            segment_id += 1
        runtime_segment[index] = segment_id
        previous_usable = True
    if int(usable.sum()) < 6:
        return empty
    sample_times = time_values[usable]
    sample_pos = np.vstack(positions.iloc[np.flatnonzero(usable)].to_numpy())
    sample_rot = np.vstack(rotations.iloc[np.flatnonzero(usable)].to_numpy())
    sample_segment = runtime_segment[usable]
    order = np.argsort(sample_times)
    sample_times = sample_times[order]
    sample_pos = sample_pos[order]
    sample_rot = sample_rot[order]
    sample_segment = sample_segment[order]
    unique = np.concatenate(([True], np.diff(sample_times) > 1e-9))
    sample_times = sample_times[unique]
    sample_pos = sample_pos[unique]
    sample_rot = sample_rot[unique]
    sample_segment = sample_segment[unique]
    if len(sample_times) < 6:
        return empty

    translation: list[LagEstimate] = []
    rotation: list[LagEstimate] = []
    segments = _runtime_segments(sample_times, sample_segment)
    for segment in segments:
        translation_result, rotation_result = _estimate_lag_segment(
            trajectory,
            sample_times[segment],
            sample_pos[segment],
            sample_rot[segment],
            max_lag_ms=max_lag_ms,
        )
        translation.append(translation_result)
        rotation.append(rotation_result)
    return StreamLag(
        _combine_segments(translation),
        _combine_segments(rotation),
        len(segments),
    )


def runtime_lag_mask(frames: pd.DataFrame, display_mask: pd.Series) -> pd.Series:
    """生成 display lag 使用的 runtime 有效掩码。

    hold-last 仍进入显示误差，但 runtime 已无输出、处于 Lost/Searching 或正在
    reacquire 时必须切断 lag 连续段，避免把冻结显示解释成可追踪轨迹。
    """

    has_output = frames.get("has_output_pose", False)
    if not isinstance(has_output, pd.Series):
        has_output = pd.Series(False, index=frames.index)
    state = frames.get("anchor_state", pd.Series("", index=frames.index)).astype(str)
    action = frames.get("policy_action", pd.Series("", index=frames.index)).astype(str)
    reason = frames.get("policy_reason", pd.Series("", index=frames.index)).astype(str)
    invalid_state = state.str.lower().str.contains("lost|search|reacquir", regex=True)
    invalid_event = (action + " " + reason).str.lower().str.contains(
        "reacquir", regex=True
    )
    return (
        display_mask.fillna(False).astype(bool)
        & has_output.fillna(False).astype(bool)
        & ~invalid_state
        & ~invalid_event
    )


def _continuous_segments(times_ms: np.ndarray) -> list[slice]:
    """按采样缺口切分，并只保留至少六个 pose 的连续段。"""

    intervals = np.diff(times_ms)
    if not np.any(np.isfinite(intervals) & (intervals > 0.0)):
        return []
    breaks = np.flatnonzero(intervals > gap_threshold(times_ms)) + 1
    boundaries = np.concatenate(([0], breaks, [len(times_ms)]))
    return [
        slice(int(start), int(end))
        for start, end in zip(boundaries[:-1], boundaries[1:])
        if end - start >= 6
    ]


def _runtime_segments(times_ms: np.ndarray, segment_ids: np.ndarray) -> list[slice]:
    """先按显式 runtime 失效边界切段，再按采样时间缺口细分。"""

    segments: list[slice] = []
    for segment_id in np.unique(segment_ids):
        indices = np.flatnonzero(segment_ids == segment_id)
        if len(indices) < 6:
            continue
        start = int(indices[0])
        local_times = times_ms[indices]
        for local in _continuous_segments(local_times):
            segments.append(slice(start + int(local.start), start + int(local.stop)))
    return segments


def _estimate_lag_segment(
    trajectory: pd.DataFrame,
    sample_times: np.ndarray,
    sample_pos: np.ndarray,
    sample_rot: np.ndarray,
    *,
    max_lag_ms: float,
) -> tuple[LagEstimate, LagEstimate]:
    """在一个无 runtime 缺口的连续段内估计 lag。"""

    translation: list[LagEstimate] = []
    rotation: list[LagEstimate] = []
    groups = (
        (group for _, group in trajectory.groupby("_gt_segment", sort=False))
        if "_gt_segment" in trajectory.columns
        else (trajectory,)
    )
    for gt_group in groups:
        current_translation, current_rotation = _estimate_lag_overlap(
            gt_group,
            sample_times,
            sample_pos,
            sample_rot,
            max_lag_ms=max_lag_ms,
        )
        translation.append(current_translation)
        rotation.append(current_rotation)
    return _best_overlap(translation), _best_overlap(rotation)


def _estimate_lag_overlap(
    trajectory: pd.DataFrame,
    sample_times: np.ndarray,
    sample_pos: np.ndarray,
    sample_rot: np.ndarray,
    *,
    max_lag_ms: float,
) -> tuple[LagEstimate, LagEstimate]:
    """在参考连续段与输出连续段的交集内估计 lag。"""

    gt_times = trajectory["render_mono_ms"].to_numpy(dtype=float)
    start = max(float(sample_times[0]), float(gt_times[0]))
    end = min(float(sample_times[-1]), float(gt_times[-1]))
    spacing = np.diff(sample_times)
    finite_spacing = spacing[np.isfinite(spacing) & (spacing > 0.0)]
    if end <= start or len(finite_spacing) == 0:
        empty = LagEstimate(status="no_overlap")
        return empty, empty
    step = float(np.median(finite_spacing))
    grid = np.arange(start, end + step * 0.5, step)
    if len(grid) < 6:
        empty = LagEstimate(status="too_short", sample_count=len(grid))
        return empty, empty
    gt_pos, gt_rot = slerp_lerp_resample(
        gt_times,
        np.vstack(trajectory["gt_pos"].to_numpy()),
        np.vstack(trajectory["gt_rot"].to_numpy()),
        grid,
    )
    stream_pos, stream_rot = slerp_lerp_resample(
        sample_times, sample_pos, sample_rot, grid
    )
    translation = _vector_velocity_lag(gt_pos, stream_pos, step, max_lag_ms)
    rotation = _vector_signal_lag(
        _world_angular_velocity_series(gt_rot, step),
        _world_angular_velocity_series(stream_rot, step),
        step,
        max_lag_ms,
    )
    return translation, rotation


def _vector_velocity_lag(
    reference: np.ndarray,
    estimate: np.ndarray,
    step_ms: float,
    max_lag_ms: float,
) -> LagEstimate:
    """把位置轨迹转换为世界系速度后估计互相关滞后。"""

    elapsed_s = step_ms / 1000.0
    if elapsed_s <= 0.0 or len(reference) < 3:
        return LagEstimate(status="too_short", sample_count=len(reference))
    return _vector_signal_lag(
        np.diff(reference, axis=0) / elapsed_s,
        np.diff(estimate, axis=0) / elapsed_s,
        step_ms,
        max_lag_ms,
    )


def _world_angular_velocity_series(rotations: np.ndarray, step_ms: float) -> np.ndarray:
    """由相邻四元数的世界系 SO(3) 增量构造角速度。"""

    elapsed_s = step_ms / 1000.0
    if elapsed_s <= 0.0 or len(rotations) < 2:
        return np.empty((0, 3), dtype=float)
    rotation = Rotation.from_quat(rotations)
    increments = (rotation[1:] * rotation[:-1].inv()).as_rotvec()
    return np.asarray(increments, dtype=float) / elapsed_s


def _vector_signal_lag(
    reference: np.ndarray,
    estimate: np.ndarray,
    step_ms: float,
    max_lag_ms: float,
) -> LagEstimate:
    """投影到参考主轴后估计 lag，并返回峰值质量诊断。"""

    count = len(reference)
    if reference.shape != estimate.shape or count < LAG_MIN_SIGNAL_SAMPLES:
        return LagEstimate(status="too_short", sample_count=count)
    centered = reference - np.mean(reference, axis=0, keepdims=True)
    if float(np.linalg.norm(centered)) <= 1e-9:
        return LagEstimate(status="low_excitation", sample_count=count)
    _, _, axes = np.linalg.svd(centered, full_matrices=False)
    axis = axes[0]
    ref_signal = reference @ axis
    est_signal = estimate @ axis
    ref_signal -= np.mean(ref_signal)
    est_signal -= np.mean(est_signal)
    if (
        float(np.std(ref_signal)) <= LAG_MIN_SIGNAL_STD
        or float(np.std(est_signal)) <= LAG_MIN_SIGNAL_STD
    ):
        return LagEstimate(status="low_excitation", sample_count=count)
    requested = int(np.floor(max_lag_ms / step_ms))
    required = max(LAG_MIN_SIGNAL_SAMPLES, 2 * requested + LAG_MIN_SIGNAL_SAMPLES)
    if count < required:
        return LagEstimate(status="search_window_too_long", sample_count=count)
    max_lag_samples = min(requested, count - 1)
    min_overlap = max(LAG_MIN_SIGNAL_SAMPLES, int(np.ceil(count * 0.5)))
    candidates: list[tuple[int, float]] = []
    for lag in range(-max_lag_samples, max_lag_samples + 1):
        if lag > 0:
            reference_overlap = ref_signal[:-lag]
            estimate_overlap = est_signal[lag:]
        elif lag < 0:
            reference_overlap = ref_signal[-lag:]
            estimate_overlap = est_signal[:lag]
        else:
            reference_overlap = ref_signal
            estimate_overlap = est_signal
        if len(reference_overlap) < min_overlap:
            continue
        denominator = float(
            np.linalg.norm(reference_overlap) * np.linalg.norm(estimate_overlap)
        )
        if denominator <= 1e-12:
            continue
        correlation = float(np.dot(reference_overlap, estimate_overlap) / denominator)
        if np.isfinite(correlation):
            candidates.append((lag, correlation))
    if not candidates:
        return LagEstimate(status="no_candidates", sample_count=count)
    best_lag, best_correlation = max(candidates, key=lambda item: item[1])
    peak_exclusion = max(1, int(round(100.0 / step_ms)))
    alternatives = [
        correlation
        for lag, correlation in candidates
        if abs(lag - best_lag) > peak_exclusion
    ]
    second = max(alternatives) if alternatives else -1.0
    prominence = float(best_correlation - second)
    if best_correlation < LAG_MIN_PEAK_CORRELATION:
        status = "low_correlation"
    elif prominence < LAG_MIN_PROMINENCE:
        status = "ambiguous_peak"
    elif max_lag_samples > 0 and abs(best_lag) == max_lag_samples:
        status = "boundary_peak"
    else:
        status = "ok"
    lag_ms = float(best_lag * step_ms) if status == "ok" else np.nan
    return LagEstimate(lag_ms, best_correlation, prominence, status, count)


def _best_overlap(estimates: list[LagEstimate]) -> LagEstimate:
    """从多个 GT overlap 中选择样本最多且质量最好的估计。"""

    if not estimates:
        return LagEstimate()
    return max(
        estimates,
        key=lambda value: (
            value.status == "ok",
            value.sample_count,
            value.peak_correlation if np.isfinite(value.peak_correlation) else -np.inf,
        ),
    )


def _combine_segments(estimates: list[LagEstimate]) -> LagEstimate:
    """以连续段为单位合并 lag 结果。"""

    valid = [estimate for estimate in estimates if estimate.status == "ok"]
    if valid:
        return LagEstimate(
            lag_ms=float(np.median([value.lag_ms for value in valid])),
            peak_correlation=float(
                np.median([value.peak_correlation for value in valid])
            ),
            peak_prominence=float(
                np.median([value.peak_prominence for value in valid])
            ),
            status="ok",
            sample_count=int(sum(value.sample_count for value in valid)),
        )
    if not estimates:
        return LagEstimate()
    status = Counter(value.status for value in estimates).most_common(1)[0][0]
    representative = max(estimates, key=lambda value: value.sample_count)
    return LagEstimate(
        peak_correlation=representative.peak_correlation,
        peak_prominence=representative.peak_prominence,
        status=status,
        sample_count=int(sum(value.sample_count for value in estimates)),
    )


__all__ = ["LagEstimate", "StreamLag", "estimate_stream_lag", "runtime_lag_mask"]

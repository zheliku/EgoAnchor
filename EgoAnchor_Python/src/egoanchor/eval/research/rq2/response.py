"""RQ2 响应时序与运动滞后的紧凑描述统计。"""

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
    RQ2_CONDITIONS,
    RQ2Config,
)
from .trajectory import reference_valid_mask


RESPONSE_COLUMNS = [
    "condition",
    "label",
    "n_sessions",
    "n_trials",
    "analysis_frame_count",
    "observation_age_sample_count",
    "observation_age_median_ms",
    "observation_age_p95_ms",
    "smoothing_delay_sample_count",
    "smoothing_delay_coverage",
    "smoothing_delay_median_ms",
    "smoothing_delay_p95_ms",
    "empirical_lag_ms",
    "lag_peak_correlation",
    "lag_peak_prominence",
    "lag_status",
    "lag_trial_count",
    "lag_valid_trial_count",
    "lag_valid_sample_count",
    "lag_total_sample_count",
    "lag_sample_coverage",
]


@dataclass(frozen=True)
class LagEstimate:
    """一个连续运动段的滞后与可辨识性诊断。"""

    lag_ms: float = np.nan
    peak_correlation: float = np.nan
    peak_prominence: float = np.nan
    status: str = "insufficient_samples"
    sample_count: int = 0
    valid_sample_count: int = 0
    total_sample_count: int = 0


def compute_response_summary(
    output: pd.DataFrame,
    config: RQ2Config | None = None,
) -> pd.DataFrame:
    """按运动任务与系统配置汇总观测年龄、策略延迟和经验运动滞后。"""

    if output.empty:
        return pd.DataFrame(columns=RESPONSE_COLUMNS)
    settings = config or RQ2Config()
    trial_id = pd.to_numeric(output.get("rq2_trial_id", -1), errors="coerce")
    work = output[
        output.get("rq2_condition", pd.Series("none", index=output.index))
        .astype(str)
        .isin(RQ2_CONDITIONS)
        & (trial_id > 0)
    ].copy()
    rows: list[dict[str, object]] = []
    for (condition, label), group in work.groupby(
        ["rq2_condition", "label"], sort=True
    ):
        analysis = group.get("analysis_motion", False)
        if not isinstance(analysis, pd.Series):
            analysis = pd.Series(False, index=group.index)
        frames = group[analysis.fillna(False).astype(bool)]
        observation_age = _finite_values(frames.get("observation_age_ms"))
        smoothing_delay = _finite_values(frames.get("smoothing_delay_ms"))
        estimates = [
            _estimate_trial_lag(
                trial,
                str(condition),
                settings.max_lag_ms,
                settings.lag_sample_hz,
                settings.min_lag_sample_coverage,
            )
            for _, trial in group.groupby(["session_id", "rq2_trial_id"], sort=True)
        ]
        valid = [estimate for estimate in estimates if estimate.status == "ok"]
        representative = _representative_estimate(estimates)
        valid_samples = int(sum(estimate.valid_sample_count for estimate in estimates))
        total_samples = int(sum(estimate.total_sample_count for estimate in estimates))
        trials = group[["session_id", "rq2_trial_id"]].drop_duplicates()
        rows.append(
            {
                "condition": str(condition),
                "label": str(label),
                "n_sessions": int(group["session_id"].astype(str).nunique()),
                "n_trials": int(len(trials)),
                "analysis_frame_count": int(len(frames)),
                "observation_age_sample_count": int(len(observation_age)),
                "observation_age_median_ms": _percentile(observation_age, 50),
                "observation_age_p95_ms": _percentile(observation_age, 95),
                "smoothing_delay_sample_count": int(len(smoothing_delay)),
                "smoothing_delay_coverage": (
                    float(len(smoothing_delay) / len(frames)) if len(frames) else np.nan
                ),
                "smoothing_delay_median_ms": _percentile(smoothing_delay, 50),
                "smoothing_delay_p95_ms": _percentile(smoothing_delay, 95),
                "empirical_lag_ms": (
                    float(np.median([estimate.lag_ms for estimate in valid]))
                    if valid
                    else np.nan
                ),
                "lag_peak_correlation": (
                    float(np.median([estimate.peak_correlation for estimate in valid]))
                    if valid
                    else representative.peak_correlation
                ),
                "lag_peak_prominence": (
                    float(np.median([estimate.peak_prominence for estimate in valid]))
                    if valid
                    else representative.peak_prominence
                ),
                "lag_status": "ok" if valid else representative.status,
                "lag_trial_count": int(len(estimates)),
                "lag_valid_trial_count": int(len(valid)),
                "lag_valid_sample_count": valid_samples,
                "lag_total_sample_count": total_samples,
                "lag_sample_coverage": (
                    float(valid_samples / total_samples) if total_samples else np.nan
                ),
            }
        )
    return pd.DataFrame.from_records(rows, columns=RESPONSE_COLUMNS)


def _estimate_trial_lag(
    trial: pd.DataFrame,
    condition: str,
    max_lag_ms: float,
    sample_hz: float,
    min_sample_coverage: float,
) -> LagEstimate:
    """在单试次连续有效段内估计显示轨迹相对平台参考的运动滞后。"""

    frames = trial.sort_values("render_mono_ms", kind="stable").reset_index(drop=True)
    if len(frames) < LAG_MIN_SIGNAL_SAMPLES + 1:
        return LagEstimate(sample_count=max(0, len(frames) - 1))
    allowed = _lag_valid_mask(frames).to_numpy(dtype=bool)
    estimates = [
        _estimate_segment_lag(
            frames.iloc[start:end],
            condition,
            max_lag_ms,
            sample_hz,
        )
        for start, end in _continuous_runs(frames, allowed)
    ]
    total_samples = int(sum(estimate.sample_count for estimate in estimates))
    valid = [estimate for estimate in estimates if estimate.status == "ok"]
    valid_samples = int(sum(estimate.sample_count for estimate in valid))
    coverage = float(valid_samples / total_samples) if total_samples else 0.0
    if valid and coverage >= min_sample_coverage:
        return LagEstimate(
            lag_ms=float(np.median([estimate.lag_ms for estimate in valid])),
            peak_correlation=float(
                np.median([estimate.peak_correlation for estimate in valid])
            ),
            peak_prominence=float(
                np.median([estimate.peak_prominence for estimate in valid])
            ),
            status="ok",
            sample_count=total_samples,
            valid_sample_count=valid_samples,
            total_sample_count=total_samples,
        )
    if valid:
        return LagEstimate(
            peak_correlation=float(
                np.median([estimate.peak_correlation for estimate in valid])
            ),
            peak_prominence=float(
                np.median([estimate.peak_prominence for estimate in valid])
            ),
            status="low_coverage",
            sample_count=total_samples,
            valid_sample_count=valid_samples,
            total_sample_count=total_samples,
        )
    representative = _representative_estimate(estimates)
    return LagEstimate(
        peak_correlation=representative.peak_correlation,
        peak_prominence=representative.peak_prominence,
        status=representative.status,
        sample_count=total_samples,
        valid_sample_count=0,
        total_sample_count=total_samples,
    )


def _lag_valid_mask(frames: pd.DataFrame) -> pd.Series:
    """返回运动滞后估计使用的连续 runtime 有效帧。"""

    analysis = frames.get("analysis_motion", False)
    if not isinstance(analysis, pd.Series):
        analysis = pd.Series(False, index=frames.index)
    has_output = frames.get("has_output_pose", False)
    if not isinstance(has_output, pd.Series):
        has_output = pd.Series(False, index=frames.index)
    has_display = frames.get("has_display_pose", has_output)
    if not isinstance(has_display, pd.Series):
        has_display = pd.Series(False, index=frames.index)
    state = frames.get("anchor_state", pd.Series("", index=frames.index)).astype(str)
    event = (
        frames.get("policy_action", pd.Series("", index=frames.index)).astype(str)
        + " "
        + frames.get("policy_reason", pd.Series("", index=frames.index)).astype(str)
    ).str.lower()
    invalid_runtime = state.str.lower().str.contains("lost|search|reacquir", regex=True)
    invalid_runtime |= event.str.contains("reacquir", regex=True)
    poses = (
        frames["gt_pos"].map(is_pose_value)
        & frames["gt_rot"].map(is_pose_value)
        & frames["display_pos"].map(is_pose_value)
        & frames["display_rot"].map(is_pose_value)
    )
    return (
        analysis.fillna(False).astype(bool)
        & reference_valid_mask(frames)
        & has_output.fillna(False).astype(bool)
        & has_display.fillna(False).astype(bool)
        & poses
        & ~invalid_runtime
    )


def _continuous_runs(frames: pd.DataFrame, allowed: np.ndarray) -> list[tuple[int, int]]:
    """按分析掩码与采样缺口切分连续帧段。"""

    times = pd.to_numeric(frames["render_mono_ms"], errors="coerce").to_numpy(dtype=float)
    intervals = np.diff(times)
    positive = intervals[np.isfinite(intervals) & (intervals > 0.0)]
    maximum_gap = max(100.0, 2.5 * float(np.median(positive))) if len(positive) else 100.0
    runs: list[tuple[int, int]] = []
    index = 0
    while index < len(frames):
        if not allowed[index] or not np.isfinite(times[index]):
            index += 1
            continue
        start = index
        while (
            index + 1 < len(frames)
            and allowed[index + 1]
            and np.isfinite(times[index + 1])
            and 0.0 < times[index + 1] - times[index] <= maximum_gap
        ):
            index += 1
        if index + 1 - start >= LAG_MIN_SIGNAL_SAMPLES + 1:
            runs.append((start, index + 1))
        index += 1
    return runs


def _estimate_segment_lag(
    frames: pd.DataFrame,
    condition: str,
    max_lag_ms: float,
    sample_hz: float,
) -> LagEstimate:
    """把连续段按时间均匀重采样，再估计速度互相关滞后。"""

    times = pd.to_numeric(frames["render_mono_ms"], errors="coerce").to_numpy(dtype=float)
    if sample_hz <= 0.0 or len(times) < 2:
        return LagEstimate(status="too_short")
    step_ms = 1000.0 / sample_hz
    grid = np.arange(times[0], times[-1] + step_ms * 0.5, step_ms)
    sample_count = max(0, len(grid) - 1)
    if sample_count < LAG_MIN_SIGNAL_SAMPLES:
        return LagEstimate(status="too_short", sample_count=sample_count)
    gt_pos, gt_rot = slerp_lerp_resample(
        times,
        np.vstack(frames["gt_pos"].to_numpy()),
        np.vstack(frames["gt_rot"].to_numpy()),
        grid,
    )
    display_pos, display_rot = slerp_lerp_resample(
        times,
        np.vstack(frames["display_pos"].to_numpy()),
        np.vstack(frames["display_rot"].to_numpy()),
        grid,
    )
    elapsed_s = step_ms / 1000.0
    if condition == "rotation":
        reference = _world_angular_velocity(gt_rot, elapsed_s)
        estimate = _world_angular_velocity(display_rot, elapsed_s)
    else:
        reference = np.diff(gt_pos, axis=0) / elapsed_s
        estimate = np.diff(display_pos, axis=0) / elapsed_s
    return _vector_signal_lag(reference, estimate, step_ms, max_lag_ms)


def _world_angular_velocity(rotations: np.ndarray, elapsed_s: float) -> np.ndarray:
    """由相邻四元数的世界系 SO(3) 增量构造角速度。"""

    values = Rotation.from_quat(rotations)
    increments = (values[1:] * values[:-1].inv()).as_rotvec()
    return np.asarray(increments, dtype=float) / elapsed_s


def _vector_signal_lag(
    reference: np.ndarray,
    estimate: np.ndarray,
    step_ms: float,
    max_lag_ms: float,
) -> LagEstimate:
    """投影到参考速度主轴后估计正值表示输出落后的运动滞后。"""

    count = len(reference)
    if reference.shape != estimate.shape or count < LAG_MIN_SIGNAL_SAMPLES:
        return LagEstimate(status="too_short", sample_count=count)
    centered = reference - np.mean(reference, axis=0, keepdims=True)
    if float(np.linalg.norm(centered)) <= 1e-9:
        return LagEstimate(status="low_excitation", sample_count=count)
    _, _, axes = np.linalg.svd(centered, full_matrices=False)
    axis = axes[0]
    reference_signal = reference @ axis
    estimate_signal = estimate @ axis
    if (
        float(np.std(reference_signal)) <= LAG_MIN_SIGNAL_STD
        or float(np.std(estimate_signal)) <= LAG_MIN_SIGNAL_STD
    ):
        return LagEstimate(status="low_excitation", sample_count=count)
    requested = int(np.floor(max_lag_ms / step_ms))
    required = max(LAG_MIN_SIGNAL_SAMPLES, 2 * requested + LAG_MIN_SIGNAL_SAMPLES)
    if requested < 1 or count < required:
        return LagEstimate(status="search_window_too_long", sample_count=count)
    minimum_overlap = max(LAG_MIN_SIGNAL_SAMPLES, int(np.ceil(count * 0.5)))
    candidates: list[tuple[int, float]] = []
    for lag in range(-requested, requested + 1):
        if lag > 0:
            reference_overlap = reference_signal[:-lag]
            estimate_overlap = estimate_signal[lag:]
        elif lag < 0:
            reference_overlap = reference_signal[-lag:]
            estimate_overlap = estimate_signal[:lag]
        else:
            reference_overlap = reference_signal
            estimate_overlap = estimate_signal
        if len(reference_overlap) < minimum_overlap:
            continue
        reference_overlap = reference_overlap - np.mean(reference_overlap)
        estimate_overlap = estimate_overlap - np.mean(estimate_overlap)
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
    exclusion = max(1, int(round(100.0 / step_ms)))
    alternatives = [
        correlation
        for lag, correlation in candidates
        if abs(lag - best_lag) > exclusion
    ]
    prominence = float(best_correlation - max(alternatives)) if alternatives else np.nan
    if best_correlation < LAG_MIN_PEAK_CORRELATION:
        status = "low_correlation"
    elif not np.isfinite(prominence) or prominence < LAG_MIN_PROMINENCE:
        status = "ambiguous_peak"
    elif abs(best_lag) == requested:
        status = "boundary_peak"
    else:
        status = "ok"
    return LagEstimate(
        lag_ms=float(best_lag * step_ms) if status == "ok" else np.nan,
        peak_correlation=best_correlation,
        peak_prominence=prominence,
        status=status,
        sample_count=count,
    )


def _representative_estimate(estimates: list[LagEstimate]) -> LagEstimate:
    """在无有效 lag 时返回样本最多的代表性诊断。"""

    if not estimates:
        return LagEstimate()
    status = Counter(estimate.status for estimate in estimates).most_common(1)[0][0]
    candidates = [estimate for estimate in estimates if estimate.status == status]
    return max(
        candidates,
        key=lambda estimate: (
            estimate.sample_count,
            estimate.peak_correlation
            if np.isfinite(estimate.peak_correlation)
            else -np.inf,
        ),
    )


def _finite_values(values: object) -> np.ndarray:
    """把表列转换为有限浮点数组。"""

    if not isinstance(values, pd.Series):
        return np.empty(0, dtype=float)
    numeric = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    return numeric[np.isfinite(numeric)]


def _percentile(values: np.ndarray, percentile: float) -> float:
    """返回有限样本分位数；空样本返回 NaN。"""

    return float(np.percentile(values, percentile)) if len(values) else np.nan


__all__ = ["RESPONSE_COLUMNS", "compute_response_summary"]

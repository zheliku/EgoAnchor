"""静止窗口内的 anchor jitter 指标。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation

from .common import highpass, is_pose_value
from .stats import rms


SUMMARY_COLUMNS = [
    "condition",
    "label",
    "n",
    "position_jitter_rms_m",
    "position_jitter_std_m",
    "rotation_jitter_rms_deg",
    "insufficient_data",
]
"""jitter 汇总字段。"""


def compute_jitter(output: pd.DataFrame, *, speed_threshold_mps: float = 0.03, cutoff_hz: float = 1.0) -> pd.DataFrame:
    """在连续 GT 低速段内计算位置与旋转的高频抖动。"""

    if output.empty:
        return _empty_summary()
    rows: list[dict[str, Any]] = []
    for (condition, label), group in output.groupby(["condition", "label"], sort=True):
        usable = _usable_pose_rows(group).sort_values("render_mono_ms")
        if len(usable) < 3:
            rows.append(_insufficient(condition, label, len(usable)))
            continue
        static = _static_mask(usable, speed_threshold_mps)
        sample = usable.loc[static]
        if len(sample) < 3:
            rows.append(_insufficient(condition, label, len(sample)))
            continue
        position_residuals: list[np.ndarray] = []
        rotation_residuals: list[np.ndarray] = []
        sample_count = 0
        for segment in _continuous_segments(sample):
            time_ms = segment["render_mono_ms"].to_numpy(dtype=float)
            dt = _median_dt_seconds(time_ms)
            position = np.vstack(segment["output_pos"].to_numpy())
            position_residuals.append(
                np.linalg.norm(highpass(position, dt=dt, cutoff_hz=cutoff_hz), axis=1)
            )
            rotation_residuals.append(
                _rotation_residual_deg(
                    np.vstack(segment["output_rot"].to_numpy()),
                    dt=dt,
                    cutoff_hz=cutoff_hz,
                )
            )
            sample_count += len(segment)
        if not position_residuals or not rotation_residuals:
            rows.append(_insufficient(condition, label, 0))
            continue
        position_residual = np.concatenate(position_residuals)
        rotation_residual = np.concatenate(rotation_residuals)
        rows.append(
            {
                "condition": condition,
                "label": label,
                "n": int(sample_count),
                "position_jitter_rms_m": rms(position_residual),
                "position_jitter_std_m": float(np.std(position_residual)),
                "rotation_jitter_rms_deg": rms(rotation_residual),
                "insufficient_data": False,
            }
        )
    return pd.DataFrame.from_records(rows, columns=SUMMARY_COLUMNS)


def _usable_pose_rows(group: pd.DataFrame) -> pd.DataFrame:
    """筛出有 GT 与 stable pose 的行。"""

    return group[
        group["valid"].fillna(False).astype(bool)
        & group["has_output_pose"].fillna(False).astype(bool)
        & group["gt_pos"].map(is_pose_value)
        & group["output_pos"].map(is_pose_value)
        & group["output_rot"].map(is_pose_value)
    ].copy()


def _static_mask(group: pd.DataFrame, threshold_mps: float) -> np.ndarray:
    """根据 GT 速度估计静止窗口。"""

    pos = np.vstack(group["gt_pos"].to_numpy())
    time_s = group["render_mono_ms"].to_numpy(dtype=float) * 0.001
    if len(group) < 2:
        return np.zeros(len(group), dtype=bool)
    dt = np.diff(time_s)
    dt[dt <= 1e-9] = np.nan
    step_speed = np.linalg.norm(np.diff(pos, axis=0), axis=1) / dt
    # speed[i] 取相邻两帧位移速度；首帧没有前一帧，复用次帧速度，避免被当成静止。
    speed = np.empty(len(group), dtype=float)
    speed[1:] = step_speed
    speed[0] = step_speed[0] if step_speed.size > 0 else np.inf
    speed[~np.isfinite(speed)] = np.inf
    return speed <= threshold_mps


def _continuous_segments(sample: pd.DataFrame) -> list[pd.DataFrame]:
    """按采样时间缺口切分连续段，避免滤波跨越追踪中断。"""

    if sample.empty:
        return []
    work = sample.sort_values("render_mono_ms", kind="stable")
    times = pd.to_numeric(work["render_mono_ms"], errors="coerce").to_numpy(dtype=float)
    intervals = np.diff(times)
    positive = intervals[np.isfinite(intervals) & (intervals > 0.0)]
    maximum_gap_ms = (
        max(100.0, 2.5 * float(np.median(positive))) if len(positive) else 100.0
    )
    boundaries = np.flatnonzero(
        ~np.isfinite(intervals)
        | (intervals <= 0.0)
        | (intervals > maximum_gap_ms)
    )
    starts = np.concatenate(([0], boundaries + 1))
    ends = np.concatenate((boundaries + 1, [len(work)]))
    return [work.iloc[start:end] for start, end in zip(starts, ends) if end - start >= 3]


def _median_dt_seconds(time_ms: np.ndarray) -> float:
    """估计采样间隔。"""

    diffs = np.diff(time_ms) * 0.001
    diffs = diffs[diffs > 0.0]
    if diffs.size == 0:
        return 1.0 / 30.0
    return float(np.median(diffs))


def _rotation_residual_deg(
    quaternions: np.ndarray,
    *,
    dt: float,
    cutoff_hz: float,
) -> np.ndarray:
    """把段内姿态转换为 SO(3) 对数向量并返回高通残差范数。"""

    if len(quaternions) == 0:
        return np.empty(0, dtype=float)
    rotations = Rotation.from_quat(quaternions)
    reference = rotations[0]
    rotation_vectors_deg = np.rad2deg((rotations * reference.inv()).as_rotvec())
    residual = highpass(rotation_vectors_deg, dt=dt, cutoff_hz=cutoff_hz)
    return np.linalg.norm(residual, axis=1)


def _insufficient(condition: str, label: str, count: int) -> dict[str, Any]:
    """构造数据不足行。"""

    return {
        "condition": condition,
        "label": label,
        "n": int(count),
        "position_jitter_rms_m": np.nan,
        "position_jitter_std_m": np.nan,
        "rotation_jitter_rms_deg": np.nan,
        "insufficient_data": True,
    }


def _empty_summary() -> pd.DataFrame:
    """返回空 jitter 汇总表。"""

    return pd.DataFrame(columns=SUMMARY_COLUMNS)


__all__ = ["compute_jitter"]

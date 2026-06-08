"""静止窗口内的 anchor jitter 指标。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .common import angle_deg, highpass, is_pose_value, relative_rotation_quat
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
    """在 GT 低速窗口内计算各变体 anchor 抖动。"""

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
        pos = np.vstack(sample["stable_pos"].to_numpy())
        time_ms = sample["render_mono_ms"].to_numpy(dtype=float)
        dt = _median_dt_seconds(time_ms)
        residual = highpass(pos, dt=dt, cutoff_hz=cutoff_hz)
        residual_norm = np.linalg.norm(residual, axis=1)
        rot_jitter = _rotation_jitter_deg(np.vstack(sample["stable_rot"].to_numpy()))
        rows.append(
            {
                "condition": condition,
                "label": label,
                "n": int(len(sample)),
                "position_jitter_rms_m": rms(residual_norm),
                "position_jitter_std_m": float(np.std(residual_norm)),
                "rotation_jitter_rms_deg": rot_jitter,
                "insufficient_data": False,
            }
        )
    return pd.DataFrame.from_records(rows, columns=SUMMARY_COLUMNS)


def _usable_pose_rows(group: pd.DataFrame) -> pd.DataFrame:
    """筛出有 GT 与 stable pose 的行。"""

    return group[
        group["valid"].fillna(False).astype(bool)
        & group["has_stable"].fillna(False).astype(bool)
        & group["gt_pos"].map(is_pose_value)
        & group["stable_pos"].map(is_pose_value)
        & group["stable_rot"].map(is_pose_value)
    ].copy()


def _static_mask(group: pd.DataFrame, threshold_mps: float) -> np.ndarray:
    """根据 GT 速度估计静止窗口。"""

    pos = np.vstack(group["gt_pos"].to_numpy())
    time_s = group["render_mono_ms"].to_numpy(dtype=float) * 0.001
    if len(group) < 2:
        return np.zeros(len(group), dtype=bool)
    dt = np.diff(time_s)
    dt[dt <= 1e-9] = np.nan
    speed = np.zeros(len(group), dtype=float)
    speed[1:] = np.linalg.norm(np.diff(pos, axis=0), axis=1) / dt
    speed[~np.isfinite(speed)] = np.inf
    if np.all(speed > threshold_mps):
        return np.ones(len(group), dtype=bool)
    return speed <= threshold_mps


def _median_dt_seconds(time_ms: np.ndarray) -> float:
    """估计采样间隔。"""

    diffs = np.diff(time_ms) * 0.001
    diffs = diffs[diffs > 0.0]
    if diffs.size == 0:
        return 1.0 / 30.0
    return float(np.median(diffs))


def _rotation_jitter_deg(quaternions: np.ndarray) -> float:
    """以第一帧为参考估计旋转 RMS 抖动。"""

    if len(quaternions) == 0:
        return np.nan
    reference = quaternions[0]
    values = []
    for quat in quaternions:
        values.append(angle_deg(relative_rotation_quat(reference, quat)))
    arr = np.asarray(values, dtype=float)
    return rms(arr)


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

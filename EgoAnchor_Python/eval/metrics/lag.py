"""GT 与 anchor 运动滞后估计。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .common import is_pose_value, slerp_lerp_resample


SUMMARY_COLUMNS = ["condition", "label", "n", "lag_ms", "correlation", "insufficient_data"]


def compute_lag(output: pd.DataFrame, *, sample_hz: float = 30.0, max_lag_ms: float = 500.0) -> pd.DataFrame:
    """用主运动轴速度互相关估计 anchor 相对 GT 的滞后。"""

    if output.empty:
        return _empty_summary()
    rows: list[dict[str, Any]] = []
    for (condition, label), group in output.groupby(["condition", "label"], sort=True):
        usable = group[
            group["valid"].fillna(False).astype(bool)
            & group["has_stable"].fillna(False).astype(bool)
            & group["gt_pos"].map(is_pose_value)
            & group["gt_rot"].map(is_pose_value)
            & group["stable_pos"].map(is_pose_value)
            & group["stable_rot"].map(is_pose_value)
        ].sort_values("render_mono_ms")
        if len(usable) < 4:
            rows.append(_insufficient(condition, label, len(usable)))
            continue
        result = _estimate_group_lag(usable, sample_hz=sample_hz, max_lag_ms=max_lag_ms)
        rows.append(
            {
                "condition": condition,
                "label": label,
                "n": int(len(usable)),
                "lag_ms": result[0],
                "correlation": result[1],
                "insufficient_data": not np.isfinite(result[0]),
            }
        )
    return pd.DataFrame.from_records(rows, columns=SUMMARY_COLUMNS)


def _estimate_group_lag(group: pd.DataFrame, *, sample_hz: float, max_lag_ms: float) -> tuple[float, float]:
    """估计单个 condition × label 的 lag。"""

    times = group["render_mono_ms"].to_numpy(dtype=float)
    start = float(times[0])
    end = float(times[-1])
    step = 1000.0 / sample_hz
    grid = np.arange(start, end + step * 0.5, step)
    if len(grid) < 4:
        return np.nan, np.nan

    identity_quat = np.tile(np.array([0.0, 0.0, 0.0, 1.0]), (len(group), 1))
    gt_pos, _ = slerp_lerp_resample(times, np.vstack(group["gt_pos"].to_numpy()), identity_quat, grid)
    anchor_pos, _ = slerp_lerp_resample(times, np.vstack(group["stable_pos"].to_numpy()), identity_quat, grid)
    axis = int(np.argmax(np.ptp(gt_pos, axis=0)))
    gt_signal = np.gradient(gt_pos[:, axis])
    anchor_signal = np.gradient(anchor_pos[:, axis])
    gt_signal -= np.mean(gt_signal)
    anchor_signal -= np.mean(anchor_signal)
    gt_std = float(np.std(gt_signal))
    anchor_std = float(np.std(anchor_signal))
    if gt_std <= 1e-9 or anchor_std <= 1e-9:
        return np.nan, np.nan
    gt_signal /= gt_std
    anchor_signal /= anchor_std

    corr = np.correlate(anchor_signal, gt_signal, mode="full")
    lags = np.arange(-len(gt_signal) + 1, len(gt_signal))
    max_lag_samples = int(round(max_lag_ms / step))
    mask = np.abs(lags) <= max_lag_samples
    if not np.any(mask):
        return np.nan, np.nan
    local = corr[mask]
    local_lags = lags[mask]
    index = int(np.argmax(local))
    return float(local_lags[index] * step), float(local[index] / len(gt_signal))


def _insufficient(condition: str, label: str, count: int) -> dict[str, Any]:
    """构造数据不足行。"""

    return {
        "condition": condition,
        "label": label,
        "n": int(count),
        "lag_ms": np.nan,
        "correlation": np.nan,
        "insufficient_data": True,
    }


def _empty_summary() -> pd.DataFrame:
    """返回空 lag 汇总表。"""

    return pd.DataFrame(columns=SUMMARY_COLUMNS)


__all__ = ["compute_lag"]

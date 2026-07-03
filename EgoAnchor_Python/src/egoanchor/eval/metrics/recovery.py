"""遮挡/出视野后的恢复时间指标。"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd


SUMMARY_COLUMNS = [
    "event_type",
    "event_mono_ms",
    "condition",
    "label",
    "recovery_time_ms",
    "threshold_m",
    "insufficient_data",
]


def compute_recovery(
    anchor_error_detail: pd.DataFrame,
    manifest: Mapping[str, Any],
    *,
    threshold_m: float = 0.05,
    hold_ms: float = 200.0,
) -> pd.DataFrame:
    """根据 manifest event marker 估计恢复时间。"""

    markers = manifest.get("event_markers", [])
    if anchor_error_detail.empty or not isinstance(markers, list) or not markers:
        return pd.DataFrame(columns=SUMMARY_COLUMNS)
    rows: list[dict[str, Any]] = []
    for marker in markers:
        if not isinstance(marker, Mapping):
            continue
        event_type = str(marker.get("type", marker.get("label", "event")))
        event_mono_ms = _marker_time(marker)
        if not np.isfinite(event_mono_ms):
            continue
        after = anchor_error_detail[anchor_error_detail["render_mono_ms"] >= event_mono_ms]
        for label, group in after.groupby("label", sort=True):
            recovered = _first_sustained_recovery(group.sort_values("render_mono_ms"), threshold_m, hold_ms)
            rows.append(
                {
                    "event_type": event_type,
                    "event_mono_ms": event_mono_ms,
                    "condition": str(group.iloc[0].get("condition", "unlabeled")) if not group.empty else "unlabeled",
                    "label": label,
                    "recovery_time_ms": recovered - event_mono_ms if np.isfinite(recovered) else np.nan,
                    "threshold_m": float(threshold_m),
                    "insufficient_data": not np.isfinite(recovered),
                }
            )
    return pd.DataFrame.from_records(rows, columns=SUMMARY_COLUMNS)


def _marker_time(marker: Mapping[str, Any]) -> float:
    """兼容 Unity 当前 marker 时间字段。"""

    for key in ("mono_ms", "event_mono_ms", "time_mono_ms"):
        if key in marker:
            try:
                return float(marker[key])
            except (TypeError, ValueError):
                return np.nan
    return np.nan


def _first_sustained_recovery(group: pd.DataFrame, threshold_m: float, hold_ms: float) -> float:
    """查找首个持续低误差窗口。"""

    if group.empty:
        return np.nan
    times = group["render_mono_ms"].to_numpy(dtype=float)
    errors = group["translation_error_m"].to_numpy(dtype=float)
    good = errors <= threshold_m
    for index, ok in enumerate(good):
        if not ok:
            continue
        end_time = times[index] + hold_ms
        stop = int(np.searchsorted(times, end_time, side="right"))
        window = good[index:stop]
        # 要求窗口确实覆盖完整 hold_ms：日志在 hold 窗口结束前截断时不算持续恢复。
        spans_hold = window.size > 0 and times[stop - 1] - times[index] >= hold_ms
        if spans_hold and np.all(window):
            return float(times[index])
    return np.nan


__all__ = ["compute_recovery"]

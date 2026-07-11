"""RQ2 Full 与 Raw-ZOH 的试次级配对比较。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .contract import BOOTSTRAP_SEED, REQUIRED_VARIANTS


PAIRED_METRICS: tuple[str, ...] = (
    "within_tolerance_valid_tracking_rate",
    "tracking_availability",
    "display_translation_median_m",
    "display_translation_p95_m",
    "display_rotation_median_deg",
    "display_rotation_p95_deg",
    "display_update_rate_hz",
    "display_hold_fraction",
    "display_translation_lag_ms",
    "display_rotation_lag_ms",
)
"""正式配对表保留的主终点与响应性指标。"""

PAIRED_COLUMNS = [
    "level",
    "session_id",
    "condition",
    "rq2_trial_id",
    "metric",
    "full_value",
    "raw_zoh_value",
    "delta_full_minus_raw_zoh",
    "n_sessions",
    "n_trials",
    "delta_mean",
    "delta_median",
    "delta_ci_low",
    "delta_ci_high",
]
"""试次级差值与跨试次分层 bootstrap 汇总字段。"""


def compute_paired_summary(
    trial_summary: pd.DataFrame,
    *,
    bootstrap_iterations: int,
) -> pd.DataFrame:
    """计算 ``Full - Raw-ZOH`` 的 trial 配对差值与 condition 级区间。"""

    required = {"session_id", "condition", "rq2_trial_id", "label"}
    if trial_summary.empty or not required.issubset(trial_summary.columns):
        return pd.DataFrame(columns=PAIRED_COLUMNS)
    records: list[dict[str, object]] = []
    index_columns = ["session_id", "condition", "rq2_trial_id"]
    for keys, group in trial_summary.groupby(index_columns, sort=True):
        by_label = group.drop_duplicates("label", keep="first").set_index("label")
        if not set(REQUIRED_VARIANTS).issubset(by_label.index):
            continue
        for metric in PAIRED_METRICS:
            if metric not in by_label.columns:
                continue
            full_value = _finite_float(by_label.at["Full", metric])
            raw_value = _finite_float(by_label.at["Raw-ZOH", metric])
            delta = (
                float(full_value - raw_value)
                if np.isfinite(full_value) and np.isfinite(raw_value)
                else np.nan
            )
            records.append(
                {
                    "level": "trial",
                    "session_id": str(keys[0]),
                    "condition": str(keys[1]),
                    "rq2_trial_id": int(keys[2]),
                    "metric": metric,
                    "full_value": full_value,
                    "raw_zoh_value": raw_value,
                    "delta_full_minus_raw_zoh": delta,
                    "n_sessions": 1,
                    "n_trials": 1,
                    "delta_mean": delta,
                    "delta_median": delta,
                    "delta_ci_low": np.nan,
                    "delta_ci_high": np.nan,
                }
            )
    trial_table = pd.DataFrame.from_records(records, columns=PAIRED_COLUMNS)
    if trial_table.empty:
        return trial_table
    scene_records: list[dict[str, object]] = []
    finite_trials = trial_table[np.isfinite(trial_table["delta_full_minus_raw_zoh"])]
    for (condition, metric), group in finite_trials.groupby(
        ["condition", "metric"], sort=True
    ):
        ci_low, ci_high = _hierarchical_delta_ci(group, bootstrap_iterations)
        delta = group["delta_full_minus_raw_zoh"].to_numpy(dtype=float)
        scene_records.append(
            {
                "level": "condition",
                "session_id": "all",
                "condition": str(condition),
                "rq2_trial_id": -1,
                "metric": str(metric),
                "full_value": float(group["full_value"].mean()),
                "raw_zoh_value": float(group["raw_zoh_value"].mean()),
                "delta_full_minus_raw_zoh": float(np.mean(delta)),
                "n_sessions": int(group["session_id"].nunique()),
                "n_trials": int(len(group)),
                "delta_mean": float(np.mean(delta)),
                "delta_median": float(np.median(delta)),
                "delta_ci_low": ci_low,
                "delta_ci_high": ci_high,
            }
        )
    return pd.concat(
        [trial_table, pd.DataFrame.from_records(scene_records, columns=PAIRED_COLUMNS)],
        ignore_index=True,
    )[PAIRED_COLUMNS]


def _hierarchical_delta_ci(
    trials: pd.DataFrame,
    iterations: int,
) -> tuple[float, float]:
    """以 session 为最高层、trial 为次层重采样配对差值。"""

    sessions = sorted(trials["session_id"].astype(str).unique())
    if len(sessions) < 2 or len(trials) < 3 or iterations <= 0:
        return np.nan, np.nan
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    values: list[float] = []
    for _ in range(iterations):
        sampled_sessions = rng.choice(sessions, size=len(sessions), replace=True)
        sampled_trials: list[float] = []
        for session in sampled_sessions:
            candidates = trials[trials["session_id"].astype(str).eq(str(session))]
            indices = rng.integers(0, len(candidates), size=len(candidates))
            sampled_trials.extend(
                candidates.iloc[indices]["delta_full_minus_raw_zoh"].to_numpy(dtype=float)
            )
        if sampled_trials:
            values.append(float(np.mean(sampled_trials)))
    if not values:
        return np.nan, np.nan
    return float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))


def _finite_float(value: Any) -> float:
    """宽容读取有限浮点数。"""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return np.nan
    return number if np.isfinite(number) else np.nan


__all__ = ["PAIRED_COLUMNS", "PAIRED_METRICS", "compute_paired_summary"]

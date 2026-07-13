"""RQ2 观测年龄与策略目标延迟的紧凑描述统计。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .contract import RQ2_CONDITIONS


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
]


def compute_response_summary(output: pd.DataFrame) -> pd.DataFrame:
    """按运动任务与系统配置汇总观测年龄和策略目标延迟。"""

    if output.empty:
        return pd.DataFrame(columns=RESPONSE_COLUMNS)
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
            }
        )
    return pd.DataFrame.from_records(rows, columns=RESPONSE_COLUMNS)


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

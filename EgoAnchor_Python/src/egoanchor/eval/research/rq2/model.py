"""RQ2 pre-image 运动与 raw 时延残差的关联分析。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .contract import BOOTSTRAP_SEED


MODEL_COLUMNS = [
    "level",
    "session_id",
    "condition",
    "rq2_trial_id",
    "label",
    "channel",
    "unit",
    "n",
    "n_sessions",
    "n_trials",
    "observed_mean",
    "predicted_mean",
    "bias",
    "mae",
    "observed_mean_report",
    "predicted_mean_report",
    "bias_report",
    "mae_report",
    "report_unit",
    "slope",
    "intercept",
    "slope_ci_low",
    "slope_ci_high",
    "intercept_ci_low",
    "intercept_ci_high",
]
"""trial 描述和 condition 级等 trial 权重关联字段。"""


def compute_model_summary(
    motion: pd.DataFrame,
    *,
    bootstrap_iterations: int = 1000,
) -> pd.DataFrame:
    """使用全部 eligible frame 做等 trial 权重拟合和分层 bootstrap。"""

    required = {"condition", "rq2_trial_id", "label"}
    if motion.empty or not required.issubset(motion.columns):
        return pd.DataFrame(columns=MODEL_COLUMNS)
    work = motion.copy()
    if "session_id" not in work:
        work["session_id"] = "session"
    channels = {
        "translation": (
            "raw_translation_lag_error_handle_m",
            "expected_translation_handle_m",
            "translation_model_eligible",
            "m",
            1.0,
            "m",
        ),
        "rotation": (
            "raw_rotation_lag_error_handle_rad",
            "expected_rotation_handle_rad",
            "rotation_model_eligible",
            "rad",
            180.0 / np.pi,
            "deg",
        ),
    }
    trial_records: list[dict[str, object]] = []
    eligible_tables: list[pd.DataFrame] = []
    for channel, fields in channels.items():
        observed_column, predicted_column, eligible_column, unit, scale, report_unit = fields
        if observed_column not in work.columns or predicted_column not in work.columns:
            continue
        channel_work = work[
            [
                "session_id",
                "condition",
                "rq2_trial_id",
                "label",
                observed_column,
                predicted_column,
                *([eligible_column] if eligible_column in work.columns else []),
            ]
        ].copy()
        channel_work["observed"] = pd.to_numeric(
            channel_work[observed_column], errors="coerce"
        )
        channel_work["predicted"] = pd.to_numeric(
            channel_work[predicted_column], errors="coerce"
        )
        if eligible_column in channel_work:
            eligible = channel_work[eligible_column].fillna(False).astype(bool)
        else:
            eligible = pd.Series(True, index=channel_work.index)
        channel_work = channel_work[
            eligible
            & np.isfinite(channel_work["observed"])
            & np.isfinite(channel_work["predicted"])
        ].copy()
        if channel_work.empty:
            continue
        channel_work["channel"] = channel
        eligible_tables.append(channel_work)
        for keys, group in channel_work.groupby(
            ["session_id", "condition", "rq2_trial_id", "label"], sort=True
        ):
            residual = group["observed"].to_numpy(dtype=float) - group[
                "predicted"
            ].to_numpy(dtype=float)
            trial_records.append(
                _summary_record(
                    level="trial",
                    session_id=str(keys[0]),
                    condition=str(keys[1]),
                    trial_id=int(keys[2]),
                    label=str(keys[3]),
                    channel=channel,
                    unit=unit,
                    report_unit=report_unit,
                    scale=scale,
                    observed=group["observed"].to_numpy(dtype=float),
                    predicted=group["predicted"].to_numpy(dtype=float),
                    residual=residual,
                    n_sessions=1,
                    n_trials=1,
                )
            )
    if not eligible_tables:
        return pd.DataFrame(columns=MODEL_COLUMNS)
    trial_table = pd.DataFrame.from_records(trial_records, columns=MODEL_COLUMNS)
    all_eligible = pd.concat(eligible_tables, ignore_index=True)
    scene_records: list[dict[str, object]] = []
    for (condition, label, channel), group in all_eligible.groupby(
        ["condition", "label", "channel"], sort=True
    ):
        unit = "rad" if channel == "rotation" else "m"
        report_unit = "deg" if channel == "rotation" else "m"
        scale = 180.0 / np.pi if channel == "rotation" else 1.0
        weights = _equal_trial_weights(group)
        slope, intercept = _weighted_fit(
            group["predicted"].to_numpy(dtype=float),
            group["observed"].to_numpy(dtype=float),
            weights,
        )
        ci = _hierarchical_regression_ci(group, bootstrap_iterations)
        residual = group["observed"].to_numpy(dtype=float) - group[
            "predicted"
        ].to_numpy(dtype=float)
        record = _summary_record(
            level="condition",
            session_id="all",
            condition=str(condition),
            trial_id=-1,
            label=str(label),
            channel=str(channel),
            unit=unit,
            report_unit=report_unit,
            scale=scale,
            observed=group["observed"].to_numpy(dtype=float),
            predicted=group["predicted"].to_numpy(dtype=float),
            residual=residual,
            n_sessions=int(group["session_id"].nunique()),
            n_trials=int(
                group[["session_id", "rq2_trial_id"]].drop_duplicates().shape[0]
            ),
        )
        weighted_observed = float(
            np.average(group["observed"].to_numpy(dtype=float), weights=weights)
        )
        weighted_predicted = float(
            np.average(group["predicted"].to_numpy(dtype=float), weights=weights)
        )
        weighted_bias = float(np.average(residual, weights=weights))
        weighted_mae = float(np.average(np.abs(residual), weights=weights))
        record.update(
            {
                "observed_mean": weighted_observed,
                "predicted_mean": weighted_predicted,
                "bias": weighted_bias,
                "mae": weighted_mae,
                "observed_mean_report": weighted_observed * scale,
                "predicted_mean_report": weighted_predicted * scale,
                "bias_report": weighted_bias * scale,
                "mae_report": weighted_mae * scale,
                "slope": slope,
                "intercept": intercept,
                "slope_ci_low": ci[0],
                "slope_ci_high": ci[1],
                "intercept_ci_low": ci[2],
                "intercept_ci_high": ci[3],
            }
        )
        scene_records.append(record)
    return pd.concat(
        [trial_table, pd.DataFrame.from_records(scene_records, columns=MODEL_COLUMNS)],
        ignore_index=True,
    )[MODEL_COLUMNS]


def _summary_record(
    *,
    level: str,
    session_id: str,
    condition: str,
    trial_id: int,
    label: str,
    channel: str,
    unit: str,
    report_unit: str,
    scale: float,
    observed: np.ndarray,
    predicted: np.ndarray,
    residual: np.ndarray,
    n_sessions: int,
    n_trials: int,
) -> dict[str, object]:
    """构造 trial 或 condition 级关联汇总记录。"""

    return {
        "level": level,
        "session_id": session_id,
        "condition": condition,
        "rq2_trial_id": trial_id,
        "label": label,
        "channel": channel,
        "unit": unit,
        "n": int(len(observed)),
        "n_sessions": n_sessions,
        "n_trials": n_trials,
        "observed_mean": float(np.mean(observed)),
        "predicted_mean": float(np.mean(predicted)),
        "bias": float(np.mean(residual)),
        "mae": float(np.mean(np.abs(residual))),
        "observed_mean_report": float(np.mean(observed) * scale),
        "predicted_mean_report": float(np.mean(predicted) * scale),
        "bias_report": float(np.mean(residual) * scale),
        "mae_report": float(np.mean(np.abs(residual)) * scale),
        "report_unit": report_unit,
        "slope": np.nan,
        "intercept": np.nan,
        "slope_ci_low": np.nan,
        "slope_ci_high": np.nan,
        "intercept_ci_low": np.nan,
        "intercept_ci_high": np.nan,
    }


def _equal_trial_weights(group: pd.DataFrame) -> np.ndarray:
    """让每个 session × trial 对回归具有相同总权重。"""

    keys = list(zip(group["session_id"].astype(str), group["rq2_trial_id"].astype(int)))
    counts = pd.Series(keys).value_counts().to_dict()
    return np.asarray([1.0 / counts[key] for key in keys], dtype=float)


def _weighted_fit(
    predicted: np.ndarray,
    observed: np.ndarray,
    weights: np.ndarray,
) -> tuple[float, float]:
    """拟合 ``observed = slope * predicted + intercept``。"""

    if len(predicted) < 2 or float(np.ptp(predicted)) <= 1e-12:
        return np.nan, np.nan
    design = np.column_stack((predicted, np.ones(len(predicted))))
    root_weight = np.sqrt(weights)
    coefficients, *_ = np.linalg.lstsq(
        design * root_weight[:, None], observed * root_weight, rcond=None
    )
    return float(coefficients[0]), float(coefficients[1])


def _hierarchical_regression_ci(
    group: pd.DataFrame,
    iterations: int,
) -> tuple[float, float, float, float]:
    """以 session 为最高层、trial 为次层重采样关联回归。"""

    sessions = sorted(group["session_id"].astype(str).unique())
    if len(sessions) < 2 or iterations <= 0:
        return np.nan, np.nan, np.nan, np.nan
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    slopes: list[float] = []
    intercepts: list[float] = []
    for _ in range(iterations):
        sampled_groups: list[pd.DataFrame] = []
        sampled_sessions = rng.choice(sessions, size=len(sessions), replace=True)
        for session_index, session in enumerate(sampled_sessions):
            session_rows = group[group["session_id"].astype(str).eq(str(session))]
            trial_ids = session_rows["rq2_trial_id"].astype(int).unique()
            sampled_trials = rng.choice(trial_ids, size=len(trial_ids), replace=True)
            for trial_index, trial_id in enumerate(sampled_trials):
                trial_rows = session_rows[session_rows["rq2_trial_id"].astype(int).eq(trial_id)].copy()
                trial_rows["_bootstrap_session"] = session_index
                trial_rows["_bootstrap_trial"] = trial_index
                sampled_groups.append(trial_rows)
        if not sampled_groups:
            continue
        sample = pd.concat(sampled_groups, ignore_index=True)
        keys = list(zip(sample["_bootstrap_session"], sample["_bootstrap_trial"]))
        counts = pd.Series(keys).value_counts().to_dict()
        weights = np.asarray([1.0 / counts[key] for key in keys], dtype=float)
        slope, intercept = _weighted_fit(
            sample["predicted"].to_numpy(dtype=float),
            sample["observed"].to_numpy(dtype=float),
            weights,
        )
        if np.isfinite(slope) and np.isfinite(intercept):
            slopes.append(slope)
            intercepts.append(intercept)
    if not slopes:
        return np.nan, np.nan, np.nan, np.nan
    return (
        float(np.percentile(slopes, 2.5)),
        float(np.percentile(slopes, 97.5)),
        float(np.percentile(intercepts, 2.5)),
        float(np.percentile(intercepts, 97.5)),
    )


__all__ = ["MODEL_COLUMNS", "compute_model_summary"]

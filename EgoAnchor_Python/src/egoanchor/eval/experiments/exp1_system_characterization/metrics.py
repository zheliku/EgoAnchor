"""把 Task 9 中性指标整理为实验一的稳定分析表。"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, cast

import numpy as np
import pandas as pd

from egoanchor.eval.metrics import METRIC_GROUP_COLUMNS, compute_all_metrics, require_columns
from egoanchor.eval.schema_v2 import EvalSessionV2, select_trials

from .contract import EXPERIMENT_ID, SCENARIOS, VARIANTS


PAIR_COLUMNS = tuple(
    column
    for column in METRIC_GROUP_COLUMNS
    if column not in {"variant_id", "variant_label"}
)
"""同一 trial/event 内跨配置配对使用的上下文键。"""

TRIAL_VALUE_COLUMNS = (
    "reference_coverage",
    "display_coverage",
    "output_coverage",
    "translation_error_mm_median",
    "translation_error_mm_iqr",
    "translation_error_mm_p95",
    "rotation_error_deg_median",
    "rotation_error_deg_iqr",
    "rotation_error_deg_p95",
    "candidate_arrival_p50_ms",
    "candidate_arrival_p95_ms",
    "candidate_processing_p50_ms",
    "candidate_processing_p95_ms",
    "observation_age_p50_ms",
    "observation_age_p95_ms",
    "smoothing_delay_p50_ms",
    "smoothing_delay_p95_ms",
    "visual_perception_hz",
    "render_hz",
)
"""参与 trial 配对和条件汇总的连续系统指标。"""


def compute_exp1_tables(session: EvalSessionV2) -> dict[str, pd.DataFrame]:
    """复用中性指标，构造一个已通过 QC 的实验一 session 表。"""

    selected = _select_exp1_variants(select_trials(session, EXPERIMENT_ID))
    neutral = compute_all_metrics(selected).tables
    trials = build_trial_metrics(selected.unity_render, neutral)
    return {
        "exp1_trial_metrics": trials,
        "exp1_paired_trial_metrics": build_paired_trial_metrics(trials),
        "exp1_condition_summary": build_condition_summary(trials),
        "exp1_static_quality": _scenario_rows(
            neutral["static_metrics"], {"static_head_motion"}
        ),
        "exp1_transition_response": _scenario_rows(
            neutral["transition_metrics"], {"start_stop_6dof"}
        ),
        "exp1_occlusion_recovery": _scenario_rows(
            neutral["occlusion_recovery_metrics"], {"occlusion_recovery"}
        ),
        "exp1_latency_summary": _scenario_rows(neutral["latency_summary"], set(SCENARIOS)),
        "exp1_vcd_diagnostics": _scenario_rows(
            neutral["reliability_summary"], set(SCENARIOS)
        ),
    }


def build_trial_metrics(
    render: pd.DataFrame,
    neutral_tables: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """合并显示误差、可用率和时延，形成每个 trial/event×variant 一行。"""

    coverage = _coverage_metrics(render)
    display_error = neutral_tables["display_error_summary"]
    latency = neutral_tables["latency_summary"]
    result = _merge_metric_table(coverage, display_error)
    result = _merge_metric_table(result, latency)
    for column in TRIAL_VALUE_COLUMNS:
        if column not in result.columns:
            result[column] = np.nan
    return result[[*METRIC_GROUP_COLUMNS, "render_tick_count", *TRIAL_VALUE_COLUMNS]].copy()


def build_paired_trial_metrics(trials: pd.DataFrame) -> pd.DataFrame:
    """以 Arrival-Hold 为基线输出逐 trial 的三组配置配对差。"""

    columns = [
        *PAIR_COLUMNS,
        "baseline_variant",
        "variant_id",
        "variant_label",
        "metric_name",
        "metric_value_baseline",
        "metric_value_variant",
        "delta_variant_minus_baseline",
        "paired_n",
    ]
    if trials.empty:
        return pd.DataFrame(columns=columns)
    require_columns(trials, (*METRIC_GROUP_COLUMNS, *TRIAL_VALUE_COLUMNS), table_name="exp1_trial_metrics")
    rows: list[dict[str, Any]] = []
    for values, group in trials.groupby(list(PAIR_COLUMNS), dropna=False, sort=True):
        context = dict(zip(PAIR_COLUMNS, values, strict=True))
        baseline_rows = group.loc[group["variant_label"].astype(str).eq(VARIANTS[0])]
        if len(baseline_rows) != 1:
            raise ValueError(f"实验一配对要求每组恰有一个 {VARIANTS[0]}：{context}")
        baseline = baseline_rows.iloc[0]
        for variant in VARIANTS[1:]:
            variant_rows = group.loc[group["variant_label"].astype(str).eq(variant)]
            if len(variant_rows) != 1:
                raise ValueError(f"实验一配对要求每组恰有一个 {variant}：{context}")
            compared = variant_rows.iloc[0]
            for metric_name in TRIAL_VALUE_COLUMNS:
                baseline_value = _number(baseline[metric_name])
                variant_value = _number(compared[metric_name])
                rows.append(
                    {
                        **context,
                        "baseline_variant": VARIANTS[0],
                        "variant_id": str(compared["variant_id"]),
                        "variant_label": variant,
                        "metric_name": metric_name,
                        "metric_value_baseline": baseline_value,
                        "metric_value_variant": variant_value,
                        "delta_variant_minus_baseline": (
                            variant_value - baseline_value
                            if np.isfinite(variant_value) and np.isfinite(baseline_value)
                            else np.nan
                        ),
                        "paired_n": int(np.isfinite(variant_value) and np.isfinite(baseline_value)),
                    }
                )
    return pd.DataFrame.from_records(rows, columns=columns)


def build_condition_summary(trials: pd.DataFrame) -> pd.DataFrame:
    """按场景和固定配置汇总 trial 分布，不把 render 帧当独立样本。"""

    context_columns = ["experiment_id", "scenario_id", "condition_id"]
    columns = [
        *context_columns,
        "variant_label",
        "metric_name",
        "trial_count",
        "median",
        "iqr",
        "p95",
    ]
    if trials.empty:
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, Any]] = []
    for context_values, context_group in trials.groupby(
        context_columns, dropna=False, sort=True
    ):
        context = dict(zip(context_columns, context_values, strict=True))
        for variant in VARIANTS:
            group = context_group.loc[
                context_group["variant_label"].astype(str).eq(variant)
            ]
            for metric_name in TRIAL_VALUE_COLUMNS:
                values = pd.to_numeric(group[metric_name], errors="coerce")
                finite = values[np.isfinite(values)]
                rows.append(
                    {
                        **context,
                        "variant_label": variant,
                        "metric_name": metric_name,
                        "trial_count": int(len(finite)),
                        "median": _quantile(finite, 0.50),
                        "iqr": _quantile(finite, 0.75) - _quantile(finite, 0.25),
                        "p95": _quantile(finite, 0.95),
                    }
                )
    return pd.DataFrame.from_records(rows, columns=columns)


def concat_exp1_tables(
    tables_by_session: list[dict[str, pd.DataFrame]],
) -> dict[str, pd.DataFrame]:
    """按固定表名合并多个 session，保留空表的字段契约。"""

    if not tables_by_session:
        return {}
    names = tuple(tables_by_session[0])
    return {
        name: pd.concat([tables[name] for tables in tables_by_session], ignore_index=True)
        for name in names
    }


def _coverage_metrics(render: pd.DataFrame) -> pd.DataFrame:
    """按完整上下文统计 reference、display 和 runtime output 覆盖率。"""

    require_columns(
        render,
        (
            *METRIC_GROUP_COLUMNS,
            "render_tick_id",
            "reference_pose_valid",
            "has_display_pose",
            "has_output_pose",
        ),
        table_name="unity_render",
    )
    rows: list[dict[str, Any]] = []
    for values, group in render.groupby(list(METRIC_GROUP_COLUMNS), dropna=False, sort=True):
        context = dict(zip(METRIC_GROUP_COLUMNS, values, strict=True))
        rows.append(
            {
                **context,
                "render_tick_count": int(group["render_tick_id"].nunique()),
                "reference_coverage": float(
                    group["reference_pose_valid"].fillna(False).astype(bool).mean()
                ),
                "display_coverage": float(
                    group["has_display_pose"].fillna(False).astype(bool).mean()
                ),
                "output_coverage": float(
                    group["has_output_pose"].fillna(False).astype(bool).mean()
                ),
            }
        )
    return pd.DataFrame.from_records(rows)


def _select_exp1_variants(session: EvalSessionV2) -> EvalSessionV2:
    """从已按实验筛选的 session 投影四配置及其关联稳定键。"""

    admission = _variant_rows(session.unity_admission)
    render = _variant_rows(session.unity_render)
    candidate_ids = set(admission["candidate_id"].dropna().astype(str))
    frame_ids = set(pd.to_numeric(admission["frame_id"], errors="coerce").dropna().astype(int))
    source_frames = pd.to_numeric(render["source_frame_id"], errors="coerce").dropna().astype(int)
    frame_ids.update(int(frame_id) for frame_id in source_frames if frame_id >= 0)

    candidates = session.python_candidates.loc[
        session.python_candidates["candidate_id"].astype(str).isin(candidate_ids)
    ].copy()
    reference = session.unity_reference.loc[
        pd.to_numeric(session.unity_reference["frame_id"], errors="coerce").isin(frame_ids)
    ].copy()
    events = _variant_events(session.events, set(render["variant_id"].dropna().astype(str)))
    return replace(
        session,
        python_candidates=candidates,
        unity_reference=reference,
        unity_admission=admission,
        unity_render=render,
        events=events,
    )


def _variant_rows(table: pd.DataFrame) -> pd.DataFrame:
    """只保留冻结的实验一配置；其他 runtime 仍由基础 QC 负责验证。"""

    require_columns(table, ("variant_label",), table_name="experiment-one table")
    return table.loc[table["variant_label"].astype(str).isin(VARIANTS)].copy()


def _variant_events(events: pd.DataFrame, variant_ids: set[str]) -> pd.DataFrame:
    """保留共享事件和四配置事件，排除仅属于消融 runtime 的事件。"""

    if events.empty or "variant_id" not in events.columns:
        return events.copy()
    event_variants = events["variant_id"].fillna("").astype(str)
    return events.loc[event_variants.eq("") | event_variants.isin(variant_ids)].copy()


def _merge_metric_table(left: pd.DataFrame, right: pd.DataFrame) -> pd.DataFrame:
    """按完整中性指标键左连接，并核对两表同名统计字段。"""

    if right.empty:
        return left.copy()
    duplicate_columns = sorted(
        (set(left.columns) & set(right.columns)) - set(METRIC_GROUP_COLUMNS)
    )
    merged = left.merge(
        right,
        on=list(METRIC_GROUP_COLUMNS),
        how="left",
        validate="one_to_one",
        suffixes=("", "_right"),
    )
    for column in duplicate_columns:
        right_column = f"{column}_right"
        equal = merged[column].eq(merged[right_column]) | (
            merged[column].isna() & merged[right_column].isna()
        )
        if not bool(equal.all()):
            raise ValueError(f"指标表同名字段 {column!r} 的值不一致。")
    return merged.drop(
        columns=[f"{column}_right" for column in duplicate_columns]
    )


def _scenario_rows(table: pd.DataFrame, scenarios: set[str]) -> pd.DataFrame:
    """只保留实验一契约中的目标场景，并返回独立副本。"""

    if table.empty or "scenario_id" not in table.columns:
        return table.copy()
    return table.loc[table["scenario_id"].astype(str).isin(scenarios)].copy()


def _number(value: object) -> float:
    """把指标值规范为有限浮点数，缺失值保持 NaN。"""

    try:
        number = float(cast(Any, value))
    except (TypeError, ValueError):
        return np.nan
    return number if np.isfinite(number) else np.nan


def _quantile(values: pd.Series, quantile: float) -> float:
    """对有限 trial 值计算分位数，空组返回 NaN。"""

    return float(values.quantile(quantile)) if len(values) else np.nan


__all__ = [
    "PAIR_COLUMNS",
    "TRIAL_VALUE_COLUMNS",
    "build_condition_summary",
    "build_paired_trial_metrics",
    "build_trial_metrics",
    "compute_exp1_tables",
    "concat_exp1_tables",
]

"""实验二基于 Task 9 中性指标的 trial/event 级配对归因。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandas as pd

from egoanchor.eval.metrics import compute_all_metrics
from egoanchor.eval.schema_v2 import EvalSessionV2

from .contract import BASELINE_VARIANT, EXPERIMENT_ID, SCENARIO_ABLATION


PAIR_KEYS = ("session_id", "scenario_id", "trial_id", "event_id")
"""完整系统与消融进行 trial/event 配对的最低稳定键。"""

_NEUTRAL_TABLES = {
    "display_error": (
        "display_error_summary",
        (
            "translation_error_mm_median",
            "translation_error_mm_iqr",
            "translation_error_mm_p95",
            "rotation_error_deg_median",
            "rotation_error_deg_iqr",
            "rotation_error_deg_p95",
        ),
    ),
    "static": (
        "static_metrics",
        (
            "position_hp_rms_mm",
            "rotation_hp_rms_deg",
            "translation_error_mm_median",
            "translation_error_mm_p95",
            "rotation_error_deg_median",
            "rotation_error_deg_p95",
            "position_drift_mm",
            "rotation_drift_deg",
        ),
    ),
    "transition": (
        "transition_metrics",
        (
            "visible_response_time_ms",
            "unlock_success",
            "unlock_time_ms",
            "relock_success",
            "relock_time_ms",
            "peak_translation_error_mm",
            "peak_rotation_error_deg",
            "settling_time_ms",
        ),
    ),
    "occlusion": (
        "occlusion_recovery_metrics",
        (
            "output_availability",
            "display_availability",
            "display_jump_p95_mm",
            "display_rotation_jump_p95_deg",
            "recovery_success",
            "recovery_time_ms",
        ),
    ),
    "latency": (
        "latency_summary",
        (
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
        ),
    ),
}
"""允许进入实验二配对的 Task 9 中性表和结果指标白名单。"""

def compute_exp2_paired_deltas(session: EvalSessionV2) -> pd.DataFrame:
    """计算一个 session 中四个场景各自唯一消融的配对差值。

    本函数先调用 Task 9 中性指标管线，再在 trial/event 汇总行上配对。原始
    render frame 不进入 merge，因此不会把同一 trial 内的帧当成独立样本。
    """

    neutral = compute_all_metrics(session)
    chunks: list[pd.DataFrame] = []
    for prefix, (table_name, allowed_metrics) in _NEUTRAL_TABLES.items():
        table = neutral.tables[table_name]
        if table.empty:
            continue
        for scenario_id, ablation_label in SCENARIO_ABLATION.items():
            scenario = _select_scenario(table, scenario_id)
            if scenario.empty:
                continue
            metric_columns = [
                metric
                for metric in allowed_metrics
                if metric in scenario.columns
                and (
                    pd.api.types.is_numeric_dtype(scenario[metric])
                    or pd.api.types.is_bool_dtype(scenario[metric])
                )
            ]
            if not metric_columns:
                continue
            full = scenario.loc[scenario["variant_label"].eq(BASELINE_VARIANT)]
            ablation = scenario.loc[scenario["variant_label"].eq(ablation_label)]
            paired = compute_paired_deltas(
                full,
                ablation,
                metric_columns=metric_columns,
                ablation_label=ablation_label,
            )
            if not paired.empty:
                paired["metric"] = prefix + "." + paired["metric"].astype(str)
                chunks.append(paired)
    return pd.concat(chunks, ignore_index=True) if chunks else _empty_delta_table()


def compute_paired_deltas(
    full: pd.DataFrame,
    ablation: pd.DataFrame,
    *,
    metric_columns: Sequence[str],
    ablation_label: str,
    pair_keys: Sequence[str] = PAIR_KEYS,
) -> pd.DataFrame:
    """严格按 session/scenario/trial/event 配对两张汇总表。

    四个键缺一不可；任一侧存在重复键都会造成多对多伪配对，因此直接拒绝。
    每个详细配对行的 ``paired_n`` 固定为 1，组级样本数由汇总函数计数。
    """

    keys = list(pair_keys)
    _require_columns(full, [*keys, *metric_columns], "完整 EgoAnchor 指标")
    _require_columns(ablation, [*keys, *metric_columns], "消融指标")
    _require_unique_pairs(full, keys, "完整 EgoAnchor 指标")
    _require_unique_pairs(ablation, keys, "消融指标")

    rows: list[dict[str, Any]] = []
    for metric in metric_columns:
        left = full[keys].copy()
        right = ablation[keys].copy()
        left["metric_value_full"] = pd.to_numeric(full[metric], errors="coerce")
        right["metric_value_ablation"] = pd.to_numeric(ablation[metric], errors="coerce")
        left = left.dropna(subset=["metric_value_full"])
        right = right.dropna(subset=["metric_value_ablation"])
        merged = left.merge(right, on=keys, how="inner", validate="one_to_one")
        for record in merged.to_dict(orient="records"):
            full_value = float(record.pop("metric_value_full"))
            ablation_value = float(record.pop("metric_value_ablation"))
            rows.append(
                {
                    **record,
                    "metric": metric,
                    "variant_label": ablation_label,
                    "metric_value_full": full_value,
                    "metric_value_ablation": ablation_value,
                    "delta_ablation_minus_full": ablation_value - full_value,
                    "paired_n": 1,
                }
            )
    return pd.DataFrame.from_records(rows, columns=_delta_columns(keys))


def aggregate_component_deltas(deltas: pd.DataFrame) -> pd.DataFrame:
    """按对应场景、消融和中性 metric 汇总配对差值。"""

    columns = [
        "scenario_id",
        "variant_label",
        "metric",
        "paired_n",
        "delta_mean",
        "delta_median",
    ]
    if deltas.empty:
        return pd.DataFrame(columns=columns)
    required = {"scenario_id", "variant_label", "metric", "delta_ablation_minus_full"}
    _require_columns(deltas, required, "实验二 paired delta")
    summary = (
        deltas.groupby(["scenario_id", "variant_label", "metric"], dropna=False)[
            "delta_ablation_minus_full"
        ]
        .agg(paired_n="count", delta_mean="mean", delta_median="median")
        .reset_index()
    )
    return summary.loc[:, columns]


def _select_scenario(table: pd.DataFrame, scenario_id: str) -> pd.DataFrame:
    """从中性表投影实验二指定场景和允许的两个配置。"""

    _require_columns(
        table,
        [*PAIR_KEYS, "experiment_id", "variant_label"],
        "Task 9 中性指标",
    )
    allowed = {BASELINE_VARIANT, SCENARIO_ABLATION[scenario_id]}
    mask = (
        table["experiment_id"].astype(str).eq(EXPERIMENT_ID)
        & table["scenario_id"].astype(str).eq(scenario_id)
        & table["variant_label"].astype(str).isin(allowed)
    )
    return table.loc[mask].copy()


def _require_columns(frame: pd.DataFrame, columns: Sequence[str] | set[str], name: str) -> None:
    """严格要求配对输入具备全部字段。"""

    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ValueError(f"{name} 缺少必需列：{missing}")


def _require_unique_pairs(frame: pd.DataFrame, keys: list[str], name: str) -> None:
    """拒绝同一 trial/event 出现多个汇总行。"""

    if frame.duplicated(keys, keep=False).any():
        duplicates = frame.loc[frame.duplicated(keys, keep=False), keys].drop_duplicates()
        raise ValueError(f"{name} 的配对键不唯一：{duplicates.to_dict(orient='records')}")


def _delta_columns(keys: Sequence[str] = PAIR_KEYS) -> list[str]:
    """返回 detailed paired delta 的稳定列顺序。"""

    return [
        *keys,
        "metric",
        "variant_label",
        "metric_value_full",
        "metric_value_ablation",
        "delta_ablation_minus_full",
        "paired_n",
    ]


def _empty_delta_table() -> pd.DataFrame:
    """返回带稳定 schema 的空配对表。"""

    return pd.DataFrame(columns=_delta_columns())


__all__ = [
    "PAIR_KEYS",
    "aggregate_component_deltas",
    "compute_exp2_paired_deltas",
    "compute_paired_deltas",
]

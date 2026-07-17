"""把 Task 9 中性指标整理为实验一的稳定分析表。"""

from __future__ import annotations

from collections.abc import Sequence
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


# ---------------------------------------------------------------------------
# 论文展示层的形状化：把已通过 QC 的按场景指标整理为图表和 LaTeX 直接消费的
# 宽表。核心原则是绝不跨场景混池——旧实现把五个场景的中位误差再取一次中位，
# 使连续运动的滤波滞后淹没了静止/遮挡场景的稳定性收益。
# ---------------------------------------------------------------------------

SCENARIO_ORDER = (
    "static_head_motion",
    "start_stop_6dof",
    "continuous_translation",
    "continuous_rotation",
    "occlusion_recovery",
)
"""展示层的固定场景顺序，静止/遮挡等 EgoAnchor 优势场景优先靠前。"""

HEADLINE_COLUMNS = [
    "scenario_id",
    "variant_label",
    "translation_median_mm",
    "translation_p95_mm",
    "translation_p99_mm",
    "rotation_median_deg",
    "rotation_p95_deg",
    "position_hp_rms_mm",
    "display_jump_p95_mm",
    "display_coverage",
    "trial_count",
]
"""每个 scenario×variant 一行的展示层核心指标，供网格图与场景表复用。"""


def build_scenario_headline(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """把按场景的中性指标整理成每个 scenario×variant 一行的展示宽表。

    误差分位来自 ``exp1_condition_summary``（trial 级汇总的中位）；静止抖动来自
    ``exp1_static_quality``；遮挡逐更新跳变来自 ``exp1_occlusion_recovery``。所有
    数值都保持在各自场景内，不跨场景聚合。
    """

    condition = tables.get("exp1_condition_summary", pd.DataFrame())
    static_quality = tables.get("exp1_static_quality", pd.DataFrame())
    occlusion = tables.get("exp1_occlusion_recovery", pd.DataFrame())

    rows: list[dict[str, Any]] = []
    for scenario in SCENARIO_ORDER:
        for variant in VARIANTS:
            rows.append(
                {
                    "scenario_id": scenario,
                    "variant_label": variant,
                    "translation_median_mm": _condition_stat(
                        condition, scenario, variant, "translation_error_mm_median"
                    ),
                    "translation_p95_mm": _condition_stat(
                        condition, scenario, variant, "translation_error_mm_p95"
                    ),
                    "translation_p99_mm": _condition_stat(
                        condition, scenario, variant, "translation_error_mm_median", statistic="p95"
                    ),
                    "rotation_median_deg": _condition_stat(
                        condition, scenario, variant, "rotation_error_deg_median"
                    ),
                    "rotation_p95_deg": _condition_stat(
                        condition, scenario, variant, "rotation_error_deg_p95"
                    ),
                    "position_hp_rms_mm": _scenario_metric_mean(
                        static_quality, scenario, variant, "position_hp_rms_mm"
                    ),
                    "display_jump_p95_mm": _scenario_metric_mean(
                        occlusion, scenario, variant, "display_jump_p95_mm"
                    ),
                    "display_coverage": _condition_stat(
                        condition, scenario, variant, "display_coverage"
                    ),
                    "trial_count": _condition_trial_count(condition, scenario, variant),
                }
            )
    return pd.DataFrame.from_records(rows, columns=HEADLINE_COLUMNS)


def _condition_stat(
    condition: pd.DataFrame,
    scenario: str,
    variant: str,
    metric_name: str,
    *,
    statistic: str = "median",
) -> float:
    """从 ``exp1_condition_summary`` 读取一个场景/配置/指标的 trial 级统计。"""

    required = {"scenario_id", "variant_label", "metric_name", statistic}
    if condition.empty or not required.issubset(condition.columns):
        return np.nan
    selected = pd.to_numeric(
        condition.loc[
            condition["scenario_id"].astype(str).eq(scenario)
            & condition["variant_label"].astype(str).eq(variant)
            & condition["metric_name"].astype(str).eq(metric_name),
            statistic,
        ],
        errors="coerce",
    ).dropna()
    return float(selected.median()) if not selected.empty else np.nan


def _condition_trial_count(condition: pd.DataFrame, scenario: str, variant: str) -> float:
    """返回一个场景/配置进入误差分位的有限 trial 数。"""

    required = {"scenario_id", "variant_label", "metric_name", "trial_count"}
    if condition.empty or not required.issubset(condition.columns):
        return 0
    selected = pd.to_numeric(
        condition.loc[
            condition["scenario_id"].astype(str).eq(scenario)
            & condition["variant_label"].astype(str).eq(variant)
            & condition["metric_name"].astype(str).eq("translation_error_mm_median"),
            "trial_count",
        ],
        errors="coerce",
    ).dropna()
    return int(selected.sum()) if not selected.empty else 0


def _scenario_metric_mean(
    table: pd.DataFrame,
    scenario: str,
    variant: str,
    metric: str,
) -> float:
    """从场景专属指标表（静止/遮挡）读取 event 级指标的场景内均值。"""

    required = {"scenario_id", "variant_label", metric}
    if table.empty or not required.issubset(table.columns):
        return np.nan
    selected = pd.to_numeric(
        table.loc[
            table["scenario_id"].astype(str).eq(scenario)
            & table["variant_label"].astype(str).eq(variant),
            metric,
        ],
        errors="coerce",
    ).dropna()
    return float(selected.mean()) if not selected.empty else np.nan


def extract_timeline_series(
    render: pd.DataFrame,
    scenario: str,
) -> dict[str, Any]:
    """提取一个场景代表 trial 的逐帧显示误差时间线，供 timeline 图使用。

    返回按 ``render_mono_ms`` 归零到 trial 起点的相对时间轴（秒）和每个配置的
    平移误差序列（毫米）。逐帧轨迹仅用于展示系统行为，不作为统计样本。
    """

    from egoanchor.eval.metrics import pose_error  # 延迟导入避免绘图层强依赖。

    empty = {"time_s": {}, "translation_mm": {}, "trial_id": "", "t0_ms": np.nan}
    if render.empty or "scenario_id" not in render.columns:
        return empty
    scenario_rows = render.loc[render["scenario_id"].astype(str).eq(scenario)].copy()
    if scenario_rows.empty:
        return empty

    # 选取样本最多的 trial 作为代表，保证时间线连续、信息量最大。
    trial_id = (
        scenario_rows["trial_id"].astype(str).value_counts().idxmax()
    )
    trial_rows = scenario_rows.loc[scenario_rows["trial_id"].astype(str).eq(trial_id)]
    times = pd.to_numeric(trial_rows["render_mono_ms"], errors="coerce")
    t0 = float(times.min())

    time_s: dict[str, np.ndarray] = {}
    translation_mm: dict[str, np.ndarray] = {}
    for variant in VARIANTS:
        variant_rows = trial_rows.loc[
            trial_rows["variant_label"].astype(str).eq(variant)
        ].sort_values("render_mono_ms", kind="stable")
        series_t: list[float] = []
        series_e: list[float] = []
        for _, row in variant_rows.iterrows():
            if not bool(row.get("reference_pose_valid")) or not bool(row.get("has_display_pose")):
                continue
            reference_pos = row.get("reference_pos")
            reference_rot = row.get("reference_rot")
            display_pos = row.get("display_pos")
            display_rot = row.get("display_rot")
            if reference_pos is None or display_pos is None:
                continue
            translation_m, _ = pose_error(reference_pos, reference_rot, display_pos, display_rot)
            series_t.append((float(row["render_mono_ms"]) - t0) / 1000.0)
            series_e.append(translation_m * 1000.0)
        time_s[variant] = np.asarray(series_t, dtype=float)
        translation_mm[variant] = np.asarray(series_e, dtype=float)
    return {
        "time_s": time_s,
        "translation_mm": translation_mm,
        "trial_id": str(trial_id),
        "t0_ms": t0,
    }


def extract_event_times(
    events: pd.DataFrame,
    scenario: str,
    trial_id: str,
    t0_ms: float,
    *,
    roles: Sequence[str] | None = None,
) -> dict[str, list[float]]:
    """按事件角色返回相对 trial 起点（秒）的标注时刻，供时间线阴影/竖线使用。"""

    result: dict[str, list[float]] = {}
    required = {"scenario_id", "trial_id", "event_type", "mono_ms", "payload"}
    if events.empty or not required.issubset(events.columns) or not np.isfinite(t0_ms):
        return result
    marker = events.loc[
        events["event_type"].astype(str).eq("event_marker")
        & events["scenario_id"].astype(str).eq(scenario)
        & events["trial_id"].astype(str).eq(trial_id)
    ]
    for _, row in marker.iterrows():
        payload = row.get("payload")
        role = str(payload.get("event_role", "")) if isinstance(payload, dict) else ""
        if roles is not None and role not in roles:
            continue
        mono = pd.to_numeric(pd.Series([row.get("mono_ms")]), errors="coerce").iloc[0]
        if np.isfinite(mono):
            result.setdefault(role or "marker", []).append((float(mono) - t0_ms) / 1000.0)
    return result


def occlusion_intervals(events: pd.DataFrame, trial_id: str, t0_ms: float) -> list[tuple[float, float]]:
    """把 occlusion_started→target_visible 成对事件转换为相对秒的遮挡区间。"""

    annotations = extract_event_times(
        events,
        "occlusion_recovery",
        trial_id,
        t0_ms,
        roles=("occlusion_started", "target_visible"),
    )
    starts = sorted(annotations.get("occlusion_started", []))
    visibles = sorted(annotations.get("target_visible", []))
    intervals: list[tuple[float, float]] = []
    for start in starts:
        end_candidates = [value for value in visibles if value > start]
        if end_candidates:
            intervals.append((start, min(end_candidates)))
    return intervals


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
    "HEADLINE_COLUMNS",
    "PAIR_COLUMNS",
    "SCENARIO_ORDER",
    "TRIAL_VALUE_COLUMNS",
    "build_condition_summary",
    "build_paired_trial_metrics",
    "build_scenario_headline",
    "build_trial_metrics",
    "compute_exp1_tables",
    "concat_exp1_tables",
    "extract_event_times",
    "extract_timeline_series",
    "occlusion_intervals",
]

"""实验一的场景、参考覆盖和同步矩阵质量门禁。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from egoanchor.eval.schema_v2 import (
    EvalSessionV2,
    accepted_trial_table,
    load_session_v2,
    run_schema_qc,
    select_completed_trials,
)

from .contract import DEFAULT_MIN_REFERENCE_COVERAGE, EXPERIMENT_ID, SCENARIOS, VARIANTS


TRIAL_COLUMNS = (
    "session_id",
    "experiment_id",
    "scenario_id",
    "trial_id",
    "event_id",
    "condition_id",
)
"""trial QC 与后续配对共用的稳定上下文键。"""


@dataclass(frozen=True)
class Exp1QcReport:
    """一个 session 的实验一质量检查结果。"""

    session_id: str
    """schema-v2 session 标识。"""

    passed: bool
    """全部基础与实验一门禁均通过时为真。"""

    errors: tuple[str, ...] = ()
    """阻止正式分析的问题。"""

    warnings: tuple[str, ...] = ()
    """不阻止分析但需要记录的问题。"""

    metrics: dict[str, Any] = field(default_factory=dict)
    """用于 ``exp1_session_qc.csv`` 的覆盖统计。"""

    trial_qc: pd.DataFrame = field(default_factory=pd.DataFrame)
    """逐 trial/event 的变体矩阵与参考覆盖检查。"""

    contributes: bool = False
    """当前 session 是否包含至少一个实验一完成任务。"""


def run_exp1_qc(
    session: EvalSessionV2 | str | Path,
    *,
    min_reference_coverage: float = DEFAULT_MIN_REFERENCE_COVERAGE,
) -> Exp1QcReport:
    """执行 schema-v2 基础 QC 和实验一专属门禁。"""

    if not 0.0 <= min_reference_coverage <= 1.0:
        raise ValueError("min_reference_coverage 必须位于 [0, 1]。")
    loaded = load_session_v2(session) if isinstance(session, (str, Path)) else session
    base = run_schema_qc(loaded)
    errors = list(base.errors)
    warnings = list(base.warnings)
    metrics = dict(base.metrics)
    accepted = select_completed_trials(loaded)

    completed = accepted_trial_table(loaded)
    target_trials = completed[completed["experiment_id"].astype(str).eq(EXPERIMENT_ID)]
    contributes = not target_trials.empty

    render = _experiment_variant_rows(accepted.unity_render)
    admission = _experiment_variant_rows(accepted.unity_admission)
    observed_scenarios = set(target_trials["scenario_id"].astype(str))
    unknown_scenarios = sorted(observed_scenarios - set(SCENARIOS))
    if unknown_scenarios:
        errors.append(f"实验一 session 包含未知场景：{unknown_scenarios}")

    trial_qc = build_trial_qc(render, min_reference_coverage=min_reference_coverage)
    if contributes:
        manifest_labels = _manifest_variant_labels(loaded.manifest)
        missing_manifest_variants = sorted(set(VARIANTS) - manifest_labels)
        if missing_manifest_variants:
            errors.append(f"实验一 manifest 缺少配置：{missing_manifest_variants}")
        missing_render_scenarios = sorted(
            observed_scenarios
            - set(render.get("scenario_id", pd.Series(dtype=str)).dropna().astype(str))
        )
        if missing_render_scenarios:
            errors.append(f"实验一完成任务缺少 render 数据：{missing_render_scenarios}")
        _check_table_variant_coverage(render, "unity_render", errors)
        _check_table_variant_coverage(admission, "unity_admission", errors)
        _check_render_ticks(render, errors)
    failed_trials = trial_qc.loc[~trial_qc["passed"]] if not trial_qc.empty else trial_qc
    for _, row in failed_trials.iterrows():
        context = "/".join(str(row[column]) for column in TRIAL_COLUMNS)
        errors.append(f"实验一 trial QC 失败 {context}：{row['reason']}")

    metrics.update(
        exp1_render_rows=int(len(render)),
        exp1_admission_rows=int(len(admission)),
        exp1_scenario_count=int(len(observed_scenarios)),
        exp1_trial_count=int(len(trial_qc)),
        exp1_rejected_trial_count=_rejected_trial_count(loaded.events),
        exp1_min_reference_coverage=float(min_reference_coverage),
        exp1_observed_scenarios=",".join(sorted(observed_scenarios)),
    )
    return Exp1QcReport(
        session_id=loaded.session_id,
        passed=not errors,
        errors=tuple(errors),
        warnings=tuple(warnings),
        metrics=metrics,
        trial_qc=trial_qc,
        contributes=contributes,
    )


def _rejected_trial_count(events: pd.DataFrame) -> int:
    """返回 session 中被操作者显式作废的唯一 trial 数。"""

    if events.empty or "event_type" not in events.columns:
        return 0
    rejected = events[events["event_type"].astype(str).eq("trial_rejected")]
    keys = ["session_id", "experiment_id", "scenario_id", "trial_id"]
    return int(len(rejected.loc[:, keys].drop_duplicates()))


def build_trial_qc(
    render: pd.DataFrame,
    *,
    min_reference_coverage: float = DEFAULT_MIN_REFERENCE_COVERAGE,
) -> pd.DataFrame:
    """按 trial/event 检查四配置配对和平台参考覆盖率。"""

    columns = [
        *TRIAL_COLUMNS,
        "render_tick_count",
        "variant_count",
        "reference_coverage",
        "passed",
        "reason",
    ]
    if render.empty:
        return pd.DataFrame(columns=columns)
    required = {*TRIAL_COLUMNS, "render_tick_id", "variant_label", "reference_pose_valid"}
    missing = sorted(required - set(render.columns))
    if missing:
        raise ValueError(f"unity_render 缺少实验一 trial QC 字段：{missing}")

    rows: list[dict[str, Any]] = []
    for values, group in render.groupby(list(TRIAL_COLUMNS), dropna=False, sort=True):
        context = dict(zip(TRIAL_COLUMNS, values, strict=True))
        labels = set(group["variant_label"].dropna().astype(str))
        missing_variants = sorted(set(VARIANTS) - labels)
        coverage = float(group["reference_pose_valid"].fillna(False).astype(bool).mean())
        reasons: list[str] = []
        if missing_variants:
            reasons.append(f"missing variants={missing_variants}")
        if coverage < min_reference_coverage:
            reasons.append(
                f"reference coverage={coverage:.3f} < {min_reference_coverage:.3f}"
            )
        rows.append(
            {
                **context,
                "render_tick_count": int(group["render_tick_id"].nunique()),
                "variant_count": int(len(labels)),
                "reference_coverage": coverage,
                "passed": not reasons,
                "reason": " | ".join(reasons),
            }
        )
    return pd.DataFrame.from_records(rows, columns=columns)


def require_exp1_qc(
    session: EvalSessionV2 | str | Path,
    *,
    min_reference_coverage: float = DEFAULT_MIN_REFERENCE_COVERAGE,
) -> Exp1QcReport:
    """要求实验一 QC 通过，否则阻止指标和论文产物生成。"""

    report = run_exp1_qc(session, min_reference_coverage=min_reference_coverage)
    if not report.passed:
        raise ValueError("实验一 QC 失败：" + "; ".join(report.errors))
    return report


def _experiment_variant_rows(table: pd.DataFrame) -> pd.DataFrame:
    """在完整 session 基础 QC 后，仅投影实验一冻结的四配置。"""

    if table.empty or not {"experiment_id", "variant_label"} <= set(table.columns):
        return table.iloc[0:0].copy()
    experiment = table["experiment_id"].astype(str).eq(EXPERIMENT_ID)
    required_variant = table["variant_label"].astype(str).isin(VARIANTS)
    return table.loc[experiment & required_variant].copy()


def _manifest_variant_labels(manifest: dict[str, Any]) -> set[str]:
    """从 manifest 提取非空配置显示名，缺 label 时使用稳定 ID。"""

    definitions = manifest.get("variant_definitions")
    if not isinstance(definitions, list):
        return set()
    return {
        str(item.get("variant_label") or item.get("variant_id"))
        for item in definitions
        if isinstance(item, dict) and (item.get("variant_label") or item.get("variant_id"))
    }


def _check_table_variant_coverage(
    table: pd.DataFrame,
    table_name: str,
    errors: list[str],
) -> None:
    """要求实验一表整体覆盖固定四配置。"""

    if table.empty:
        errors.append(f"实验一 {table_name} 为空")
        return
    if "variant_label" not in table.columns:
        errors.append(f"实验一 {table_name} 缺少 variant_label")
        return
    missing = sorted(set(VARIANTS) - set(table["variant_label"].dropna().astype(str)))
    if missing:
        errors.append(f"实验一 {table_name} 缺少配置：{missing}")


def _check_render_ticks(render: pd.DataFrame, errors: list[str]) -> None:
    """每个实验一 render tick 必须恰好包含四配置各一行。"""

    required = {"session_id", "render_tick_id", "variant_label"}
    missing = sorted(required - set(render.columns))
    if render.empty or missing:
        if missing:
            errors.append(f"实验一 unity_render 缺少 tick 配对字段：{missing}")
        return
    for values, group in render.groupby(["session_id", "render_tick_id"], dropna=False, sort=True):
        labels = list(group["variant_label"].dropna().astype(str))
        missing_labels = sorted(set(VARIANTS) - set(labels))
        duplicates = sorted(label for label in set(labels) if labels.count(label) > 1)
        if missing_labels or duplicates or len(labels) != len(VARIANTS):
            errors.append(
                f"实验一 render tick {values!r} 配对不完整："
                f"missing={missing_labels}, duplicates={duplicates}, rows={len(labels)}"
            )


__all__ = [
    "Exp1QcReport",
    "TRIAL_COLUMNS",
    "build_trial_qc",
    "require_exp1_qc",
    "run_exp1_qc",
]

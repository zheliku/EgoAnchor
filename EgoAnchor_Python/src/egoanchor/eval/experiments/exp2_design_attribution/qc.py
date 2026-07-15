"""实验二完整 session、单组件消融和 trial 配对质量门禁。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from egoanchor.eval.schema_v2 import EvalSessionV2, load_session_v2, run_schema_qc

from .contract import (
    ABLATION_COMPONENT,
    BASELINE_VARIANT,
    COMPONENT_KEYS,
    EXPERIMENT_ID,
    REQUIRED_VARIANTS,
    SCENARIO_ABLATION,
    variant_contracts,
)


TRIAL_COLUMNS = (
    "session_id",
    "experiment_id",
    "scenario_id",
    "trial_id",
    "event_id",
    "condition_id",
)
"""实验二 trial/event 审计使用的稳定上下文键。"""


@dataclass(frozen=True)
class Exp2QcReport:
    """一个 schema-v2 session 的实验二质量检查结果。"""

    session_id: str
    """被检查的 session 标识。"""

    passed: bool
    """基础 QC、组件契约和配对矩阵全部通过时为真。"""

    errors: tuple[str, ...] = ()
    """阻止正式分析的问题。"""

    warnings: tuple[str, ...] = ()
    """不阻止分析但必须进入审计表的问题。"""

    metrics: dict[str, Any] = field(default_factory=dict)
    """session 级覆盖统计。"""

    trial_qc: pd.DataFrame = field(default_factory=pd.DataFrame)
    """逐 trial/event 的对应消融配对检查。"""


def run_exp2_qc(session: EvalSessionV2 | str | Path) -> Exp2QcReport:
    """先执行完整 schema-v2 QC，再验证实验二专属契约。"""

    loaded = load_session_v2(session) if isinstance(session, (str, Path)) else session
    base = run_schema_qc(loaded)
    errors = list(base.errors)
    warnings = list(base.warnings)
    metrics = dict(base.metrics)

    experiment_ids = loaded.manifest.get("experiment_ids")
    if not isinstance(experiment_ids, list) or EXPERIMENT_ID not in experiment_ids:
        errors.append(f"manifest.experiment_ids 缺少 {EXPERIMENT_ID}")

    try:
        contracts = variant_contracts(loaded.manifest)
    except ValueError as exc:
        errors.append(str(exc))
        contracts = {}
    _check_component_contract(contracts, errors)

    render = _experiment_rows(loaded.unity_render)
    admission = _experiment_rows(loaded.unity_admission)
    _check_table_variants(render, "unity_render", errors)
    _check_table_variants(admission, "unity_admission", errors)
    _check_render_ticks(render, errors)
    trial_qc = build_trial_qc(render)
    for _, row in trial_qc.loc[~trial_qc["passed"]].iterrows():
        context = "/".join(str(row[column]) for column in TRIAL_COLUMNS)
        errors.append(f"实验二 trial QC 失败 {context}：{row['reason']}")

    observed_scenarios = set(
        render.get("scenario_id", pd.Series(dtype=str)).dropna().astype(str)
    )
    if str(loaded.manifest.get("run_kind", "")).lower() == "formal":
        missing_scenarios = sorted(set(SCENARIO_ABLATION) - observed_scenarios)
        if missing_scenarios:
            errors.append(f"实验二 Formal session 缺少归因场景：{missing_scenarios}")

    metrics.update(
        exp2_render_rows=int(len(render)),
        exp2_admission_rows=int(len(admission)),
        exp2_scenario_count=int(len(observed_scenarios)),
        exp2_trial_count=int(len(trial_qc)),
    )
    return Exp2QcReport(
        session_id=loaded.session_id,
        passed=not errors,
        errors=tuple(errors),
        warnings=tuple(warnings),
        metrics=metrics,
        trial_qc=trial_qc,
    )


def build_trial_qc(render: pd.DataFrame) -> pd.DataFrame:
    """按 trial/event 检查完整系统与场景对应消融是否同步存在。"""

    columns = [*TRIAL_COLUMNS, "paired_variant", "render_tick_count", "passed", "reason"]
    if render.empty:
        return pd.DataFrame(columns=columns)
    required = {*TRIAL_COLUMNS, "render_tick_id", "variant_label"}
    missing = sorted(required - set(render.columns))
    if missing:
        raise ValueError(f"unity_render 缺少实验二 trial QC 字段：{missing}")

    rows: list[dict[str, Any]] = []
    for values, group in render.groupby(list(TRIAL_COLUMNS), dropna=False, sort=True):
        context = dict(zip(TRIAL_COLUMNS, values, strict=True))
        scenario_id = str(context["scenario_id"])
        paired_variant = SCENARIO_ABLATION.get(scenario_id, "")
        expected = {BASELINE_VARIANT, paired_variant} if paired_variant else set()
        labels = set(group["variant_label"].dropna().astype(str))
        reasons: list[str] = []
        if not paired_variant:
            reasons.append(f"unknown attribution scenario={scenario_id}")
        else:
            missing_labels = sorted(expected - labels)
            if missing_labels:
                reasons.append(f"missing paired variants={missing_labels}")
            for tick_id, tick in group.groupby("render_tick_id", dropna=False, sort=True):
                tick_labels = list(tick["variant_label"].dropna().astype(str))
                if any(tick_labels.count(label) != 1 for label in expected):
                    reasons.append(f"tick={tick_id!r} does not contain one paired row per variant")
                    break
        rows.append(
            {
                **context,
                "paired_variant": paired_variant,
                "render_tick_count": int(group["render_tick_id"].nunique()),
                "passed": not reasons,
                "reason": " | ".join(reasons),
            }
        )
    return pd.DataFrame.from_records(rows, columns=columns)


def _check_component_contract(
    contracts: dict[str, Any],
    errors: list[str],
) -> None:
    """冻结 full 四项全开以及名称到唯一关闭组件的映射。"""

    missing = sorted(set(REQUIRED_VARIANTS) - set(contracts))
    if missing:
        errors.append(f"实验二 manifest 缺少配置：{missing}")
        return
    baseline = contracts[BASELINE_VARIANT]
    disabled_in_full = [key for key in COMPONENT_KEYS if not baseline.flags[key]]
    if disabled_in_full:
        errors.append(f"完整 EgoAnchor 必须启用四个归因组件：disabled={disabled_in_full}")

    for label, expected_component in ABLATION_COMPONENT.items():
        changed = contracts[label].changed_components(baseline)
        if changed != (expected_component,):
            errors.append(
                f"变体 {label!r} 必须且只能关闭 {expected_component}：observed={list(changed)}"
            )
        if contracts[label].flags[expected_component]:
            errors.append(f"变体 {label!r} 未关闭 {expected_component}")


def _experiment_rows(table: pd.DataFrame) -> pd.DataFrame:
    """在基础 QC 后仅投影实验二五个配置，不混入实验一基线。"""

    if table.empty or not {"experiment_id", "variant_label"} <= set(table.columns):
        return table.iloc[0:0].copy()
    mask = (
        table["experiment_id"].astype(str).eq(EXPERIMENT_ID)
        & table["variant_label"].astype(str).isin(REQUIRED_VARIANTS)
    )
    return table.loc[mask].copy()


def _check_table_variants(table: pd.DataFrame, table_name: str, errors: list[str]) -> None:
    """要求实验二长表整体覆盖 full 与全部四消融。"""

    if table.empty:
        errors.append(f"实验二 {table_name} 为空")
        return
    missing = sorted(set(REQUIRED_VARIANTS) - set(table["variant_label"].dropna().astype(str)))
    if missing:
        errors.append(f"实验二 {table_name} 缺少配置：{missing}")


def _check_render_ticks(render: pd.DataFrame, errors: list[str]) -> None:
    """投影后的每个 render tick 必须恰好包含五个实验二配置。"""

    required = {"session_id", "render_tick_id", "variant_label"}
    missing = sorted(required - set(render.columns))
    if render.empty or missing:
        if missing:
            errors.append(f"实验二 unity_render 缺少 tick 配对字段：{missing}")
        return
    for values, group in render.groupby(["session_id", "render_tick_id"], dropna=False):
        labels = list(group["variant_label"].dropna().astype(str))
        missing_labels = sorted(set(REQUIRED_VARIANTS) - set(labels))
        duplicates = sorted(label for label in set(labels) if labels.count(label) > 1)
        if missing_labels or duplicates or len(labels) != len(REQUIRED_VARIANTS):
            errors.append(
                f"实验二 render tick {values!r} 投影不完整："
                f"missing={missing_labels}, duplicates={duplicates}, rows={len(labels)}"
            )


__all__ = ["Exp2QcReport", "TRIAL_COLUMNS", "build_trial_qc", "run_exp2_qc"]

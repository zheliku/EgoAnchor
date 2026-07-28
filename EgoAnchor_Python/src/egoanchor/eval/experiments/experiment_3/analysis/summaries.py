"""实验三问卷、对象、操纵检验与绘图数据汇总。"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime, time, timedelta
from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd

from .contracts import (
    AnalysisTables,
    BLOCK_ITEMS,
    EGOANCHOR,
    Exp3Data,
    METHODS,
    OBJECTS,
    ONE_EURO,
    PARTICIPANT_BACKGROUND_COLUMNS,
    PARTICIPANT_CATEGORIES,
    PRIMARY_OUTCOMES,
    SCALE_OUTCOMES,
    ScoreData,
)
from .inference import (
    empty_paired_result,
    holm_adjust,
    paired_result,
    paired_tost,
    quartiles,
    reliability_results,
)
from .reader import (
    block_valid_mask,
    included_participant_ids,
    method_assessment_complete_mask,
    method_record_valid_mask,
)
from .settings import AnalysisSettings


_SECONDARY_ITEMS = ("AQ_EQ1", "AQ_EQ2", "AQ_EQ3", "AQ_IQ1", "AQ_IQ2", "AQ_IQ3")
"""保留单项探索结果的 AQ 条目。"""

_OPEN_THEMES = (
    "Stationary_Jitter",
    "Viewpoint_Drift",
    "Absolute_Offset",
    "Motion_Lag",
    "Motion_Sliding",
    "Orientation_Mismatch",
    "PostPlacement_Settling",
    "Recovery_Jump",
    "Wrong_Recovery",
    "Predictability",
    "Embedding_Blending",
    "No_Noticeable_Difference",
    "Other",
)
"""权威计划预设的开放题多标签主题。"""


def analyze_scores(
    data: Exp3Data,
    scores: ScoreData,
    settings: AnalysisSettings,
) -> AnalysisTables:
    """计算主分析、量表、描述性结果和绘图长表。"""

    participant_summary, participant_balance, participant_audit = _participant_results(
        data,
        settings=settings,
    )
    primary = _family_results(scores.paired_scores, PRIMARY_OUTCOMES, settings)
    scales = _family_results(scores.paired_scores, SCALE_OUTCOMES, settings)
    reliability = reliability_results(scores.reliability_items, settings)
    scales = scales.merge(
        _reliability_wide(reliability),
        on="Outcome",
        how="left",
        validate="one_to_one",
    )
    secondary_outcomes = list(_SECONDARY_ITEMS)
    if settings.q10_enabled:
        secondary_outcomes.insert(0, "Q10")
    secondary_pairs = _pair_block_items(data, secondary_outcomes)
    secondary = _family_results(secondary_pairs, secondary_outcomes, settings, holm=False)
    objects = _object_results(scores.block_scores, settings)
    manipulation = _manipulation_results(data, settings)
    choices, choice_cross = _choice_results(data)
    open_coding = _open_coding_table(data)
    plot_paired = _plot_paired(scores.block_scores)
    plot_scales = scores.aggregate_scores.loc[
        scores.aggregate_scores["Outcome"].isin(("Q6", "Q7", *SCALE_OUTCOMES))
    ].copy()
    return AnalysisTables(
        participant_summary=participant_summary,
        participant_balance=participant_balance,
        participant_audit=participant_audit,
        primary=primary,
        scales=scales,
        secondary=secondary,
        reliability=reliability,
        objects=objects,
        manipulation=manipulation,
        choices=choices,
        choice_cross=choice_cross,
        open_coding=open_coding,
        plot_paired=plot_paired,
        plot_scales=plot_scales,
    )


def _participant_results(
    data: Exp3Data,
    *,
    settings: AnalysisSettings,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """生成样本流程、论文描述、平衡性和逐人审计表。"""

    audit = _participant_audit(data)
    included = audit[audit["Included"]]
    consented = audit[audit["Consented"]]
    exposed = consented[consented["Started"]]
    included_denominator = len(consented) or len(included)
    summary_rows: list[dict[str, Any]] = []

    def add_count(section: str, variable: str, category: str, count: int, denominator: int, role: str) -> None:
        """追加一行显式分母的计数和比例。"""

        summary_rows.append(
            {
                "Section": section,
                "Variable": variable,
                "Category": category,
                "N": count,
                "Denominator": denominator,
                "Proportion": count / denominator if denominator else math.nan,
                "Paper_Role": role,
            }
        )

    add_count(
        "Sample_Flow",
        "Preallocated_Slots",
        "all",
        len(audit),
        settings.target_participants,
        "audit",
    )
    add_count("Sample_Flow", "Consented", "yes", len(consented), len(audit), "main_text")
    add_count("Sample_Flow", "Started", "yes", int(consented["Started"].sum()), len(consented), "main_text")
    add_count(
        "Sample_Flow",
        "Completed_Session",
        "yes",
        int(consented["Completed_Session"].sum()),
        len(consented),
        "main_text",
    )
    add_count("Sample_Flow", "Included", "yes", len(included), included_denominator, "main_text")
    add_count("Sample_Flow", "Excluded", "yes", int(consented["Excluded"].sum()), len(consented), "main_text")
    add_count(
        "Sample_Flow",
        "Pending_Review",
        "yes",
        int(consented["Pending_Review"].sum()),
        len(consented),
        "audit",
    )

    _append_continuous_summary(summary_rows, included["Age"], "Age", len(included), "main_text")
    _append_continuous_summary(
        summary_rows,
        included["Session_Duration_Minutes"],
        "Session_Duration_Minutes",
        len(included),
        "supplement",
    )
    for variable, categories in PARTICIPANT_CATEGORIES.items():
        is_safety = "Discomfort" in variable
        population = exposed if is_safety else included
        values = population[variable]
        for category in categories:
            add_count(
                "Safety" if is_safety else "Participant_Profile",
                variable,
                category,
                int((values.astype(str) == category).sum()),
                len(population),
                "main_text" if variable in {"Gender", "Handedness", "Vision"} else "supplement",
            )
        add_count(
            "Safety" if is_safety else "Participant_Profile",
            variable,
            "Missing",
            sum(_is_missing(value) for value in values),
            len(population),
            "missingness",
        )

    comparable = exposed[exposed["Discomfort_Change"].notna()]
    worsened = int((comparable["Discomfort_Change"] == "Worsened").sum())
    add_count("Safety", "Discomfort_Change", "Worsened", worsened, len(comparable), "main_text")

    excluded = audit[audit["Excluded"]]
    reasons = excluded["Exclusion_Reason"].map(lambda value: "Missing" if _is_missing(value) else str(value).strip())
    for reason, count in reasons.value_counts(dropna=False, sort=False).items():
        add_count("Exclusion", "Exclusion_Reason", str(reason), int(count), len(excluded), "main_text")

    summary = pd.DataFrame(summary_rows)
    balance = _participant_balance(
        data.participants,
        target_participants=settings.target_participants,
    )
    return summary, balance, audit


def _participant_audit(data: Exp3Data) -> pd.DataFrame:
    """将 Participants 和三段 Records 合并为不含自由备注的逐人审计表。"""

    blocks = data.blocks.copy()
    blocks["_valid"] = block_valid_mask(blocks)
    valid_blocks = blocks.groupby(blocks["Participant_ID"].astype(str))["_valid"].sum()
    methods = data.methods.copy()
    methods["_completed"] = method_assessment_complete_mask(methods)
    methods["_valid"] = method_record_valid_mask(methods)
    completed_methods = methods.groupby(methods["Participant_ID"].astype(str))["_completed"].sum()
    valid_methods = methods.groupby(methods["Participant_ID"].astype(str))["_valid"].sum()
    finals = data.finals.set_index(data.finals["Participant_ID"].astype(str), drop=False)

    rows: list[dict[str, Any]] = []
    for _, source in data.participants.iterrows():
        participant_id = str(source["Participant_ID"])
        final = finals.loc[participant_id]
        included = _is_yes(source.get("纳入分析"))
        explicitly_excluded = _is_no(source.get("纳入分析")) and _is_yes(source.get("签署同意"))
        final_complete = _final_complete(final)
        started = not _is_missing(source.get("开始时间"))
        completed_session = started and not _is_missing(source.get("结束时间"))
        block_count = int(valid_blocks.get(participant_id, 0)) if included else 0
        completed_method_count = int(completed_methods.get(participant_id, 0))
        valid_method_count = int(valid_methods.get(participant_id, 0)) if included else 0
        analysis_complete = (
            included
            and block_count == 6
            and completed_method_count == 2
            and valid_method_count == 2
            and final_complete
        )
        audit_status = _audit_status(
            source,
            included=included,
            explicitly_excluded=explicitly_excluded,
            analysis_complete=analysis_complete,
        )
        baseline_discomfort = source.get("基线不适")
        end_discomfort = final.get("结束不适")
        row: dict[str, Any] = {
            "Participant_ID": participant_id,
            "Consented": _is_yes(source.get("签署同意")),
            "Started": started,
            "Completed_Session": completed_session,
            "Analysis_Complete": analysis_complete,
            "Included": included,
            "Excluded": explicitly_excluded,
            "Pending_Review": _is_yes(source.get("签署同意")) and not included and not explicitly_excluded,
            "Valid_Blocks": block_count,
            "Completed_Method_Assessments": completed_method_count,
            "Valid_Method_Records": valid_method_count,
            "Final_Complete": final_complete,
            "Session_Duration_Minutes": _duration_minutes(source.get("开始时间"), source.get("结束时间")),
            "Consent": source.get("签署同意"),
            "Baseline_Discomfort": baseline_discomfort,
            "End_Discomfort": end_discomfort,
            "Discomfort_Change": _discomfort_change(baseline_discomfort, end_discomfort),
            "Exclusion_Reason": source.get("退出/技术问题"),
            "Audit_Status": audit_status,
        }
        for output_column, source_column in PARTICIPANT_BACKGROUND_COLUMNS.items():
            row[output_column] = source.get(source_column) if included else math.nan
        rows.append(row)
    columns = (
        "Participant_ID", "Consented", "Started", "Completed_Session", "Analysis_Complete",
        "Included", "Excluded",
        "Pending_Review", "Age", "Gender", "Handedness", "Vision", "VRMR_Experience",
        "PhysicalMR_Experience", "Session_Duration_Minutes", "Valid_Blocks",
        "Completed_Method_Assessments", "Valid_Method_Records", "Final_Complete",
        "Consent", "Baseline_Discomfort", "End_Discomfort",
        "Discomfort_Change", "Exclusion_Reason", "Audit_Status",
    )
    return pd.DataFrame(rows, columns=columns)


def _append_continuous_summary(
    rows: list[dict[str, Any]],
    series: pd.Series,
    variable: str,
    denominator: int,
    role: str,
) -> None:
    """追加连续变量的 N、均值、SD、中位数、IQR 与范围。"""

    values = pd.to_numeric(series, errors="coerce").dropna().to_numpy(dtype=float)
    q1, median, q3 = quartiles(values) if len(values) else (math.nan, math.nan, math.nan)
    rows.append(
        {
            "Section": "Participant_Profile",
            "Variable": variable,
            "Category": "Summary",
            "N": int(len(values)),
            "Denominator": denominator,
            "Proportion": len(values) / denominator if denominator else math.nan,
            "Mean": float(np.mean(values)) if len(values) else math.nan,
            "SD": float(np.std(values, ddof=1)) if len(values) > 1 else math.nan,
            "Median": median,
            "Q1": q1,
            "Q3": q3,
            "Min": float(np.min(values)) if len(values) else math.nan,
            "Max": float(np.max(values)) if len(values) else math.nan,
            "Missing_N": denominator - len(values),
            "Paper_Role": role,
        }
    )


def _participant_balance(participants: pd.DataFrame, *, target_participants: int) -> pd.DataFrame:
    """按冻结设计因子报告实际人数与平衡偏差。"""

    factors = {
        "Balance_Unit": "平衡单元",
        "Object_Order": "物体排列ID",
        "Method_Sequence": "标签序列",
        "A_Mapping": "方法A=（保密）",
        "First_Method": "先行实际方法",
    }
    rows: list[dict[str, Any]] = []
    included = participants.loc[participants["纳入分析"].map(_is_yes)]
    included_count = len(included)
    for factor, column in factors.items():
        levels = tuple(participants[column].dropna().astype(str).unique())
        expected_target = target_participants / len(levels) if levels else math.nan
        expected_actual = included_count / len(levels) if levels else math.nan
        for level in levels:
            count = int((included[column].astype(str) == level).sum())
            deviation = count - expected_actual
            if factor == "Balance_Unit" and included_count < target_participants:
                status = "partial_coverage"
            elif abs(deviation) < 1e-12:
                status = "balanced"
            else:
                status = "review"
            rows.append(
                {
                    "Factor": factor,
                    "Level": level,
                    "N": count,
                    "Expected_At_Target": expected_target,
                    "Expected_At_Actual_N": expected_actual,
                    "Deviation_From_Actual_Balance": deviation,
                    "Status": status,
                }
            )
    return pd.DataFrame(rows)


def _final_complete(row: pd.Series) -> bool:
    """按最终问卷七项与偏好强度跳题规则判断完整。"""

    choice = row.get("方法选择(标签)")
    strength = row.get("偏好强度(1-7/NA)")
    required = (
        choice,
        row.get("信任选择(标签)"),
        row.get("区分信心(1-7)"),
        row.get("开放:最明显区别"),
        row.get("开放:最破坏信任的现象"),
        row.get("结束不适"),
    )
    if any(_is_missing(value) for value in required):
        return False
    if str(choice) == "无明显偏好":
        return _is_missing(strength) or str(strength).strip().lower() in {"n/a", "na"}
    numeric = pd.to_numeric(pd.Series([strength]), errors="coerce").iloc[0]
    return pd.notna(numeric) and 1 <= float(numeric) <= 7


def _audit_status(
    row: pd.Series,
    *,
    included: bool,
    explicitly_excluded: bool,
    analysis_complete: bool,
) -> str:
    """生成不替代人工决策的参与者流程状态。"""

    consented = _is_yes(row.get("签署同意"))
    manual_columns = (
        *PARTICIPANT_BACKGROUND_COLUMNS.values(),
        "签署同意",
        "基线不适",
        "开始时间",
        "结束时间",
        "纳入分析",
        "退出/技术问题",
        "备注",
    )
    manual_values = [row.get(column) for column in manual_columns if column in row.index]
    if not consented and all(_is_missing(value) for value in manual_values):
        return "unused_slot"
    if not consented:
        return "not_consented"
    if included:
        return "included_complete" if analysis_complete else "included_but_incomplete"
    if explicitly_excluded:
        return "excluded" if not _is_missing(row.get("退出/技术问题")) else "excluded_reason_missing"
    return "pending_review"


def _duration_minutes(start: Any, end: Any) -> float:
    """解析 Excel 日期时间或 HH:MM 文本，允许会话跨越午夜。"""

    if _is_missing(start) or _is_missing(end):
        return math.nan
    if isinstance(start, datetime) and isinstance(end, datetime):
        delta = end - start
        if delta.total_seconds() < 0:
            delta += timedelta(days=1)
        return delta.total_seconds() / 60.0
    if isinstance(start, (int, float, np.number)) and isinstance(end, (int, float, np.number)):
        start_value = float(start)
        end_value = float(end)
        if math.isfinite(start_value) and math.isfinite(end_value):
            return ((end_value - start_value) % 1.0) * 24 * 60
    start_time = _as_time(start)
    end_time = _as_time(end)
    if start_time is None or end_time is None:
        return math.nan
    start_minutes = start_time.hour * 60 + start_time.minute + start_time.second / 60
    end_minutes = end_time.hour * 60 + end_time.minute + end_time.second / 60
    return (end_minutes - start_minutes) % (24 * 60)


def _as_time(value: Any) -> time | None:
    """把 Excel 时间或常见时刻文本转为 time。"""

    if isinstance(value, time):
        return value
    if isinstance(value, datetime):
        return value.time()
    text = str(value).strip()
    for pattern in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text, pattern).time()
        except ValueError:
            continue
    return None


def _is_missing(value: Any) -> bool:
    """识别工作簿空白值。"""

    return value is None or bool(pd.isna(value)) or str(value).strip() == ""


def _discomfort_change(baseline: Any, end: Any) -> str | None:
    """按冻结安全等级返回不适变化方向。"""

    levels = {label: index for index, label in enumerate(PARTICIPANT_CATEGORIES["End_Discomfort"])}
    if _is_missing(baseline) or _is_missing(end):
        return None
    baseline_text = str(baseline).strip()
    end_text = str(end).strip()
    if baseline_text not in levels or end_text not in levels:
        return None
    difference = levels[end_text] - levels[baseline_text]
    if difference > 0:
        return "Worsened"
    if difference < 0:
        return "Improved"
    return "Unchanged"


def _is_yes(value: Any) -> bool:
    """识别明确肯定选项。"""

    return str(value or "").strip().lower() in {"是", "yes", "true", "1"}


def _is_no(value: Any) -> bool:
    """识别明确否定选项。"""

    return str(value or "").strip().lower() in {"否", "no", "false", "0"}


def _family_results(
    paired: pd.DataFrame,
    outcomes: Iterable[str],
    settings: AnalysisSettings,
    *,
    holm: bool = True,
) -> pd.DataFrame:
    """按冻结顺序计算一组配对结局，并可选执行 Holm。"""

    rows: list[dict[str, Any]] = []
    for outcome in outcomes:
        subset = paired[paired["Outcome"] == outcome].sort_values("Participant_ID")
        result = paired_result(
            subset[ONE_EURO].to_numpy(dtype=float),
            subset[EGOANCHOR].to_numpy(dtype=float),
            bootstrap_iterations=settings.bootstrap_iterations,
            bootstrap_seed=_outcome_seed(settings.bootstrap_seed, outcome),
            confidence_level=settings.confidence_level,
        )
        rows.append({"Outcome": outcome, **result})
    frame = pd.DataFrame(rows)
    frame["p_Holm"] = holm_adjust(frame["p_raw"]) if holm else np.nan
    frame["Significant"] = (
        frame["p_Holm"].lt(settings.alpha)
        if holm
        else frame["p_raw"].lt(settings.alpha)
    )
    return frame


def _pair_block_items(data: Any, outcomes: Iterable[str]) -> pd.DataFrame:
    """为探索性区块单项形成三个对象均值后的完整方法配对。"""

    included = included_participant_ids(data.participants)
    blocks = data.blocks.loc[
        data.blocks["Participant_ID"].astype(str).isin(included)
        & block_valid_mask(data.blocks)
    ].copy()
    rows: list[dict[str, Any]] = []
    for outcome in outcomes:
        column = BLOCK_ITEMS[outcome]
        blocks[column] = pd.to_numeric(blocks[column], errors="coerce")
        grouped = (
            blocks.groupby(["Participant_ID", "Condition(保密)"], as_index=False)
            .agg(
                Value=(column, "mean"),
                Count=(column, "count"),
                Objects=("Object_Key", "nunique"),
            )
        )
        grouped = grouped[(grouped["Count"] == 3) & (grouped["Objects"] == 3)]
        pivot = grouped.pivot(
            index="Participant_ID",
            columns="Condition(保密)",
            values="Value",
        )
        if not set(METHODS).issubset(pivot.columns):
            continue
        for participant_id, values in pivot.dropna(subset=list(METHODS)).iterrows():
            rows.append(
                {
                    "Participant_ID": str(participant_id),
                    "Outcome": outcome,
                    ONE_EURO: float(values[ONE_EURO]),
                    EGOANCHOR: float(values[EGOANCHOR]),
                    "Difference": float(values[EGOANCHOR] - values[ONE_EURO]),
                }
            )
    return pd.DataFrame(rows)


def _object_results(block_scores: pd.DataFrame, settings: AnalysisSettings) -> pd.DataFrame:
    """按三个对象输出区块结局的配对描述统计。"""

    outcomes = list(PRIMARY_OUTCOMES) + list(SCALE_OUTCOMES[:2])
    if settings.q10_enabled:
        outcomes.append("Q10")
    rows: list[dict[str, Any]] = []
    for outcome in outcomes:
        column = (
            outcome
            if outcome.startswith("AQ_") and outcome in {"AQ_EQ", "AQ_IQ"}
            else BLOCK_ITEMS[outcome]
        )
        for object_key in OBJECTS:
            subset = block_scores[block_scores["Object_Key"] == object_key]
            pivot = subset.pivot_table(
                index="Participant_ID",
                columns="Condition(保密)",
                values=column,
                aggfunc="first",
            )
            if not set(METHODS).issubset(pivot.columns):
                result = empty_paired_result()
            else:
                paired = pivot.dropna(subset=list(METHODS))
                result = paired_result(
                    paired[ONE_EURO],
                    paired[EGOANCHOR],
                    bootstrap_iterations=max(1000, settings.bootstrap_iterations // 5),
                    bootstrap_seed=_outcome_seed(
                        settings.bootstrap_seed,
                        f"{outcome}:{object_key}",
                    ),
                    confidence_level=settings.confidence_level,
                )
            rows.append({"Outcome": outcome, "Object_Key": object_key, **result})
    return pd.DataFrame(rows)


def _manipulation_results(data: Any, settings: AnalysisSettings) -> pd.DataFrame:
    """汇总连续输入一致性、生命周期和重获取审计。"""

    included = included_participant_ids(data.participants)
    blocks = data.blocks.loc[
        data.blocks["Participant_ID"].astype(str).isin(included)
        & block_valid_mask(data.blocks)
    ].copy()
    continuous = {
        "Candidate_Rate_Hz": "Candidate_Rate_Hz",
        "VCD_Median": "VCD_Median",
        "VCD_Admission_Rate": "VCD_Admission_Rate",
        "Output_Availability": "Output_Availability",
        "Occlusion_Seconds": "遮挡时长_s",
    }
    rows: list[dict[str, Any]] = []
    for metric, column in continuous.items():
        blocks[column] = pd.to_numeric(blocks[column], errors="coerce")
        participant_means = (
            blocks.groupby(["Participant_ID", "Condition(保密)"], as_index=False)[
                column
            ].mean()
        )
        pivot = participant_means.pivot(
            index="Participant_ID",
            columns="Condition(保密)",
            values=column,
        )
        paired = (
            pivot.dropna(subset=list(METHODS))
            if set(METHODS).issubset(pivot.columns)
            else pd.DataFrame()
        )
        if paired.empty:
            left = np.array([], dtype=float)
            right = np.array([], dtype=float)
        else:
            left = paired[ONE_EURO].to_numpy(dtype=float)
            right = paired[EGOANCHOR].to_numpy(dtype=float)
        margin = settings.equivalence_margins[metric]
        tost = (
            paired_tost(right - left, margin)
            if settings.equivalence_enabled
            else paired_tost([], 0.0)
        )
        rows.append(
            {
                "Metric": metric,
                "Type": "continuous",
                "N_Pairs": int(len(left)),
                "OneEuro_Mean": float(np.mean(left)) if len(left) else math.nan,
                "EgoAnchor_Mean": float(np.mean(right)) if len(right) else math.nan,
                "Difference_Mean": (
                    float(np.mean(right - left)) if len(left) else math.nan
                ),
                "Margin": margin if settings.equivalence_enabled else math.nan,
                **tost,
                "Status": (
                    ("equivalent" if tost["Equivalent"] else "not_equivalent")
                    if settings.equivalence_enabled
                    else "not_run_margin_unfrozen"
                ),
            }
        )
    for method in METHODS:
        method_rows = blocks[blocks["Condition(保密)"].astype(str) == method]
        total = len(method_rows)
        for state in ("FrozenUncertain", "Lost", "Coasting"):
            count = int(
                (method_rows["遮挡生命周期状态"].astype(str) == state).sum()
            )
            rows.append(
                {
                    "Metric": f"Lifecycle_{state}",
                    "Type": "count",
                    "Condition": method,
                    "Count": count,
                    "Total": total,
                    "Proportion": count / total if total else math.nan,
                    "Status": (
                        "majority"
                        if state == "FrozenUncertain" and count > total / 2
                        else "descriptive"
                    ),
                }
            )
        for metric, column in (
            ("Server_Reacquisition_Count", "服务器重获取次数"),
            ("StaticLock_Enter_Count", "StaticLock进入次数"),
        ):
            values = pd.to_numeric(method_rows[column], errors="coerce")
            rows.append(
                {
                    "Metric": metric,
                    "Type": "count",
                    "Condition": method,
                    "Count": float(values.sum(min_count=1)),
                    "Total": int(values.notna().sum()),
                    "Status": "descriptive",
                }
            )
    return pd.DataFrame(rows)


def _choice_results(data: Any) -> tuple[pd.DataFrame, pd.DataFrame]:
    """解码最终标签选择并计算描述统计与三乘三交叉表。"""

    included = included_participant_ids(data.participants)
    participants = data.participants.set_index("Participant_ID")
    finals = data.finals[data.finals["Participant_ID"].astype(str).isin(included)].copy()
    decoded: list[dict[str, Any]] = []
    for _, row in finals.iterrows():
        participant_id = str(row["Participant_ID"])
        mapping = participants.loc[participant_id]
        label_map = {
            "方法A": str(mapping["方法A=（保密）"]),
            "方法B": str(mapping["方法B=（保密）"]),
            "无明显偏好": "无明显偏好",
        }
        decoded.append(
            {
                "Participant_ID": participant_id,
                "Method_Choice": label_map[str(row["方法选择(标签)"])],
                "Trust_Choice": label_map[str(row["信任选择(标签)"])],
                "Preference_Strength": pd.to_numeric(
                    row["偏好强度(1-7/NA)"],
                    errors="coerce",
                ),
                "Discrimination_Confidence": pd.to_numeric(
                    row["区分信心(1-7)"],
                    errors="coerce",
                ),
                "Discomfort": row.get("结束不适"),
            }
        )
    frame = pd.DataFrame(decoded)
    rows: list[dict[str, Any]] = []
    choices = (EGOANCHOR, ONE_EURO, "无明显偏好")
    for measure, column in (
        ("Method_Choice", "Method_Choice"),
        ("Trust_Choice", "Trust_Choice"),
    ):
        for choice in choices:
            count = int((frame[column] == choice).sum())
            rows.append(
                {
                    "Measure": measure,
                    "Category": choice,
                    "Count": count,
                    "Proportion": count / len(frame) if len(frame) else math.nan,
                }
            )
    for measure, column in (
        ("Preference_Strength", "Preference_Strength"),
        ("Discrimination_Confidence", "Discrimination_Confidence"),
    ):
        values = frame[column].dropna().to_numpy(dtype=float)
        q1, median, q3 = (
            quartiles(values) if len(values) else (math.nan, math.nan, math.nan)
        )
        rows.append(
            {
                "Measure": measure,
                "Category": "summary",
                "Count": int(len(values)),
                "Median": median,
                "Q1": q1,
                "Q3": q3,
                "Mean": float(np.mean(values)) if len(values) else math.nan,
                "SD": float(np.std(values, ddof=1)) if len(values) > 1 else math.nan,
            }
        )
        for score in range(1, 8):
            rows.append(
                {
                    "Measure": measure,
                    "Category": str(score),
                    "Count": int((values == score).sum()),
                    "Proportion": (
                        float(np.mean(values == score)) if len(values) else math.nan
                    ),
                }
            )
    disagreement = frame["Method_Choice"] != frame["Trust_Choice"]
    rows.append(
        {
            "Measure": "Choice_Disagreement",
            "Category": "Method_Choice != Trust_Choice",
            "Count": int(disagreement.sum()),
            "Proportion": float(np.mean(disagreement)) if len(frame) else math.nan,
        }
    )
    cross = pd.crosstab(
        frame["Method_Choice"],
        frame["Trust_Choice"],
        dropna=False,
    ).reindex(index=choices, columns=choices, fill_value=0)
    cross.index.name = "Method_Choice"
    return pd.DataFrame(rows), cross.reset_index()


def _open_coding_table(data: Any) -> pd.DataFrame:
    """为两名独立编码者和最终裁决生成不覆盖原文的多标签工作区。"""

    included = included_participant_ids(data.participants)
    finals = data.finals[data.finals["Participant_ID"].astype(str).isin(included)]
    rows: list[dict[str, Any]] = []
    questions = (
        ("OPEN_DIFFERENCE", "开放:最明显区别"),
        ("OPEN_DISTRUST", "开放:最破坏信任的现象"),
    )
    for _, row in finals.iterrows():
        for question, column in questions:
            result: dict[str, Any] = {
                "Participant_ID": str(row["Participant_ID"]),
                "Question": question,
                "Raw_Text": row.get(column),
                "Coder1_ID": "",
                "Coder2_ID": "",
                "Adjudication_Note": "",
            }
            for theme in _OPEN_THEMES:
                result[f"{theme}_Coder1"] = ""
                result[f"{theme}_Coder2"] = ""
                result[f"{theme}_Final"] = ""
            rows.append(result)
    return pd.DataFrame(rows)


def _plot_paired(block_scores: pd.DataFrame) -> pd.DataFrame:
    """生成冻结四面板使用的逐参与者逐物体长表。"""

    rows: list[dict[str, Any]] = []
    for outcome in ("Q1", "Q8", "Q3", "Q6"):
        column = BLOCK_ITEMS[outcome]
        for _, row in block_scores.iterrows():
            value = pd.to_numeric(row[column], errors="coerce")
            if pd.notna(value):
                rows.append(
                    {
                        "Participant_ID": str(row["Participant_ID"]),
                        "Outcome": outcome,
                        "Object_Key": str(row["Object_Key"]),
                        "Condition": str(row["Condition(保密)"]),
                        "Value": float(value),
                    }
                )
    return pd.DataFrame(rows)


def _reliability_wide(reliability: pd.DataFrame) -> pd.DataFrame:
    """把方法级信度长表展开为量表结果的一行式列。"""

    rows: list[dict[str, Any]] = []
    for outcome, group in reliability.groupby("Outcome", sort=False):
        result: dict[str, Any] = {"Outcome": outcome}
        for _, row in group.iterrows():
            suffix = "EA" if row["Condition"] == EGOANCHOR else "OE"
            result[f"Reliability_N_{suffix}"] = row["N"]
            result[f"Alpha_{suffix}"] = row["Cronbach_Alpha"]
            result[f"Omega_{suffix}"] = row["Omega_Total"]
            result[f"SpearmanBrown_{suffix}"] = row["Spearman_Brown"]
        rows.append(result)
    return pd.DataFrame(rows)


def _outcome_seed(base_seed: int, outcome: str) -> int:
    """由全局种子和稳定结局键派生跨进程一致的子种子。"""

    digest = hashlib.sha256(f"{base_seed}:{outcome}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


__all__ = ["analyze_scores"]


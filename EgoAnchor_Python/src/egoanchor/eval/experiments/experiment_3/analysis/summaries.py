"""实验三问卷、对象、操纵检验与绘图数据汇总。"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable
from datetime import datetime, time, timedelta
from typing import Any

import numpy as np
import pandas as pd

from .contracts import (
    AnalysisTables,
    BLOCK_ITEMS,
    EGOANCHOR,
    Exp3Data,
    MAIN_FAMILY,
    METHODS,
    OBJECTS,
    ONE_EURO,
    PARTICIPANT_BACKGROUND_COLUMNS,
    PARTICIPANT_CATEGORIES,
    PRIMARY_OUTCOMES,
    SCALE_FAMILY,
    SCALE_OUTCOMES,
    ScoreData,
)
from .inference import (
    holm_adjust,
    paired_result,
    paired_tost,
    quartiles,
    reliability_results,
)
from .reader import (
    block_valid_mask,
    included_participant_ids,
)
from .settings import AnalysisSettings


def analyze_scores(
    data: Exp3Data,
    scores: ScoreData,
    settings: AnalysisSettings,
) -> AnalysisTables:
    """计算六页结果工作簿需要的精简分析表。

    主结果严格限定为预先冻结的七个主条目和已发表量表家族五项结局；AQ 单项、Q10 和
    逐对象推断均不进入默认结果。Q10 若在未来预实验后启用，应另行登记为次级分析，
    不能静默混入已冻结的十二项结果。
    """

    sample = _participant_results(data, settings=settings)
    results = pd.concat(
        (
            _family_results(scores.paired_scores, PRIMARY_OUTCOMES, settings, family=MAIN_FAMILY),
            _family_results(scores.paired_scores, SCALE_OUTCOMES, settings, family=SCALE_FAMILY),
        ),
        ignore_index=True,
    )
    return AnalysisTables(
        sample=sample,
        results=results,
        objects=_object_descriptions(scores.block_scores),
        reliability=reliability_results(scores.reliability_items, settings),
        manipulation=_manipulation_results(data, settings),
        choices=_choice_results(data),
    )


def _participant_results(
    data: Exp3Data,
    *,
    settings: AnalysisSettings,
) -> pd.DataFrame:
    """生成样本流程、背景、安全与设计平衡摘要。"""

    participants = _participant_summary_frame(data)
    included = participants[participants["Included"]]
    consented = participants[participants["Consented"]]
    exposed = consented[consented["Started"]]
    included_denominator = len(consented) or len(included)
    summary_rows: list[dict[str, Any]] = []

    def add_count(
        section: str,
        variable: str,
        category: str,
        count: int,
        denominator: int,
    ) -> None:
        """追加一行显式分母的计数和比例。"""

        summary_rows.append(
            {
                "Section": section,
                "Variable": variable,
                "Category": category,
                "N": count,
                "Denominator": denominator,
                "Proportion": count / denominator if denominator else math.nan,
            }
        )

    add_count(
        "Sample_Flow",
        "Preallocated_Slots",
        "all",
        len(participants),
        settings.target_participants,
    )
    add_count(
        "Sample_Flow",
        "Consented",
        "yes",
        len(consented),
        len(participants),
    )
    add_count("Sample_Flow", "Started", "yes", int(consented["Started"].sum()), len(consented))
    add_count(
        "Sample_Flow",
        "Completed_Session",
        "yes",
        int(consented["Completed_Session"].sum()),
        len(consented),
    )
    add_count("Sample_Flow", "Included", "yes", len(included), included_denominator)
    add_count("Sample_Flow", "Excluded", "yes", int(consented["Excluded"].sum()), len(consented))
    add_count(
        "Sample_Flow",
        "Pending_Review",
        "yes",
        int(consented["Pending_Review"].sum()),
        len(consented),
    )

    _append_continuous_summary(summary_rows, included["Age"], "Age", len(included))
    _append_continuous_summary(
        summary_rows,
        included["Session_Duration_Minutes"],
        "Session_Duration_Minutes",
        len(included),
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
            )
        add_count(
            "Safety" if is_safety else "Participant_Profile",
            variable,
            "Missing",
            sum(_is_missing(value) for value in values),
            len(population),
        )

    comparable = exposed[exposed["Discomfort_Change"].notna()]
    worsened = int((comparable["Discomfort_Change"] == "Worsened").sum())
    add_count("Safety", "Discomfort_Change", "Worsened", worsened, len(comparable))

    excluded = participants[participants["Excluded"]]
    reasons = excluded["Exclusion_Reason"].map(lambda value: "Missing" if _is_missing(value) else str(value).strip())
    for reason, count in reasons.value_counts(dropna=False, sort=False).items():
        add_count("Exclusion", "Exclusion_Reason", str(reason), int(count), len(excluded))

    summary_rows.extend(
        _design_balance_rows(
            data.participants,
            target_participants=settings.target_participants,
        )
    )
    return pd.DataFrame(summary_rows)


def _participant_summary_frame(data: Exp3Data) -> pd.DataFrame:
    """合并样本描述真正需要的 Participants 字段与实验后不适。"""

    finals = data.finals.set_index(data.finals["Participant_ID"].astype(str), drop=False)

    rows: list[dict[str, Any]] = []
    for _, source in data.participants.iterrows():
        participant_id = str(source["Participant_ID"])
        final = finals.loc[participant_id]
        included = _is_yes(source.get("纳入分析"))
        explicitly_excluded = _is_no(source.get("纳入分析")) and _is_yes(source.get("签署同意"))
        started = not _is_missing(source.get("开始时间"))
        completed_session = started and not _is_missing(source.get("结束时间"))
        baseline_discomfort = source.get("基线不适")
        end_discomfort = final.get("结束不适")
        row: dict[str, Any] = {
            "Consented": _is_yes(source.get("签署同意")),
            "Started": started,
            "Completed_Session": completed_session,
            "Included": included,
            "Excluded": explicitly_excluded,
            "Pending_Review": _is_yes(source.get("签署同意")) and not included and not explicitly_excluded,
            "Session_Duration_Minutes": _duration_minutes(source.get("开始时间"), source.get("结束时间")),
            "Baseline_Discomfort": baseline_discomfort,
            "End_Discomfort": end_discomfort,
            "Discomfort_Change": _discomfort_change(baseline_discomfort, end_discomfort),
            "Exclusion_Reason": source.get("退出/技术问题"),
        }
        for output_column, source_column in PARTICIPANT_BACKGROUND_COLUMNS.items():
            row[output_column] = source.get(source_column) if included else math.nan
        rows.append(row)
    columns = (
        "Consented", "Started", "Completed_Session", "Included", "Excluded",
        "Pending_Review", "Age", "Gender", "Handedness", "Vision", "VRMR_Experience",
        "PhysicalMR_Experience", "Session_Duration_Minutes", "Baseline_Discomfort",
        "End_Discomfort", "Discomfort_Change", "Exclusion_Reason",
    )
    return pd.DataFrame(rows, columns=columns)


def _append_continuous_summary(
    rows: list[dict[str, Any]],
    series: pd.Series,
    variable: str,
    denominator: int,
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
        }
    )


def _design_balance_rows(
    participants: pd.DataFrame,
    *,
    target_participants: int,
) -> list[dict[str, Any]]:
    """按冻结设计因子生成实际人数与平衡偏差行，并入样本描述表。"""

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
                    "Section": "Design_Balance",
                    "Variable": factor,
                    "N": count,
                    "Expected_At_Actual_N": expected_actual,
                    "Deviation_From_Actual_Balance": deviation,
                    "Status": status,
                }
            )
    return rows


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
    family: str,
) -> pd.DataFrame:
    """按冻结顺序计算一个确证家族，并在家族内部执行 Holm 校正。"""

    rows: list[dict[str, Any]] = []
    for outcome in outcomes:
        subset = paired[paired["Outcome"] == outcome].sort_values("Participant_ID")
        one_euro = subset[ONE_EURO].to_numpy(dtype=float)
        egoanchor = subset[EGOANCHOR].to_numpy(dtype=float)
        result = paired_result(
            one_euro,
            egoanchor,
            bootstrap_iterations=settings.bootstrap_iterations,
            bootstrap_seed=_outcome_seed(settings.bootstrap_seed, outcome),
            confidence_level=settings.confidence_level,
        )
        rows.append(
            {
                "Family": family,
                "Outcome": outcome,
                **result,
            }
        )
    frame = pd.DataFrame(rows)
    frame["p_Holm"] = holm_adjust(frame["p_raw"])
    frame = frame.drop(columns="p_raw")
    return frame


def _object_descriptions(block_scores: pd.DataFrame) -> pd.DataFrame:
    """生成七个主条目乘三个对象的纯描述统计。

    逐对象结果只用于检查方向一致性。这里故意不调用任何推断函数，也不返回 p 值、
    多重比较或效应量字段，避免读者把低功效的逐对象切片误作确证结论。
    """

    rows: list[dict[str, Any]] = []
    for outcome in PRIMARY_OUTCOMES:
        column = BLOCK_ITEMS[outcome]
        for object_key in OBJECTS:
            subset = block_scores[block_scores["Object_Key"] == object_key]
            pivot = subset.pivot_table(
                index="Participant_ID",
                columns="Condition(保密)",
                values=column,
                aggfunc="first",
            )
            if set(METHODS).issubset(pivot.columns):
                paired = pivot.dropna(subset=list(METHODS))
                one_euro = paired[ONE_EURO].to_numpy(dtype=float)
                egoanchor = paired[EGOANCHOR].to_numpy(dtype=float)
            else:
                one_euro = np.array([], dtype=float)
                egoanchor = np.array([], dtype=float)
            oe_q1, oe_median, oe_q3 = _safe_quartiles(one_euro)
            ea_q1, ea_median, ea_q3 = _safe_quartiles(egoanchor)
            difference_q1, difference_median, difference_q3 = _safe_quartiles(
                np.round(egoanchor - one_euro, decimals=12)
            )
            rows.append(
                {
                    "Outcome": outcome,
                    "Object_Key": object_key,
                    "N": int(len(one_euro)),
                    "OneEuro_Q1": oe_q1,
                    "OneEuro_Median": oe_median,
                    "OneEuro_Q3": oe_q3,
                    "EgoAnchor_Q1": ea_q1,
                    "EgoAnchor_Median": ea_median,
                    "EgoAnchor_Q3": ea_q3,
                    "Difference_Q1": difference_q1,
                    "Difference_Median": difference_median,
                    "Difference_Q3": difference_q3,
                    "Direction": _median_direction(difference_median),
                }
            )
    return pd.DataFrame(rows)


def _safe_quartiles(values: np.ndarray) -> tuple[float, float, float]:
    """对可能为空的数值数组计算四分位数，空数组返回缺失值。"""

    return quartiles(values) if len(values) else (math.nan, math.nan, math.nan)


def _median_direction(difference_median: float) -> str:
    """按 EgoAnchor−One-Euro 的配对差中位数给出描述性方向标签。"""

    if not math.isfinite(difference_median):
        return "not_available"
    if difference_median > 0.0:
        return "EgoAnchor_higher"
    if difference_median < 0.0:
        return "OneEuro_higher"
    return "median_tie"


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


def _choice_results(data: Any) -> pd.DataFrame:
    """解码最终标签选择，并把描述统计与偏好×信任交叉表堆叠为一张表。"""

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
    for method_choice in choices:
        for trust_choice in choices:
            count = int(cross.at[method_choice, trust_choice])
            rows.append(
                {
                    "Measure": "Method_By_Trust",
                    "Category": f"{method_choice} → {trust_choice}",
                    "Count": count,
                }
            )
    return pd.DataFrame(rows)


def _outcome_seed(base_seed: int, outcome: str) -> int:
    """由全局种子和稳定结局键派生跨进程一致的子种子。"""

    digest = hashlib.sha256(f"{base_seed}:{outcome}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


__all__ = ["analyze_scores"]

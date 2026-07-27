"""实验三问卷、对象、操纵检验与绘图数据汇总。"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd

from .contracts import (
    AnalysisTables,
    BLOCK_ITEMS,
    EGOANCHOR,
    METHODS,
    OBJECTS,
    ONE_EURO,
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
from .reader import block_valid_mask, included_participant_ids
from .settings import Exp3Settings


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
    data: Any,
    scores: ScoreData,
    settings: Exp3Settings,
) -> AnalysisTables:
    """计算主分析、量表、描述性结果和绘图长表。"""

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


def _family_results(
    paired: pd.DataFrame,
    outcomes: Iterable[str],
    settings: Exp3Settings,
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


def _object_results(block_scores: pd.DataFrame, settings: Exp3Settings) -> pd.DataFrame:
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


def _manipulation_results(data: Any, settings: Exp3Settings) -> pd.DataFrame:
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

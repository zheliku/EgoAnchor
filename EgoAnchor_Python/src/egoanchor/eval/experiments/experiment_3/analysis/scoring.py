"""实验三原始评分的无损派生与三物体配对汇总。"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

from .contracts import (
    BLOCK_ITEMS,
    EGOANCHOR,
    Exp3Data,
    METHOD_ITEM_COLUMNS,
    METHOD_SCALE_ITEMS,
    METHODS,
    PRIMARY_OUTCOMES,
    REVERSED_TIA_ITEMS,
    SCALE_OUTCOMES,
    ScoreData,
    aq_scale_items,
)
from .reader import block_valid_mask, included_participant_ids, method_record_valid_mask
from ..settings import Exp3Settings


def derive_scores(data: Exp3Data, settings: Exp3Settings) -> ScoreData:
    """从 ``Exp3Data`` 的原始记录派生不改写原值的分析长表。"""

    participants = data.participants
    blocks = data.blocks
    methods = data.methods
    included = included_participant_ids(participants)
    block_scores = _derive_block_scores(blocks, included, settings)
    method_scores = _derive_method_scores(methods, included, settings)
    block_aggregate = _aggregate_block_outcomes(block_scores, settings)
    method_aggregate = _aggregate_method_outcomes(method_scores)
    aggregate_scores = pd.concat((block_aggregate, method_aggregate), ignore_index=True)
    paired_scores = _pair_scores(aggregate_scores)
    reliability_items = _reliability_items(block_scores, method_scores, settings)
    return ScoreData(
        block_scores=block_scores,
        method_scores=method_scores,
        aggregate_scores=aggregate_scores,
        paired_scores=paired_scores,
        reliability_items=reliability_items,
    )


def _derive_block_scores(
    blocks: pd.DataFrame,
    included: frozenset[str],
    settings: Exp3Settings,
) -> pd.DataFrame:
    """筛选有效区块，并在不替换原始条目的前提下计算 AQ 子量表。"""

    selected = blocks.loc[
        blocks["Participant_ID"].astype(str).isin(included) & block_valid_mask(blocks)
    ].copy()
    selected["Participant_ID"] = selected["Participant_ID"].astype(str)
    selected["Condition(保密)"] = selected["Condition(保密)"].astype(str)
    selected["Object_Key"] = selected["Object_Key"].astype(str)
    for column in BLOCK_ITEMS.values():
        selected[column] = pd.to_numeric(selected[column], errors="coerce")
    for scale, items in _aq_item_sets(settings).items():
        selected[scale] = selected.loc[:, items].mean(axis=1, skipna=True)
        selected.loc[selected.loc[:, items].notna().sum(axis=1) != len(items), scale] = np.nan
    return selected


def _derive_method_scores(
    methods: pd.DataFrame,
    included: frozenset[str],
    settings: Exp3Settings,
) -> pd.DataFrame:
    """对 TiA 换向并计算方法级三项量表分。"""

    selected = methods.loc[
        methods["Participant_ID"].astype(str).isin(included) & method_record_valid_mask(methods)
    ].copy()
    selected["Participant_ID"] = selected["Participant_ID"].astype(str)
    selected["Condition(保密)"] = selected["Condition(保密)"].astype(str)
    for column in METHOD_ITEM_COLUMNS:
        selected[column] = pd.to_numeric(selected[column], errors="coerce")
    for column in REVERSED_TIA_ITEMS:
        selected[f"{column}_SCORED"] = 6.0 - selected[column]
    for scale, items in METHOD_SCALE_ITEMS.items():
        scored = tuple(
            f"{item}_SCORED" if item in REVERSED_TIA_ITEMS else item
            for item in items
        )
        minimum = _minimum_items(scale, settings)
        selected[scale] = selected.loc[:, scored].mean(axis=1, skipna=True)
        selected.loc[selected.loc[:, scored].notna().sum(axis=1) < minimum, scale] = np.nan
    return selected


def _aggregate_block_outcomes(block_scores: pd.DataFrame, settings: Exp3Settings) -> pd.DataFrame:
    """按参与者×方法在三个对象上形成每项区块级结局的均值。"""

    outcomes = list(PRIMARY_OUTCOMES) + list(_aq_item_sets(settings))
    if settings.q10_enabled:
        outcomes.append("Q10")
    records: list[dict[str, object]] = []
    for (participant_id, condition), rows in block_scores.groupby(
        ["Participant_ID", "Condition(保密)"], sort=True
    ):
        if len(rows) != settings.objects_per_method or rows["Object_Key"].nunique() != settings.objects_per_method:
            continue
        for outcome in outcomes:
            values = pd.to_numeric(rows[_outcome_column(outcome)], errors="coerce")
            if values.notna().sum() != settings.objects_per_method:
                continue
            records.append(
                {
                    "Participant_ID": str(participant_id),
                    "Condition": str(condition),
                    "Outcome": outcome,
                    "Value": float(values.mean()),
                    "Level": "block",
                }
            )
    return pd.DataFrame(records, columns=("Participant_ID", "Condition", "Outcome", "Value", "Level"))


def _aggregate_method_outcomes(method_scores: pd.DataFrame) -> pd.DataFrame:
    """把每位参与者每种方法的直接量表分转为统一长表。"""

    records: list[dict[str, object]] = []
    for _, values in method_scores.iterrows():
        for outcome in SCALE_OUTCOMES[2:]:
            value = values[outcome]
            if pd.notna(value):
                records.append(
                    {
                        "Participant_ID": str(values["Participant_ID"]),
                    "Condition": str(values["Condition(保密)"]),
                        "Outcome": outcome,
                        "Value": float(value),
                        "Level": "method",
                    }
                )
    return pd.DataFrame(records, columns=("Participant_ID", "Condition", "Outcome", "Value", "Level"))


def _pair_scores(aggregate_scores: pd.DataFrame) -> pd.DataFrame:
    """按参与者×结局形成 EgoAnchor 减 One-Euro 的完整配对表。"""

    if aggregate_scores.empty:
        return pd.DataFrame(columns=("Participant_ID", "Outcome", "One-Euro", "EgoAnchor", "Difference"))
    pivot = aggregate_scores.pivot_table(
        index=["Participant_ID", "Outcome"],
        columns="Condition",
        values="Value",
        aggfunc="first",
    ).reset_index()
    for method in METHODS:
        if method not in pivot:
            pivot[method] = np.nan
    paired = pivot.dropna(subset=list(METHODS)).copy()
    paired["Difference"] = paired[EGOANCHOR] - paired["One-Euro"]
    return paired.loc[:, ["Participant_ID", "Outcome", "One-Euro", "EgoAnchor", "Difference"]]


def _reliability_items(
    block_scores: pd.DataFrame,
    method_scores: pd.DataFrame,
    settings: Exp3Settings,
) -> pd.DataFrame:
    """构造按参与者独立汇总的量表项目矩阵长表。"""

    rows: list[dict[str, object]] = []
    for scale, items in _aq_item_sets(settings).items():
        for (participant_id, condition), group in block_scores.groupby(
            ["Participant_ID", "Condition(保密)"], sort=True
        ):
            if group["Object_Key"].nunique() != settings.objects_per_method:
                continue
            for item in items:
                values = pd.to_numeric(group[_outcome_column(item)], errors="coerce")
                if values.notna().sum() == settings.objects_per_method:
                    rows.append(
                        {
                            "Participant_ID": str(participant_id),
                            "Condition": str(condition),
                            "Scale": scale,
                            "Item": item,
                            "Value": float(values.mean()),
                        }
                    )
    for _, values in method_scores.iterrows():
        condition = str(values["Condition(保密)"])
        participant_id = str(values["Participant_ID"])
        for scale, items in METHOD_SCALE_ITEMS.items():
            for item in items:
                column = f"{item}_SCORED" if item in REVERSED_TIA_ITEMS else item
                value = values[column]
                if pd.notna(value):
                    rows.append(
                        {
                            "Participant_ID": participant_id,
                            "Condition": condition,
                            "Scale": scale,
                            "Item": item,
                            "Value": float(value),
                        }
                    )
    return pd.DataFrame(rows, columns=("Participant_ID", "Condition", "Scale", "Item", "Value"))


def _aq_item_sets(settings: Exp3Settings) -> dict[str, tuple[str, ...]]:
    """按完整或预实验冻结的缩减模式返回 AQ 条目。"""

    return aq_scale_items(settings.aq_mode)


def _minimum_items(scale: str, settings: Exp3Settings) -> int:
    """返回方法级量表的最少可计分条目数。"""

    if scale == "TIA_RC":
        return settings.tia_rc_min_items
    if scale == "TIA_UP":
        return settings.tia_up_min_items
    return settings.stias_min_items


def _outcome_column(outcome: str) -> str:
    """把分析结局键映射到区块派生列。"""

    if outcome in {"AQ_EQ", "AQ_IQ"}:
        return outcome
    return BLOCK_ITEMS[outcome]


__all__ = ["derive_scores"]

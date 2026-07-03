"""尖峰抑制与 policy reject 统计。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


SUMMARY_COLUMNS = [
    "condition",
    "label",
    "n",
    "spike_count",
    "spike_threshold_m",
    "max_translation_error_m",
    "policy_reject_count",
    "top_policy_reasons",
]


def compute_jump_suppression(
    anchor_error_detail: pd.DataFrame,
    *,
    spike_threshold_m: float = 0.05,
) -> pd.DataFrame:
    """按误差尖峰数量和 policy reject 原因汇总跳变抑制效果。"""

    if anchor_error_detail.empty:
        return pd.DataFrame(columns=SUMMARY_COLUMNS)
    rows: list[dict[str, Any]] = []
    for (condition, label), group in anchor_error_detail.groupby(["condition", "label"], sort=True):
        errors = group["translation_error_m"].to_numpy(dtype=float)
        reasons = group["policy_reason"].astype(str)
        actions = group["policy_action"].astype(str).str.lower()
        reject_mask = actions.str.contains("reject", na=False)
        rows.append(
            {
                "condition": condition,
                "label": label,
                "n": int(len(group)),
                "spike_count": int(np.sum(errors > spike_threshold_m)),
                "spike_threshold_m": float(spike_threshold_m),
                "max_translation_error_m": float(np.nanmax(errors)) if errors.size else np.nan,
                "policy_reject_count": int(np.sum(reject_mask)),
                "top_policy_reasons": _top_reasons(reasons[reject_mask]),
            }
        )
    return pd.DataFrame.from_records(rows, columns=SUMMARY_COLUMNS)


def _top_reasons(reasons: pd.Series) -> str:
    """把 reject reason 分布写成紧凑字符串。"""

    if reasons.empty:
        return ""
    counts = reasons.value_counts().head(5)
    return ";".join(f"{reason}:{count}" for reason, count in counts.items())


__all__ = ["compute_jump_suppression"]

"""schema-v2 可靠性评分与接纳行为诊断。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .common import METRIC_GROUP_COLUMNS, iter_metric_groups, require_columns
from .stats import finite_percentile


_SCORE_COLUMNS = (
    "vcd_score",
    "visibility_score",
    "geometry_core_score",
    "color_projection_score",
    "depth_alignment_score",
    "depth_abs_score",
    "depth_struct_score",
    "depth_alpha",
)
"""candidate 顶层连续评分字段。"""

_RENDER_NUMERIC_KEYS = (
    "render_quality_mask_iou",
    "render_quality_area_ratio_score",
    "render_quality_render_visible_ratio",
    "render_quality_observed_visible_ratio",
    "render_quality_render_area_px",
    "render_quality_depth_inlier",
    "render_quality_depth_alignment",
    "render_quality_depth_absolute",
    "render_quality_depth_structural",
    "render_quality_depth_alpha",
    "render_quality_depth_residual_m",
    "render_quality_ms",
)
"""保留在 render_diagnostics 中的数值诊断字段。"""

_CANDIDATE_COLUMNS = [
    "session_id",
    "candidate_id",
    "has_pose",
    *_SCORE_COLUMNS,
    "render_diagnostics",
]
"""可靠性诊断所需的 Python candidate 字段。"""

_ADMISSION_COLUMNS = [
    *METRIC_GROUP_COLUMNS,
    "candidate_id",
    "admission_decision",
    "policy_action",
    "policy_reason",
]
"""可靠性诊断所需的 Unity admission 字段。"""


@dataclass(frozen=True)
class ReliabilityDiagnosticsResult:
    """一组按上下文和 variant 对齐的可靠性诊断表。"""

    summary: pd.DataFrame
    """candidate 评分与渲染诊断的上下文汇总。"""

    vcd_histogram: pd.DataFrame
    """按上下文和 variant 统计的 VCD 分数直方图。"""

    admission_distribution: pd.DataFrame
    """按 candidate 统计的 admission decision/action/reason 分布。"""


def compute_reliability_diagnostics(
    python_candidates: pd.DataFrame,
    unity_admission: pd.DataFrame,
    *,
    histogram_bins: int = 10,
) -> ReliabilityDiagnosticsResult:
    """连接 candidate 与 admission，生成 schema-v2 可靠性诊断。

    Python candidate 本身不带实验上下文，因此先通过稳定 ``candidate_id`` 与
    Unity admission 连接。一个 candidate 可被多个 variant 消费，连接后的每个
    variant 都独立汇总，但 admission 行不会按 render tick 重复计数。
    """

    if histogram_bins <= 0:
        raise ValueError("histogram_bins 必须大于 0。")
    require_columns(python_candidates, _CANDIDATE_COLUMNS, table_name="python_candidates")
    require_columns(unity_admission, _ADMISSION_COLUMNS, table_name="unity_admission")

    joined = _join_candidates(python_candidates, unity_admission)
    return ReliabilityDiagnosticsResult(
        summary=_summarize_candidates(joined),
        vcd_histogram=_build_vcd_histogram(joined, bins=histogram_bins),
        admission_distribution=_build_admission_distribution(joined),
    )


def _join_candidates(
    python_candidates: pd.DataFrame,
    unity_admission: pd.DataFrame,
) -> pd.DataFrame:
    """按稳定 candidate 主键连接两端数据，并拒绝含糊的重复记录。"""

    candidate_keys = ["session_id", "candidate_id"]
    if python_candidates.duplicated(candidate_keys).any():
        raise ValueError("python_candidates 包含重复的 session_id + candidate_id。")

    admission_keys = ["session_id", "candidate_id", "variant_id"]
    if unity_admission.duplicated(admission_keys).any():
        raise ValueError(
            "unity_admission 包含重复的 session_id + candidate_id + variant_id。"
        )

    admission = unity_admission.loc[:, _ADMISSION_COLUMNS].copy()
    candidates = python_candidates.loc[:, _CANDIDATE_COLUMNS].copy()
    joined = admission.merge(
        candidates,
        on=candidate_keys,
        how="left",
        validate="many_to_one",
        indicator=True,
    )
    missing = sorted(
        joined.loc[joined["_merge"] != "both", "candidate_id"].astype(str).unique()
    )
    if missing:
        raise ValueError(f"unity_admission 引用了未知 candidate_id: {missing}")
    return joined.drop(columns="_merge")


def _summarize_candidates(joined: pd.DataFrame) -> pd.DataFrame:
    """按公共上下文键汇总连续评分和嵌套渲染诊断。"""

    rows: list[dict[str, Any]] = []
    for group_keys, group in iter_metric_groups(joined):
        row: dict[str, Any] = {
            **group_keys,
            "candidate_count": int(group["candidate_id"].nunique()),
            "has_pose_count": int(group["has_pose"].fillna(False).astype(bool).sum()),
        }
        for column in _SCORE_COLUMNS:
            row.update(_numeric_summary(group[column], prefix=column))

        render_diagnostics = group["render_diagnostics"]
        row["render_quality_evaluated_count"] = int(
            render_diagnostics.map(
                lambda value: bool(value.get("render_quality_evaluated", False))
                if isinstance(value, Mapping)
                else False
            ).sum()
        )
        row["render_quality_valid_count"] = int(
            render_diagnostics.map(
                lambda value: value.get("render_quality_status") == "valid"
                if isinstance(value, Mapping)
                else False
            ).sum()
        )
        for key in _RENDER_NUMERIC_KEYS:
            row.update(_numeric_summary(_render_values(render_diagnostics, key), prefix=key))
        rows.append(row)

    return pd.DataFrame.from_records(rows, columns=_summary_columns())


def _build_vcd_histogram(joined: pd.DataFrame, *, bins: int) -> pd.DataFrame:
    """按上下文和 variant 生成 ``[0, 1]`` VCD 候选直方图。"""

    columns = [*METRIC_GROUP_COLUMNS, "bin_left", "bin_right", "candidate_count"]
    rows: list[dict[str, Any]] = []
    for group_keys, group in iter_metric_groups(joined):
        scores = _finite_values(group["vcd_score"])
        if scores.size == 0:
            continue
        if ((scores < 0.0) | (scores > 1.0)).any():
            raise ValueError("vcd_score 必须位于 [0, 1]，不得在指标阶段裁剪越界值。")
        counts, edges = np.histogram(scores, bins=bins, range=(0.0, 1.0))
        rows.extend(
            {
                **group_keys,
                "bin_left": float(edges[index]),
                "bin_right": float(edges[index + 1]),
                "candidate_count": int(count),
            }
            for index, count in enumerate(counts)
        )
    return pd.DataFrame.from_records(rows, columns=columns)


def _build_admission_distribution(joined: pd.DataFrame) -> pd.DataFrame:
    """按唯一 candidate 汇总 admission 决策，不使用 render tick。"""

    decision_columns = ["admission_decision", "policy_action", "policy_reason"]
    columns = [*METRIC_GROUP_COLUMNS, *decision_columns, "candidate_count", "candidate_share"]
    rows: list[dict[str, Any]] = []
    for group_keys, group in iter_metric_groups(joined):
        candidate_count = int(group["candidate_id"].nunique())
        distributions = (
            group.groupby(decision_columns, dropna=False, sort=True)["candidate_id"]
            .nunique()
            .reset_index(name="candidate_count")
        )
        for _, distribution in distributions.iterrows():
            count = int(distribution["candidate_count"])
            rows.append(
                {
                    **group_keys,
                    **{column: str(distribution[column]) for column in decision_columns},
                    "candidate_count": count,
                    "candidate_share": (
                        float(count / candidate_count) if candidate_count else np.nan
                    ),
                }
            )
    return pd.DataFrame.from_records(rows, columns=columns)


def _numeric_summary(values: pd.Series, *, prefix: str) -> dict[str, Any]:
    """返回连续诊断量的有效计数、最小值、中位数和 P95。"""

    finite = _finite_values(values)
    return {
        f"{prefix}_count": int(finite.size),
        f"{prefix}_min": float(np.min(finite)) if finite.size else np.nan,
        f"{prefix}_p50": finite_percentile(finite, 50),
        f"{prefix}_p95": finite_percentile(finite, 95),
    }


def _finite_values(values: pd.Series) -> np.ndarray:
    """把 Series 转为有限浮点数组；``None`` 和非数值值会被排除。"""

    numeric = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    return numeric[np.isfinite(numeric)]


def _render_values(diagnostics: pd.Series, key: str) -> pd.Series:
    """从每条 candidate 的 render_diagnostics 中读取一个数值字段。"""

    return diagnostics.map(
        lambda value: value.get(key) if isinstance(value, Mapping) else None
    )


def _summary_columns() -> list[str]:
    """返回固定的可靠性汇总列顺序。"""

    columns = [*METRIC_GROUP_COLUMNS, "candidate_count", "has_pose_count"]
    for prefix in (*_SCORE_COLUMNS, *_RENDER_NUMERIC_KEYS):
        columns.extend(
            [
                f"{prefix}_count",
                f"{prefix}_min",
                f"{prefix}_p50",
                f"{prefix}_p95",
            ]
        )
    columns.extend(["render_quality_evaluated_count", "render_quality_valid_count"])
    return columns


__all__ = ["ReliabilityDiagnosticsResult", "compute_reliability_diagnostics"]

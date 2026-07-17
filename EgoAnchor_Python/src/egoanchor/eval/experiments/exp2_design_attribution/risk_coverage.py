"""基于平台参考误差的 VCD risk-coverage 与 AURC 诊断。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from egoanchor.eval.metrics import is_pose_vector, pose_error, require_columns

from .contract import BASELINE_VARIANT, EXPERIMENT_ID, SOURCE_EXPERIMENT_ID


RISK_GROUP_COLUMNS = (
    "session_id",
    "experiment_id",
    "scenario_id",
    "trial_id",
    "event_id",
    "condition_id",
)
"""AURC 的最小分析单元；候选行不得跨 trial/event 汇成伪样本。"""

CURVE_COLUMNS = (
    *RISK_GROUP_COLUMNS,
    "candidate_count",
    "accepted_candidates",
    "coverage",
    "threshold",
    "selective_risk_mm",
)
"""risk-coverage 曲线的稳定列顺序。"""

AURC_COLUMNS = (
    *RISK_GROUP_COLUMNS,
    "candidate_count",
    "threshold_count",
    "aurc_mm",
)
"""trial/event 单元 AURC 表的稳定列顺序。"""

SUMMARY_COLUMNS = (
    "session_id",
    "unit_count",
    "candidate_count",
    "aurc_mm_median",
    "aurc_mm_iqr",
    "baseline_admission_count",
    "eligible_candidate_count",
    "excluded_candidate_count",
    "excluded_no_pose_count",
    "excluded_no_aligned_raw_count",
    "excluded_invalid_reference_count",
    "excluded_incomplete_context_count",
)
"""单元 AURC、eligible 数量和各排除原因的 session 级汇总。"""


@dataclass(frozen=True)
class VcdRiskCoverageResult:
    """VCD 评分风险判别性诊断的三层固定输出。"""

    curve: pd.DataFrame
    """每个 trial/event 单元按分数阈值诱导的 risk-coverage 曲线。"""

    aurc: pd.DataFrame
    """每个 trial/event 单元的 AURC，单位为毫米。"""

    summary: pd.DataFrame
    """对单元 AURC 做中位数/IQR 的 session 级汇总。"""


def compute_vcd_risk_coverage(
    candidates: pd.DataFrame,
    admissions: pd.DataFrame,
    references: pd.DataFrame,
) -> VcdRiskCoverageResult:
    """用完整 EgoAnchor 的 aligned raw 与平台参考误差计算 VCD AURC。

    VCD 分数只用于诱导候选接纳阈值。risk 固定为同 ``frame_id`` 下
    capture-time aligned raw 相对平台参考的平移误差，单位为毫米；不得用
    VCD 的组成分数代替 risk，也不得跨 trial/event 汇总候选行进行推断。
    """

    _validate_columns(candidates, admissions, references)
    baseline = admissions.loc[
        (admissions["experiment_id"].astype(str) == SOURCE_EXPERIMENT_ID)
        & (admissions["variant_label"].astype(str) == BASELINE_VARIANT)
    ].copy()
    if baseline.empty:
        raise ValueError("任务 1--5 的 unity_admission 缺少完整 EgoAnchor 候选，无法计算 VCD risk。")

    _require_unique(candidates, ["session_id", "candidate_id"], "python_candidates")
    _require_unique(baseline, ["session_id", "candidate_id"], "exp2 EgoAnchor admission")
    _require_unique(references, ["session_id", "frame_id"], "unity_reference")

    candidate_view = candidates[
        ["session_id", "candidate_id", "frame_id", "has_pose", "vcd_score"]
    ].rename(columns={"frame_id": "candidate_frame_id", "vcd_score": "candidate_vcd_score"})
    joined = baseline.merge(
        candidate_view,
        on=["session_id", "candidate_id"],
        how="left",
        validate="one_to_one",
        indicator="candidate_match",
    )
    missing_candidates = sorted(
        joined.loc[joined["candidate_match"] != "both", "candidate_id"].astype(str).unique()
    )
    if missing_candidates:
        raise ValueError(f"exp2 EgoAnchor admission 引用了未知 candidate_id：{missing_candidates}")
    if not (
        pd.to_numeric(joined["frame_id"], errors="coerce")
        == pd.to_numeric(joined["candidate_frame_id"], errors="coerce")
    ).all():
        raise ValueError("candidate 与 admission 的 frame_id 不一致。")

    reference_view = references[
        [
            "session_id",
            "frame_id",
            "reference_pose_valid",
            "reference_pos",
            "reference_rot",
        ]
    ]
    joined = joined.drop(columns="candidate_match").merge(
        reference_view,
        on=["session_id", "frame_id"],
        how="left",
        validate="many_to_one",
        indicator="reference_match",
    )
    _validate_joined_rows(joined)
    detail, eligibility = _compute_candidate_risk(joined)
    if detail.empty:
        audit = (
            eligibility.iloc[0].to_dict()
            if len(eligibility) == 1
            else eligibility.to_dict(orient="records")
        )
        raise ValueError(f"VCD risk 没有 eligible 候选；排除统计={audit}")
    curve, aurc = _compute_group_curves(detail)
    return VcdRiskCoverageResult(
        curve=curve,
        aurc=aurc,
        summary=_summarize_aurc(aurc, eligibility),
    )


def _validate_columns(
    candidates: pd.DataFrame,
    admissions: pd.DataFrame,
    references: pd.DataFrame,
) -> None:
    """检查三张 schema-v2 输入表的风险计算契约。"""

    require_columns(
        candidates,
        ("session_id", "candidate_id", "frame_id", "has_pose", "vcd_score"),
        table_name="python_candidates",
    )
    require_columns(
        admissions,
        (
            *RISK_GROUP_COLUMNS,
            "candidate_id",
            "frame_id",
            "variant_label",
            "has_aligned_raw",
            "aligned_raw_pos",
            "aligned_raw_rot",
            "vcd_score",
        ),
        table_name="unity_admission",
    )
    require_columns(
        references,
        (
            "session_id",
            "frame_id",
            "reference_pose_valid",
            "reference_pos",
            "reference_rot",
        ),
        table_name="unity_reference",
    )


def _require_unique(frame: pd.DataFrame, keys: list[str], table_name: str) -> None:
    """拒绝会把一个候选或平台参考重复计入曲线的主键。"""

    if frame.duplicated(keys).any():
        raise ValueError(f"{table_name} 包含重复主键：{' + '.join(keys)}")


def _validate_joined_rows(joined: pd.DataFrame) -> None:
    """校验分数与布尔字段类型；预期的不可用 pose 留给 eligibility 统计。"""

    candidate_scores = pd.to_numeric(joined["candidate_vcd_score"], errors="coerce")
    admission_scores = pd.to_numeric(joined["vcd_score"], errors="coerce")
    if not np.isfinite(candidate_scores.to_numpy(dtype=float)).all():
        raise ValueError("python_candidates.vcd_score 必须是有限数值。")
    if not candidate_scores.between(0.0, 1.0, inclusive="both").all():
        raise ValueError("python_candidates.vcd_score 必须位于 [0, 1]，不得裁剪越界值。")
    if not np.isfinite(admission_scores.to_numpy(dtype=float)).all():
        raise ValueError("unity_admission.vcd_score 必须是有限数值。")
    if not admission_scores.between(0.0, 1.0, inclusive="both").all():
        raise ValueError("unity_admission.vcd_score 必须位于 [0, 1]，不得裁剪越界值。")
    if not np.allclose(candidate_scores, admission_scores, rtol=0.0, atol=1e-6):
        raise ValueError("candidate 与 admission 的 vcd_score 不一致。")

    _require_bool(joined, "has_pose")
    _require_bool(joined, "has_aligned_raw")
    reference_matches = joined["reference_match"].astype(str).eq("both")
    _require_bool(joined.loc[reference_matches], "reference_pose_valid")


def _require_bool(frame: pd.DataFrame, column: str) -> None:
    """要求已存在的 schema 布尔列使用真正的布尔值。"""

    valid = frame[column].map(lambda value: isinstance(value, (bool, np.bool_)))
    if not valid.all():
        raise ValueError(f"VCD risk 要求 {column} 使用真正的布尔值。")


def _valid_pose(position: object, rotation: object) -> bool:
    """检查位置、四元数形状与非零旋转范数。"""

    return (
        is_pose_vector(position, 3)
        and is_pose_vector(rotation, 4)
        and float(np.linalg.norm(np.asarray(rotation, dtype=float))) > 1e-12
    )


def _compute_candidate_risk(
    joined: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """筛选 eligible 候选并返回逐 session 的显式排除统计。"""

    detail = joined.copy()
    context_complete = pd.Series(True, index=detail.index)
    for column in RISK_GROUP_COLUMNS:
        context_complete &= (
            detail[column].notna() & detail[column].astype(str).str.strip().ne("")
        )
    has_pose = detail["has_pose"].astype(bool)
    has_aligned = detail["has_aligned_raw"].astype(bool) & detail.apply(
        lambda row: _valid_pose(row["aligned_raw_pos"], row["aligned_raw_rot"]),
        axis=1,
    )
    has_reference = (
        detail["reference_match"].astype(str).eq("both")
        & detail["reference_pose_valid"].fillna(False).astype(bool)
        & detail.apply(
            lambda row: _valid_pose(row["reference_pos"], row["reference_rot"]),
            axis=1,
        )
    )
    eligible = has_pose & has_aligned & has_reference & context_complete

    eligibility_rows: list[dict[str, object]] = []
    for session_id, indexes in detail.groupby("session_id", dropna=False, sort=True).groups.items():
        selected = pd.Index(indexes)
        selected_eligible = eligible.loc[selected]
        eligibility_rows.append(
            {
                "session_id": session_id,
                "baseline_admission_count": int(len(selected)),
                "eligible_candidate_count": int(selected_eligible.sum()),
                "excluded_candidate_count": int((~selected_eligible).sum()),
                "excluded_no_pose_count": int((~has_pose.loc[selected]).sum()),
                "excluded_no_aligned_raw_count": int((~has_aligned.loc[selected]).sum()),
                "excluded_invalid_reference_count": int((~has_reference.loc[selected]).sum()),
                "excluded_incomplete_context_count": int((~context_complete.loc[selected]).sum()),
            }
        )

    detail = detail.loc[eligible].copy()
    detail["experiment_id"] = EXPERIMENT_ID
    risks: list[float] = []
    for _, row in detail.iterrows():
        translation_m, _ = pose_error(
            row["reference_pos"],
            row["reference_rot"],
            row["aligned_raw_pos"],
            row["aligned_raw_rot"],
        )
        risks.append(translation_m * 1000.0)
    detail["score"] = pd.to_numeric(detail["candidate_vcd_score"], errors="raise")
    detail["risk_mm"] = risks
    eligibility_columns = (
        "session_id",
        "baseline_admission_count",
        "eligible_candidate_count",
        "excluded_candidate_count",
        "excluded_no_pose_count",
        "excluded_no_aligned_raw_count",
        "excluded_invalid_reference_count",
        "excluded_incomplete_context_count",
    )
    return detail, pd.DataFrame.from_records(
        eligibility_rows,
        columns=eligibility_columns,
    )


def _compute_group_curves(detail: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """逐 trial/event 单元构造并列阈值安全的曲线与 AURC。"""

    curve_rows: list[dict[str, object]] = []
    aurc_rows: list[dict[str, object]] = []
    grouped = detail.groupby(list(RISK_GROUP_COLUMNS), dropna=False, sort=True)
    for values, group in grouped:
        context = dict(zip(RISK_GROUP_COLUMNS, values, strict=True))
        candidate_count = int(group["candidate_id"].nunique())
        previous_coverage = 0.0
        aurc_mm = 0.0
        thresholds = sorted(group["score"].unique(), reverse=True)
        for threshold in thresholds:
            accepted = group.loc[group["score"] >= threshold, "risk_mm"]
            coverage = float(len(accepted) / candidate_count)
            selective_risk_mm = float(accepted.mean())
            aurc_mm += selective_risk_mm * (coverage - previous_coverage)
            previous_coverage = coverage
            curve_rows.append(
                {
                    **context,
                    "candidate_count": candidate_count,
                    "accepted_candidates": int(len(accepted)),
                    "coverage": coverage,
                    "threshold": float(threshold),
                    "selective_risk_mm": selective_risk_mm,
                }
            )
        aurc_rows.append(
            {
                **context,
                "candidate_count": candidate_count,
                "threshold_count": len(thresholds),
                "aurc_mm": aurc_mm,
            }
        )
    return (
        pd.DataFrame.from_records(curve_rows, columns=CURVE_COLUMNS),
        pd.DataFrame.from_records(aurc_rows, columns=AURC_COLUMNS),
    )


def _summarize_aurc(
    aurc: pd.DataFrame,
    eligibility: pd.DataFrame,
) -> pd.DataFrame:
    """合并 trial/event AURC 与逐 session eligibility 审计统计。"""

    aurc_rows: list[dict[str, object]] = []
    for session_id, group in aurc.groupby("session_id", dropna=False, sort=True):
        values = group["aurc_mm"].to_numpy(dtype=float)
        aurc_rows.append(
            {
                "session_id": session_id,
                "unit_count": int(len(group)),
                "candidate_count": int(group["candidate_count"].sum()),
                "aurc_mm_median": float(np.median(values)),
                "aurc_mm_iqr": float(np.quantile(values, 0.75) - np.quantile(values, 0.25)),
            }
        )
    aurc_summary = pd.DataFrame.from_records(
        aurc_rows,
        columns=SUMMARY_COLUMNS[:5],
    )
    if eligibility.empty:
        return pd.DataFrame(columns=SUMMARY_COLUMNS)
    merged = eligibility.merge(
        aurc_summary,
        on="session_id",
        how="left",
        validate="one_to_one",
    )
    merged["unit_count"] = merged["unit_count"].fillna(0).astype(int)
    merged["candidate_count"] = merged["candidate_count"].fillna(0).astype(int)
    return merged.loc[:, SUMMARY_COLUMNS]


__all__ = [
    "AURC_COLUMNS",
    "CURVE_COLUMNS",
    "RISK_GROUP_COLUMNS",
    "SUMMARY_COLUMNS",
    "VcdRiskCoverageResult",
    "compute_vcd_risk_coverage",
]

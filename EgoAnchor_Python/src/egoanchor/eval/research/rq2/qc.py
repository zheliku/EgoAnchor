"""RQ2 trial 契约与数据覆盖审计。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .contract import REQUIRED_VARIANTS, RQ2_CONDITIONS, RQ2Config
from .trajectory import (
    active_at_times,
    active_duration_seconds,
    reference_valid_mask,
    unique_trial_frames,
)


AUDIT_COLUMNS = [
    "session_id",
    "condition",
    "rq2_trial_id",
    "legal_condition",
    "required_variants_present",
    "pair_complete_fraction",
    "duplicate_variant_row_count",
    "unique_primary",
    "primary_label",
    "target_speed_consistent",
    "target_metadata_valid",
    "gt_coverage",
    "active_frame_count",
    "active_duration_s",
    "active_capture_count",
    "active_source_count",
    "raw_source_yield",
    "accepted",
    "issues",
]
"""每个 session × trial 的正式数据审计字段。"""


SESSION_AUDIT_COLUMNS = [
    "session_id",
    "capture_dropped_rows",
    "output_dropped_rows",
    "required_variants_declared",
    "freshness_fields_present",
    "dynamic_keep_alive_rows",
    "accepted",
    "issues",
]
"""录制会话级日志完整性审计字段。"""


DESIGN_AUDIT_COLUMNS = [
    "level",
    "session_id",
    "condition",
    "accepted_trials",
    "required_trials",
    "sessions_meeting_requirement",
    "required_sessions",
    "accepted",
    "issues",
]
"""正式重复次数与独立录制会话覆盖审计字段。"""


def compute_trial_audit(
    output: pd.DataFrame,
    source: pd.DataFrame,
    capture: pd.DataFrame | None,
    *,
    session_id: str,
    config: RQ2Config,
) -> pd.DataFrame:
    """检查正式 RQ2 trial 的变体、目标、GT、运动和 source 覆盖。"""

    if output.empty or not {"rq2_condition", "rq2_trial_id"}.issubset(output.columns):
        return pd.DataFrame(columns=AUDIT_COLUMNS)
    rows: list[dict[str, object]] = []
    trial_id = pd.to_numeric(output["rq2_trial_id"], errors="coerce")
    trials = output[trial_id > 0]
    for (condition, current_trial), group in trials.groupby(
        ["rq2_condition", "rq2_trial_id"], sort=True
    ):
        frames = unique_trial_frames(group)
        tick_key = "tick_index" if "tick_index" in group.columns else "render_mono_ms"
        expected = set(REQUIRED_VARIANTS)
        per_tick = group.groupby(tick_key, sort=False)
        pair_flags = per_tick["label"].apply(
            lambda values: len(values) == 2 and set(values.astype(str)) == expected
        )
        duplicate_rows = int(
            sum(max(0, len(values) - len(set(values.astype(str)))) for _, values in per_tick["label"])
        )
        primary_counts = per_tick["is_primary"].apply(
            lambda values: int(values.fillna(False).astype(bool).sum())
        )
        primary_labels = sorted(
            group.loc[group["is_primary"].fillna(False).astype(bool), "label"]
            .astype(str)
            .unique()
            .tolist()
        )
        unique_primary = bool(
            len(primary_labels) == 1 and len(primary_counts) > 0 and (primary_counts == 1).all()
        )
        target_consistent = _target_consistent(frames)
        target_valid = _target_metadata_valid(str(condition), frames)
        gt_valid = reference_valid_mask(frames)
        gt_coverage = float(gt_valid.mean()) if len(frames) else np.nan
        active_frames = frames[frames["active_motion"].fillna(False).astype(bool)]
        active_duration = active_duration_seconds(frames)
        active_sources = source[
            source["session_id"].astype(str).eq(str(session_id))
            & source["condition"].astype(str).eq(str(condition))
            & pd.to_numeric(source["rq2_trial_id"], errors="coerce").eq(current_trial)
            & source["active_motion"].fillna(False).astype(bool)
        ] if not source.empty else source
        active_capture_count = _active_capture_count(
            capture,
            output,
            str(condition),
            int(current_trial),
        )
        source_count = int(active_sources["source_frame_id"].nunique()) if not active_sources.empty else 0
        source_yield = (
            float(source_count / active_capture_count) if active_capture_count > 0 else np.nan
        )
        legal = str(condition) in RQ2_CONDITIONS
        variants_present = expected.issubset(set(group["label"].astype(str)))
        pair_fraction = float(pair_flags.mean()) if len(pair_flags) else 0.0
        issues: list[str] = []
        _issue(issues, not legal, "illegal_condition")
        _issue(issues, not variants_present, "missing_required_variant")
        _issue(issues, pair_fraction < 1.0, "incomplete_variant_tick")
        _issue(issues, duplicate_rows > 0, "duplicate_variant_row")
        _issue(issues, not unique_primary, "invalid_primary")
        _issue(issues, not target_consistent, "target_speed_changed")
        _issue(issues, not target_valid, "invalid_target_metadata")
        _issue(issues, not np.isfinite(gt_coverage) or gt_coverage < 0.95, "low_gt_coverage")
        _issue(
            issues,
            active_duration < config.min_active_duration_s,
            "insufficient_active_motion",
        )
        _issue(issues, source_count <= 0, "no_active_source")
        rows.append(
            {
                "session_id": str(session_id),
                "condition": str(condition),
                "rq2_trial_id": int(current_trial),
                "legal_condition": legal,
                "required_variants_present": variants_present,
                "pair_complete_fraction": pair_fraction,
                "duplicate_variant_row_count": duplicate_rows,
                "unique_primary": unique_primary,
                "primary_label": primary_labels[0] if len(primary_labels) == 1 else "",
                "target_speed_consistent": target_consistent,
                "target_metadata_valid": target_valid,
                "gt_coverage": gt_coverage,
                "active_frame_count": int(len(active_frames)),
                "active_duration_s": active_duration,
                "active_capture_count": int(active_capture_count),
                "active_source_count": source_count,
                "raw_source_yield": source_yield,
                "accepted": len(issues) == 0,
                "issues": ";".join(issues),
            }
        )
    return pd.DataFrame.from_records(rows, columns=AUDIT_COLUMNS)


def compute_session_audit(
    output: pd.DataFrame,
    manifest: dict[str, object],
    *,
    session_id: str,
) -> pd.DataFrame:
    """拒收发生丢行、变体声明错误或使用动态 keep-alive 的录制会话。"""

    stats = manifest.get("log_writer_stats")
    has_stats = isinstance(stats, dict)
    stats = stats if has_stats else {}
    capture_dropped = _nonnegative_int(stats.get("capture_dropped_rows"), default=-1)
    output_dropped = _nonnegative_int(stats.get("output_dropped_rows"), default=-1)
    labels = manifest.get("variant_labels")
    declared = (
        isinstance(labels, list)
        and len(labels) == len(REQUIRED_VARIANTS)
        and set(str(label) for label in labels) == set(REQUIRED_VARIANTS)
    )
    has_freshness_fields = {
        "gt_pose_fresh",
        "gt_pose_keep_alive",
        "gt_pose_fresh_age_ms",
    }.issubset(output.columns)
    dynamic_rows = output[
        output.get("rq2_condition", pd.Series("none", index=output.index))
        .fillna("none")
        .astype(str)
        .isin(RQ2_CONDITIONS)
        & (
            pd.to_numeric(
                output.get("rq2_trial_id", pd.Series(-1, index=output.index)),
                errors="coerce",
            )
            > 0
        )
    ]
    keep_alive = dynamic_rows.get("gt_pose_keep_alive", False)
    keep_alive_count = (
        int(keep_alive.fillna(False).astype(bool).sum())
        if isinstance(keep_alive, pd.Series)
        else 0
    )
    fresh_age = pd.to_numeric(
        dynamic_rows.get("gt_pose_fresh_age_ms", pd.Series(dtype=float)),
        errors="coerce",
    )
    freshness_fields = bool(
        has_freshness_fields
        and not dynamic_rows.empty
        and np.isfinite(fresh_age.to_numpy(dtype=float)).any()
    )
    issues: list[str] = []
    _issue(issues, not has_stats, "missing_log_writer_stats")
    _issue(issues, capture_dropped != 0, "capture_log_rows_dropped")
    _issue(issues, output_dropped != 0, "output_log_rows_dropped")
    _issue(issues, not declared, "invalid_manifest_variants")
    _issue(issues, not freshness_fields, "missing_gt_freshness_fields")
    _issue(issues, keep_alive_count > 0, "dynamic_gt_keep_alive")
    return pd.DataFrame.from_records(
        [
            {
                "session_id": str(session_id),
                "capture_dropped_rows": capture_dropped,
                "output_dropped_rows": output_dropped,
                "required_variants_declared": declared,
                "freshness_fields_present": freshness_fields,
                "dynamic_keep_alive_rows": keep_alive_count,
                "accepted": len(issues) == 0,
                "issues": ";".join(issues),
            }
        ],
        columns=SESSION_AUDIT_COLUMNS,
    )


def compute_design_audit(
    trial_audit: pd.DataFrame,
    session_ids: list[str],
    config: RQ2Config,
) -> pd.DataFrame:
    """核对每会话每类试次数量，并验证跨会话覆盖是否达到预定设计。"""

    rows: list[dict[str, object]] = []
    sessions = sorted(set(str(value) for value in session_ids))
    accepted = (
        trial_audit[trial_audit["accepted"].fillna(False).astype(bool)]
        if not trial_audit.empty
        else trial_audit
    )
    counts: dict[tuple[str, str], int] = {}
    for session in sessions:
        for condition in RQ2_CONDITIONS:
            count = int(
                accepted[
                    accepted["session_id"].astype(str).eq(session)
                    & accepted["condition"].astype(str).eq(condition)
                ]["rq2_trial_id"].nunique()
            ) if not accepted.empty else 0
            counts[(session, condition)] = count
            ok = count >= config.min_trials_per_condition
            rows.append(
                {
                    "level": "session_condition",
                    "session_id": session,
                    "condition": condition,
                    "accepted_trials": count,
                    "required_trials": config.min_trials_per_condition,
                    "sessions_meeting_requirement": int(ok),
                    "required_sessions": config.min_sessions,
                    "accepted": ok,
                    "issues": "" if ok else "insufficient_accepted_trials",
                }
            )
    condition_ok: list[bool] = []
    for condition in RQ2_CONDITIONS:
        meeting = sum(
            counts.get((session, condition), 0) >= config.min_trials_per_condition
            for session in sessions
        )
        ok = meeting >= config.min_sessions
        condition_ok.append(ok)
        rows.append(
            {
                "level": "condition",
                "session_id": "all",
                "condition": condition,
                "accepted_trials": int(
                    sum(counts.get((session, condition), 0) for session in sessions)
                ),
                "required_trials": config.min_trials_per_condition,
                "sessions_meeting_requirement": meeting,
                "required_sessions": config.min_sessions,
                "accepted": ok,
                "issues": "" if ok else "insufficient_sessions",
            }
        )
    study_ok = bool(condition_ok) and all(condition_ok)
    rows.append(
        {
            "level": "study",
            "session_id": "all",
            "condition": "all",
            "accepted_trials": int(sum(counts.values())),
            "required_trials": config.min_trials_per_condition,
            "sessions_meeting_requirement": len(sessions),
            "required_sessions": config.min_sessions,
            "accepted": study_ok,
            "issues": "" if study_ok else "incomplete_formal_design",
        }
    )
    return pd.DataFrame.from_records(rows, columns=DESIGN_AUDIT_COLUMNS)


def accepted_trial_keys(audit: pd.DataFrame) -> set[tuple[str, int]]:
    """返回通过审计的 ``condition × trial`` 键。"""

    if audit.empty:
        return set()
    accepted = audit[audit["accepted"].fillna(False).astype(bool)]
    return {
        (str(row.condition), int(row.rq2_trial_id)) for row in accepted.itertuples()
    }


def _target_consistent(frames: pd.DataFrame) -> bool:
    """检查 trial 内目标速度元数据是否保持不变。"""

    return all(
        len(_finite_unique(frames.get(column))) <= 1
        for column in (
            "rq2_target_linear_speed_m_s",
            "rq2_target_angular_speed_deg_s",
        )
    )


def _target_metadata_valid(condition: str, frames: pd.DataFrame) -> bool:
    """检查平移和旋转 trial 的目标速度通道是否匹配。"""

    linear = _finite_unique(frames.get("rq2_target_linear_speed_m_s"))
    angular = _finite_unique(frames.get("rq2_target_angular_speed_deg_s"))
    if condition == "rotation":
        return len(linear) == 0 and len(angular) == 1 and angular[0] >= 0.0
    return len(linear) == 1 and linear[0] >= 0.0 and len(angular) == 0


def _finite_unique(values: object) -> list[float]:
    """返回数值序列中按容差去重的有限值。"""

    if values is None:
        return []
    numeric = np.asarray(pd.to_numeric(values, errors="coerce"), dtype=float)
    numeric = np.sort(numeric[np.isfinite(numeric)])
    unique: list[float] = []
    for value in numeric:
        if not unique or not np.isclose(value, unique[-1], rtol=1e-6, atol=1e-9):
            unique.append(float(value))
    return unique


def _active_capture_count(
    capture: pd.DataFrame | None,
    output: pd.DataFrame,
    condition: str,
    trial_id: int,
) -> int:
    """统计 active-motion 时间内成功发布的 capture frame。"""

    if capture is None or capture.empty or "capture_mono_ms" not in capture.columns:
        return 0
    times = pd.to_numeric(capture["capture_mono_ms"], errors="coerce").to_numpy(dtype=float)
    active = active_at_times(output, condition, trial_id, times)
    published = capture.get("publish_succeeded", True)
    if not isinstance(published, pd.Series):
        published = pd.Series(True, index=capture.index)
    finite = np.isfinite(times)
    return int(np.sum(active & finite & published.fillna(False).to_numpy(dtype=bool)))


def _issue(issues: list[str], condition: bool, code: str) -> None:
    """按条件追加稳定的审计问题代码。"""

    if condition:
        issues.append(code)


def _nonnegative_int(value: object, *, default: int) -> int:
    """读取 manifest 中的非负整数；缺失或非法时返回哨兵。"""

    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number >= 0 else default


__all__ = [
    "AUDIT_COLUMNS",
    "DESIGN_AUDIT_COLUMNS",
    "SESSION_AUDIT_COLUMNS",
    "accepted_trial_keys",
    "compute_design_audit",
    "compute_session_audit",
    "compute_trial_audit",
]

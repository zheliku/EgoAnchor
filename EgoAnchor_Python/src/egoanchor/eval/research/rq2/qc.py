"""RQ2 双任务日志的会话与试次质量审计。"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from .contract import REQUIRED_VARIANTS, RQ2_CONDITIONS, RQ2Config
from .trajectory import (
    active_duration_seconds,
    reference_valid_mask,
    unique_trial_frames,
)


SESSION_AUDIT_COLUMNS = [
    "session_id",
    "output_row_count",
    "render_tick_count",
    "declared_variants",
    "logged_variants",
    "motion_tasks",
    "capture_dropped_rows",
    "output_dropped_rows",
    "freshness_fields_present",
    "dynamic_keep_alive_tick_count",
    "accepted",
    "issues",
]

TRIAL_AUDIT_COLUMNS = [
    "session_id",
    "condition",
    "rq2_trial_id",
    "render_tick_count",
    "active_frame_count",
    "analysis_frame_count",
    "active_duration_s",
    "analysis_duration_s",
    "reference_coverage",
    "paired_tick_count",
    "pair_complete",
    "target_consistent",
    "target_metadata_valid",
    "included_speed_max",
    "accepted",
    "issues",
]


def compute_session_audit(
    output: pd.DataFrame,
    manifest: Mapping[str, object],
) -> pd.DataFrame:
    """检查双变体声明、丢行、运动任务与动态参考来源。"""

    session_id = str(manifest.get("session_id", ""))
    declared = tuple(str(value) for value in manifest.get("variant_labels", []))
    logged = tuple(sorted(output.get("label", pd.Series(dtype=str)).dropna().astype(str).unique()))
    trial_id = pd.to_numeric(output.get("rq2_trial_id", -1), errors="coerce")
    active_rows = output[trial_id > 0] if isinstance(trial_id, pd.Series) else output.iloc[0:0]
    tasks = tuple(
        sorted(active_rows.get("rq2_condition", pd.Series(dtype=str)).dropna().astype(str).unique())
    )
    stats = manifest.get("log_writer_stats", {})
    stats = stats if isinstance(stats, Mapping) else {}
    capture_dropped = _nonnegative_int(stats.get("capture_dropped_rows"), default=-1)
    output_dropped = _nonnegative_int(stats.get("output_dropped_rows"), default=-1)
    freshness_fields = {
        "gt_pose_fresh",
        "gt_pose_keep_alive",
        "gt_pose_fresh_age_ms",
    }
    freshness_present = freshness_fields.issubset(output.columns)
    dynamic_frames = unique_trial_frames(active_rows)
    keep_alive = dynamic_frames.get("gt_pose_keep_alive", pd.Series(False, index=dynamic_frames.index))
    keep_alive_count = int(keep_alive.fillna(False).astype(bool).sum())

    issues: list[str] = []
    _issue(issues, not session_id, "missing_session_id")
    _issue(issues, set(declared) != set(REQUIRED_VARIANTS), "variant_manifest_mismatch")
    _issue(issues, set(logged) != set(REQUIRED_VARIANTS), "variant_log_mismatch")
    _issue(issues, set(tasks) != set(RQ2_CONDITIONS), "motion_task_mismatch")
    _issue(issues, capture_dropped != 0, "capture_rows_dropped")
    _issue(issues, output_dropped != 0, "output_rows_dropped")
    _issue(issues, not freshness_present, "missing_freshness_fields")
    _issue(issues, keep_alive_count > 0, "dynamic_gt_used_keep_alive")
    record = {
        "session_id": session_id,
        "output_row_count": int(len(output)),
        "render_tick_count": int(len(unique_trial_frames(output))),
        "declared_variants": "|".join(declared),
        "logged_variants": "|".join(logged),
        "motion_tasks": "|".join(tasks),
        "capture_dropped_rows": capture_dropped,
        "output_dropped_rows": output_dropped,
        "freshness_fields_present": freshness_present,
        "dynamic_keep_alive_tick_count": keep_alive_count,
        "accepted": not issues,
        "issues": "|".join(issues),
    }
    return pd.DataFrame.from_records([record], columns=SESSION_AUDIT_COLUMNS)


def compute_trial_audit(
    output: pd.DataFrame,
    config: RQ2Config | None = None,
) -> pd.DataFrame:
    """逐试次检查配对完整性、参考覆盖与有效运动时长。"""

    settings = config or RQ2Config()
    if output.empty:
        return pd.DataFrame(columns=TRIAL_AUDIT_COLUMNS)
    trial_id = pd.to_numeric(output.get("rq2_trial_id", -1), errors="coerce")
    trials = output[
        output.get("rq2_condition", pd.Series("none", index=output.index))
        .astype(str)
        .isin(RQ2_CONDITIONS)
        & (trial_id > 0)
    ]
    rows: list[dict[str, object]] = []
    group_columns = ["session_id", "rq2_condition", "rq2_trial_id"]
    for (session_id, condition, current_trial), group in trials.groupby(
        group_columns, sort=True
    ):
        frames = unique_trial_frames(group)
        active = frames.get("active_motion", pd.Series(False, index=frames.index)).fillna(False).astype(bool)
        analysis = frames.get("analysis_motion", pd.Series(False, index=frames.index)).fillna(False).astype(bool)
        reference = reference_valid_mask(frames)
        active_count = int(active.sum())
        coverage = float((reference & active).sum() / active_count) if active_count else 0.0
        pair_complete, paired_tick_count = _pair_completeness(group)
        target_consistent = _target_consistent(frames)
        target_valid = _target_metadata_valid(str(condition), frames)
        analysis_duration = active_duration_seconds(frames, "analysis_motion")
        speed_column = (
            "gt_angular_speed_smooth_deg_s"
            if str(condition) == "rotation"
            else "gt_linear_speed_smooth_m_s"
        )
        included_speed = pd.to_numeric(frames.get(speed_column), errors="coerce")
        included_speed = included_speed[analysis & np.isfinite(included_speed)]
        issues: list[str] = []
        _issue(issues, not pair_complete, "incomplete_variant_pair")
        _issue(issues, not target_consistent, "inconsistent_target_metadata")
        _issue(issues, not target_valid, "invalid_target_metadata")
        _issue(issues, active_count == 0, "no_active_motion")
        _issue(issues, coverage < settings.min_reference_coverage, "insufficient_reference_coverage")
        _issue(
            issues,
            analysis_duration < settings.min_analysis_duration_s,
            "insufficient_analysis_duration",
        )
        rows.append(
            {
                "session_id": str(session_id),
                "condition": str(condition),
                "rq2_trial_id": int(current_trial),
                "render_tick_count": int(len(frames)),
                "active_frame_count": active_count,
                "analysis_frame_count": int(analysis.sum()),
                "active_duration_s": active_duration_seconds(frames, "active_motion"),
                "analysis_duration_s": analysis_duration,
                "reference_coverage": coverage,
                "paired_tick_count": paired_tick_count,
                "pair_complete": pair_complete,
                "target_consistent": target_consistent,
                "target_metadata_valid": target_valid,
                "included_speed_max": (
                    float(included_speed.max()) if len(included_speed) else np.nan
                ),
                "accepted": not issues,
                "issues": "|".join(issues),
            }
        )
    return pd.DataFrame.from_records(rows, columns=TRIAL_AUDIT_COLUMNS)


def accepted_trial_keys(audit: pd.DataFrame) -> set[tuple[str, str, int]]:
    """返回通过审计的 ``session × task × trial`` 键。"""

    if audit.empty:
        return set()
    accepted = audit[audit["accepted"].fillna(False).astype(bool)]
    return {
        (str(row.session_id), str(row.condition), int(row.rq2_trial_id))
        for row in accepted.itertuples()
    }


def _pair_completeness(group: pd.DataFrame) -> tuple[bool, int]:
    """检查每个 tick 是否恰有一条 Full 和一条 ZOH。"""

    key = "tick_index" if "tick_index" in group.columns else "render_mono_ms"
    paired = 0
    complete = True
    for _, rows in group.groupby(key, sort=False):
        labels = rows["label"].astype(str).tolist()
        ok = len(labels) == len(REQUIRED_VARIANTS) and set(labels) == set(REQUIRED_VARIANTS)
        paired += int(ok)
        complete &= ok
    return complete, paired


def _target_consistent(frames: pd.DataFrame) -> bool:
    """检查一个试次内的目标速度是否保持单一取值。"""

    return all(
        len(_finite_unique(frames.get(column))) <= 1
        for column in (
            "rq2_target_linear_speed_m_s",
            "rq2_target_angular_speed_deg_s",
        )
    )


def _target_metadata_valid(condition: str, frames: pd.DataFrame) -> bool:
    """检查平移与旋转试次使用匹配的目标速度通道。"""

    linear = _finite_unique(frames.get("rq2_target_linear_speed_m_s"))
    angular = _finite_unique(frames.get("rq2_target_angular_speed_deg_s"))
    if condition == "translation":
        return len(linear) == 1 and linear[0] > 0.0 and not angular
    if condition == "rotation":
        return len(angular) == 1 and angular[0] > 0.0 and not linear
    return False


def _finite_unique(values: object) -> list[float]:
    """返回有限浮点值的有序去重列表。"""

    if values is None:
        return []
    numeric = pd.to_numeric(values, errors="coerce")
    return sorted(float(value) for value in numeric[np.isfinite(numeric)].unique())


def _issue(issues: list[str], failed: bool, code: str) -> None:
    """在检查失败时追加稳定问题码。"""

    if failed:
        issues.append(code)


def _nonnegative_int(value: object, *, default: int) -> int:
    """把 manifest 计数解析为非负整数。"""

    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


__all__ = [
    "SESSION_AUDIT_COLUMNS",
    "TRIAL_AUDIT_COLUMNS",
    "accepted_trial_keys",
    "compute_session_audit",
    "compute_trial_audit",
]

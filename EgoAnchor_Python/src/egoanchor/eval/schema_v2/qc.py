"""schema-v2 采集前后质量门禁（QC）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .readers import EvalSessionV2, accepted_trial_keys
from .rows import SchemaV2Error


FORMAL_VARIANTS = (
    "Arrival-Hold",
    "Capture-Hold",
    "One-Euro Anchor",
    "EgoAnchor",
    "EgoAnchor w/o capture-time alignment",
    "EgoAnchor w/o VCD",
    "EgoAnchor w/o temporal synthesis",
    "EgoAnchor w/o StaticLock",
)
"""正式实验一/二场景冻结的八个唯一 runtime 变体。"""

_RUN_KINDS = {"debug", "smoke", "calibration", "formal"}
"""schema-v2 允许的 session 用途。"""


@dataclass(frozen=True)
class SchemaQcReport:
    """结构性质量检查结果。"""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """只有零个 errors 才能通过。"""

        return not self.errors


def run_schema_qc(session: EvalSessionV2) -> SchemaQcReport:
    """执行固定 session 文件、variant 矩阵和 writer stats 质量门禁。"""

    errors: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {}
    manifest = session.manifest
    _check_forbidden_fields(session, errors)
    _check_log_files(manifest, errors)
    variants = _variant_ids(manifest.get("variant_definitions"), errors)
    if not variants:
        errors.append("manifest.variant_definitions must contain at least one variant_id")
    metrics["variant_count"] = len(variants)

    _check_writer_stats(session, errors, metrics)
    _check_run_kind_and_formal_freeze(manifest, variants, errors)
    _check_variant_hashes(session, variants, errors)
    _check_completed_tasks(session, errors, metrics)
    _check_primary_keys(session, errors)
    _check_score_ranges(session, errors)

    if session.python_candidates.empty:
        errors.append("python_candidates is empty")
    if session.unity_reference.empty:
        errors.append("unity_reference is empty")
    if session.events.empty:
        warnings.append("events is empty")

    _check_render_matrix(session, variants, errors, metrics)
    _check_admission_matrix(session, variants, errors, warnings, metrics)
    return SchemaQcReport(errors=errors, warnings=warnings, metrics=metrics)


def _check_completed_tasks(
    session: EvalSessionV2,
    errors: list[str],
    metrics: dict[str, Any],
) -> None:
    """核对 manifest 完成任务摘要、固定计划和生命周期事件。"""

    raw = session.manifest.get("completed_tasks")
    plan = session.manifest.get("trial_plan")
    if not isinstance(raw, list):
        errors.append("manifest.completed_tasks must be an array")
        return
    if not isinstance(plan, list):
        errors.append("manifest.trial_plan must be an array")
        return

    manifest_keys: set[tuple[str, str, str, str]] = set()
    previous_number = 0
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            errors.append(f"manifest.completed_tasks[{index}] must be an object")
            continue
        task_number = item.get("task_number")
        if isinstance(task_number, bool) or not isinstance(task_number, int):
            errors.append(f"manifest.completed_tasks[{index}].task_number must be an integer")
            continue
        if task_number <= previous_number:
            errors.append("manifest.completed_tasks must use unique ascending task_number values")
        previous_number = task_number
        if task_number < 1 or task_number > len(plan):
            errors.append(
                f"manifest.completed_tasks[{index}].task_number is outside trial_plan: {task_number}"
            )
            continue

        values = tuple(str(item.get(key) or "") for key in ("experiment_id", "scenario_id", "trial_id"))
        if any(not value for value in values):
            errors.append(
                f"manifest.completed_tasks[{index}] requires experiment_id/scenario_id/trial_id"
            )
            continue
        planned = plan[task_number - 1]
        if not isinstance(planned, dict) or (
            planned.get("experiment_id"), planned.get("scenario_id")
        ) != values[:2]:
            errors.append(
                f"manifest.completed_tasks[{index}] does not match trial_plan task {task_number}"
            )
        manifest_keys.add((session.session_id, *values))

    try:
        event_keys = accepted_trial_keys(session)
    except SchemaV2Error as exc:
        errors.append(str(exc))
        event_keys = set()
    if manifest_keys != event_keys:
        errors.append(
            "manifest.completed_tasks does not match accepted lifecycle trials: "
            f"missing={sorted(event_keys - manifest_keys)}, extra={sorted(manifest_keys - event_keys)}"
        )
    if str(session.manifest.get("run_kind", "")).lower() == "formal" and not event_keys:
        errors.append("formal session requires at least one completed task")
    if str(session.manifest.get("run_kind", "")).lower() == "formal":
        _check_formal_trial_durations(session, event_keys, plan, errors, metrics)
    metrics["completed_task_count"] = len(event_keys)


def _check_formal_trial_durations(
    session: EvalSessionV2,
    event_keys: set[tuple[str, str, str, str]],
    plan: list[Any],
    errors: list[str],
    metrics: dict[str, Any],
) -> None:
    """正式完成 trial 必须具有唯一开始/结束事件，且持续时间落在冻结计划范围内。"""

    plan_by_condition = {
        (str(item.get("experiment_id") or ""), str(item.get("scenario_id") or "")): item
        for item in plan
        if isinstance(item, dict)
    }
    durations: dict[str, float] = {}
    for session_id, experiment_id, scenario_id, trial_id in sorted(event_keys):
        rows = session.events[
            (session.events["session_id"].astype(str) == session_id)
            & (session.events["experiment_id"].astype(str) == experiment_id)
            & (session.events["scenario_id"].astype(str) == scenario_id)
            & (session.events["trial_id"].astype(str) == trial_id)
        ]
        starts = rows[rows["event_type"] == "trial_started"]
        ends = rows[rows["event_type"] == "trial_ended"]
        if len(starts) != 1 or len(ends) != 1:
            errors.append(
                f"formal trial {trial_id!r} requires exactly one trial_started and trial_ended event"
            )
            continue

        duration_seconds = (float(ends.iloc[0]["mono_ms"]) - float(starts.iloc[0]["mono_ms"])) / 1000.0
        durations[trial_id] = round(duration_seconds, 3)
        planned = plan_by_condition.get((experiment_id, scenario_id), {})
        minimum_raw = planned.get("minimum_seconds")
        maximum_raw = planned.get("maximum_seconds")
        if (
            isinstance(minimum_raw, bool)
            or not isinstance(minimum_raw, (int, float))
            or isinstance(maximum_raw, bool)
            or not isinstance(maximum_raw, (int, float))
        ):
            errors.append(f"formal trial plan for {experiment_id}/{scenario_id} requires numeric duration bounds")
            continue
        minimum = float(minimum_raw)
        maximum = float(maximum_raw)
        if duration_seconds < minimum or duration_seconds > maximum:
            errors.append(
                f"formal trial {trial_id!r} duration {duration_seconds:.3f}s is outside "
                f"[{minimum:.3f}, {maximum:.3f}]s"
            )
    metrics["completed_trial_duration_seconds"] = durations


def _variant_ids(raw: Any, errors: list[str]) -> set[str]:
    """提取并验证 manifest 中的 variant id。"""

    if not isinstance(raw, list):
        return set()
    result: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            errors.append(f"manifest.variant_definitions[{index}] must be an object")
            continue
        variant_id = item.get("variant_id")
        if not isinstance(variant_id, str) or not variant_id:
            errors.append(f"manifest.variant_definitions[{index}] requires non-empty variant_id")
            continue
        if variant_id in result:
            errors.append(f"manifest.variant_definitions contains duplicate variant_id: {variant_id}")
        result.add(variant_id)
    return result


def _check_log_files(manifest: dict[str, Any], errors: list[str]) -> None:
    """manifest 必须声明固定逻辑名到固定文件名的精确映射。"""

    expected = {
        "python_candidates": "python_candidates.jsonl",
        "unity_reference": "unity_reference.jsonl",
        "unity_admission": "unity_admission.jsonl",
        "unity_render": "unity_render.jsonl",
        "events": "events.jsonl",
    }
    if manifest.get("log_files") != expected:
        errors.append(f"manifest.log_files must equal fixed schema-v2 mapping: {expected}")


def _check_writer_stats(session: EvalSessionV2, errors: list[str], metrics: dict[str, Any]) -> None:
    """检查每个固定文件的完整统计、失败标记及实际行数。"""

    expected_rows = {
        "python_candidates.jsonl": len(session.python_candidates),
        "unity_reference.jsonl": len(session.unity_reference),
        "unity_admission.jsonl": len(session.unity_admission),
        "unity_render.jsonl": len(session.unity_render),
        "events.jsonl": len(session.events),
    }
    raw_stats = session.manifest.get("log_writer_stats")
    if not isinstance(raw_stats, dict):
        errors.append("manifest.log_writer_stats must be an object")
        return
    missing = sorted(set(expected_rows) - raw_stats.keys())
    extra = sorted(raw_stats.keys() - set(expected_rows))
    if missing:
        errors.append(f"manifest.log_writer_stats missing files: {missing}")
    if extra:
        errors.append(f"manifest.log_writer_stats has unknown files: {extra}")

    for file_name, actual_rows in expected_rows.items():
        stats = raw_stats.get(file_name)
        if not isinstance(stats, dict):
            if file_name not in missing:
                errors.append(f"log_writer_stats[{file_name!r}] must be an object")
            continue
        status = str(stats.get("status") or "")
        if status.startswith("pending"):
            errors.append(f"writer stats pending for {file_name}: {status}")
        rows_written = _stats_int(stats, "rows_written", file_name, errors)
        dropped = _stats_int(stats, "dropped_rows", file_name, errors)
        failures = stats.get("log_write_failures", 0)
        if isinstance(failures, bool) or not isinstance(failures, int) or failures < 0:
            errors.append(f"writer stats {file_name}.log_write_failures must be a non-negative integer")
        elif failures:
            errors.append(f"writer failures for {file_name}: {failures}")
        write_error = str(stats.get("write_error") or "")
        if write_error:
            errors.append(f"writer error for {file_name}: {write_error}")
        if dropped is not None and dropped != 0:
            errors.append(f"writer dropped rows for {file_name}: {dropped}")
        if rows_written is not None and rows_written != actual_rows:
            errors.append(f"writer row count mismatch for {file_name}: stats={rows_written}, actual={actual_rows}")
        metrics[f"{file_name}.rows"] = actual_rows


def _stats_int(stats: dict[str, Any], key: str, file_name: str, errors: list[str]) -> int | None:
    """读取 manifest writer 非负整数统计；null 和 bool 都视为错误。"""

    value = stats.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        errors.append(f"writer stats {file_name}.{key} must be a non-negative integer")
        return None
    return value


def _check_run_kind_and_formal_freeze(
    manifest: dict[str, Any],
    variants: set[str],
    errors: list[str],
) -> None:
    """验证 run kind；Formal 额外要求八变体与自动生成的运行元数据。"""

    raw_run_kind = manifest.get("run_kind")
    normalized = raw_run_kind.strip().lower() if isinstance(raw_run_kind, str) else ""
    if normalized not in _RUN_KINDS or raw_run_kind != normalized:
        errors.append(f"manifest.run_kind must be one of {sorted(_RUN_KINDS)} using canonical lowercase spelling")
    if normalized != "formal":
        return
    expected_variants = set(FORMAL_VARIANTS)
    if variants != expected_variants:
        errors.append(
            "formal session requires exact eight variants: "
            f"missing={sorted(expected_variants - variants)}, extra={sorted(variants - expected_variants)}"
        )
    for key in (
        "object_id",
        "operator_id",
        "unity_run_mode",
        "python_host",
        "unity_version",
        "python_version",
        "protocol_version",
        "config_hash",
        "frozen_parameter_set_id",
        "object_model_id",
    ):
        if not isinstance(manifest.get(key), str) or not str(manifest[key]).strip():
            errors.append(f"formal session requires non-empty manifest.{key}")


def _check_variant_hashes(session: EvalSessionV2, variants: set[str], errors: list[str]) -> None:
    """manifest、admission 与 render 必须对每个变体使用同一非空配置 hash。"""

    definitions = session.manifest.get("variant_definitions")
    if not isinstance(definitions, list):
        return
    expected: dict[str, str] = {}
    for item in definitions:
        if not isinstance(item, dict) or item.get("variant_id") not in variants:
            continue
        variant_id = str(item["variant_id"])
        config_hash = item.get("config_hash")
        if not isinstance(config_hash, str) or not config_hash.strip():
            errors.append(f"variant {variant_id!r} requires non-empty manifest config_hash")
            continue
        expected[variant_id] = config_hash

    try:
        aggregate = aggregate_config_hash(definitions)
    except ValueError as exc:
        errors.append(str(exc))
    else:
        if session.manifest.get("config_hash") != aggregate:
            errors.append(
                "manifest.config_hash does not match ordered variant config hashes: "
                f"expected={aggregate}, observed={session.manifest.get('config_hash')!r}"
            )

    for table_name, table in (("unity_admission", session.unity_admission), ("unity_render", session.unity_render)):
        if table.empty:
            continue
        if "config_hash" not in table.columns:
            errors.append(f"{table_name} requires config_hash")
            continue
        for index, row in table.iterrows():
            variant_id = str(row.get("variant_id"))
            expected_hash = expected.get(variant_id)
            if expected_hash is None:
                continue
            observed_hash = row["config_hash"]
            if not isinstance(observed_hash, str) or not observed_hash.strip() or observed_hash != expected_hash:
                errors.append(
                    f"{table_name} row {index!r} variant {variant_id!r} config_hash mismatch: "
                    f"expected={expected_hash!r}, observed={observed_hash!r}"
                )


def _check_render_matrix(session: EvalSessionV2, variants: set[str], errors: list[str], metrics: dict[str, Any]) -> None:
    """每个 render tick 必须包含全部 variant。"""

    table = session.unity_render
    if table.empty:
        errors.append("unity_render is empty")
        return
    required = {
        "session_id",
        "render_tick_id",
        "variant_id",
        "source_frame_id",
        "has_output_pose",
        "has_display_pose",
    }
    if not _require_columns(table, "unity_render", required, errors):
        return
    metrics["render_tick_count"] = int(table["render_tick_id"].nunique())
    if table.duplicated(["session_id", "render_tick_id", "variant_id"]).any():
        errors.append("unity_render contains duplicate session/render_tick/variant primary keys")
    reference_ids = (
        {int(item) for item in session.unity_reference["frame_id"].dropna()}
        if "frame_id" in session.unity_reference
        else set()
    )
    for index, row in table.iterrows():
        source_frame_id = int(row["source_frame_id"])
        if source_frame_id < 0:
            if bool(row["has_output_pose"]) or bool(row["has_display_pose"]):
                errors.append(f"render row {index!r} has display/output pose without a source frame")
        elif source_frame_id not in reference_ids:
            errors.append(f"render row {index!r} references unknown source_frame_id: {source_frame_id}")
    for tick_id, group in table.groupby("render_tick_id", dropna=False):
        observed = {str(item) for item in group["variant_id"].dropna()}
        missing = variants - observed
        extra = observed - variants
        if missing:
            errors.append(f"render tick {tick_id!r} missing variants: {sorted(missing)}")
        if extra:
            errors.append(f"render tick {tick_id!r} has unknown variants: {sorted(extra)}")
        if group.duplicated(["render_tick_id", "variant_id"]).any():
            errors.append(f"render tick {tick_id!r} contains duplicate variant rows")


def _check_admission_matrix(
    session: EvalSessionV2,
    variants: set[str],
    errors: list[str],
    warnings: list[str],
    metrics: dict[str, Any],
) -> None:
    """每个被 Unity 消费的 candidate 必须在所有 variant 上有明确 admission 行。"""

    table = session.unity_admission
    if table.empty:
        errors.append("unity_admission is empty")
        return
    if not _require_columns(table, "unity_admission", {"candidate_id", "variant_id"}, errors):
        return
    metrics["candidate_count"] = int(table["candidate_id"].nunique())
    expected_candidates = (
        {str(item) for item in session.python_candidates["candidate_id"].dropna()}
        if "candidate_id" in session.python_candidates
        else set()
    )
    observed_candidates = {str(item) for item in table["candidate_id"].dropna()}
    missing_candidates = expected_candidates - observed_candidates
    extra_candidates = observed_candidates - expected_candidates
    metrics["python_candidate_count"] = len(expected_candidates)
    metrics["python_candidates_without_unity_admission"] = len(missing_candidates)
    if missing_candidates:
        sample = sorted(missing_candidates)[:5]
        warnings.append(
            f"{len(missing_candidates)} python candidates were not consumed by Unity admission "
            f"(latest-only delivery or session boundary); excluded from candidate-level analysis; sample={sample}"
        )
    if extra_candidates:
        errors.append(f"admission has unknown candidate_id values: {sorted(extra_candidates)}")
    for candidate_id, group in table.groupby("candidate_id", dropna=False):
        observed = {str(item) for item in group["variant_id"].dropna()}
        missing = variants - observed
        if missing:
            errors.append(f"candidate {candidate_id!r} missing admission variants: {sorted(missing)}")
        extra = observed - variants
        if extra:
            errors.append(f"candidate {candidate_id!r} has unknown admission variants: {sorted(extra)}")
        if group.duplicated(["candidate_id", "variant_id"]).any():
            errors.append(f"candidate {candidate_id!r} contains duplicate admission variants")


def _check_forbidden_fields(session: EvalSessionV2, errors: list[str]) -> None:
    """递归拒绝 manifest、payload 和表中重新出现的旧字段。"""

    hits = _find_forbidden_keys(session.manifest, prefix="manifest")
    if hits:
        errors.append(f"manifest contains forbidden legacy fields: {sorted(hits)}")
    for name, table in (
        ("python_candidates", session.python_candidates),
        ("unity_reference", session.unity_reference),
        ("unity_admission", session.unity_admission),
        ("unity_render", session.unity_render),
        ("events", session.events),
    ):
        hits: set[str] = set()
        for index, row in enumerate(table.to_dict(orient="records")):
            hits.update(_find_forbidden_keys(row, prefix=f"{name}[{index}]"))
        if hits:
            errors.append(f"{name} contains forbidden legacy fields: {sorted(hits)}")


def _check_primary_keys(session: EvalSessionV2, errors: list[str]) -> None:
    """candidate 与 reference 右表主键必须唯一，保证 many-to-one join 可执行。"""

    candidates = session.python_candidates
    if (
        not candidates.empty
        and _require_columns(candidates, "python_candidates", {"session_id", "candidate_id"}, errors)
        and candidates.duplicated(["session_id", "candidate_id"]).any()
    ):
        errors.append("python_candidates contains duplicate session_id/candidate_id primary keys")
    reference = session.unity_reference
    if (
        not reference.empty
        and _require_columns(reference, "unity_reference", {"session_id", "frame_id"}, errors)
        and reference.duplicated(["session_id", "frame_id"]).any()
    ):
        errors.append("unity_reference contains duplicate session_id/frame_id primary keys")


def _check_score_ranges(session: EvalSessionV2, errors: list[str]) -> None:
    """连续可靠性评分必须保持 `[0,1]`，null 表示信号不可用。"""

    candidate_scores = (
        "vcd_score",
        "visibility_score",
        "geometry_core_score",
        "color_projection_score",
        "depth_alignment_score",
        "depth_abs_score",
        "depth_struct_score",
        "depth_alpha",
    )
    for table_name, table, columns in (
        ("python_candidates", session.python_candidates, candidate_scores),
        ("unity_admission", session.unity_admission, ("vcd_score",)),
    ):
        for column in columns:
            if column not in table.columns:
                errors.append(f"{table_name} requires score column {column}")
                continue
            present = table[column].notna()
            values = pd.to_numeric(table[column], errors="coerce")
            invalid = present & (
                values.isna() | ~values.between(0.0, 1.0, inclusive="both")
            )
            if invalid.any():
                errors.append(
                    f"{table_name}.{column} contains {int(invalid.sum())} values outside [0, 1]"
                )


def _require_columns(table: Any, table_name: str, required: set[str], errors: list[str]) -> bool:
    """要求 QC 直接接收的 DataFrame 具备结构列，损坏输入只返回错误而不抛 KeyError。"""

    missing = sorted(required - set(table.columns))
    if missing:
        errors.append(f"{table_name} requires columns: {', '.join(missing)}")
        return False
    return True


def _find_forbidden_keys(value: Any, *, prefix: str) -> set[str]:
    """递归查找旧 RQ、GT 和旧文件语义字段键。"""

    hits: set[str] = set()
    if isinstance(value, dict):
        for raw_key, item in value.items():
            key = str(raw_key)
            path = f"{prefix}.{key}"
            lowered = key.lower()
            if lowered.startswith(("rq1_", "rq2_", "gt_")) or any(
                token in lowered for token in ("session_manifest", "unity_capture", "unity_output")
            ):
                hits.add(path)
            hits.update(_find_forbidden_keys(item, prefix=path))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            hits.update(_find_forbidden_keys(item, prefix=f"{prefix}[{index}]"))
    return hits


def aggregate_config_hash(variant_definitions: Any) -> str:
    """复现 Unity EvalJson 对有序 variant config hash 列表的 FNV-1a 汇总。"""

    if not isinstance(variant_definitions, list):
        raise ValueError("manifest.variant_definitions must be a list for aggregate config hash")
    hash_value = 14695981039346656037
    prime = 1099511628211
    mask = (1 << 64) - 1
    for index, item in enumerate(variant_definitions):
        config_hash = item.get("config_hash") if isinstance(item, dict) else None
        if not isinstance(config_hash, str) or not config_hash.strip():
            raise ValueError(f"variant_definitions[{index}] requires non-empty config_hash")
        for value in config_hash.encode("utf-8"):
            hash_value ^= value
            hash_value = (hash_value * prime) & mask
    return f"{hash_value:016x}"


__all__ = ["FORMAL_VARIANTS", "SchemaQcReport", "aggregate_config_hash", "run_schema_qc"]

"""schema-v2 采集前后质量门禁（QC）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .readers import EvalSessionV2


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
    variants = _variant_ids(manifest.get("variant_definitions"))
    if not variants:
        errors.append("manifest.variant_definitions must contain at least one variant_id")
    metrics["variant_count"] = len(variants)

    for file_name, stats in (manifest.get("log_writer_stats") or {}).items():
        if not isinstance(stats, dict):
            errors.append(f"log_writer_stats[{file_name!r}] must be an object")
            continue
        dropped = stats.get("dropped_rows", 0)
        if dropped:
            errors.append(f"writer dropped rows for {file_name}: {dropped}")

    if session.python_candidates.empty:
        errors.append("python_candidates is empty")
    if session.unity_reference.empty:
        errors.append("unity_reference is empty")
    if session.events.empty:
        warnings.append("events is empty")

    _check_render_matrix(session, variants, errors, metrics)
    _check_admission_matrix(session, variants, errors, metrics)
    return SchemaQcReport(errors=errors, warnings=warnings, metrics=metrics)


def _variant_ids(raw: Any) -> set[str]:
    """提取并验证 manifest 中的 variant id。"""

    if not isinstance(raw, list):
        return set()
    result: set[str] = set()
    for item in raw:
        if isinstance(item, dict) and isinstance(item.get("variant_id"), str) and item["variant_id"]:
            result.add(item["variant_id"])
    return result


def _check_render_matrix(session: EvalSessionV2, variants: set[str], errors: list[str], metrics: dict[str, Any]) -> None:
    """每个 render tick 必须包含全部 variant。"""

    table = session.unity_render
    if table.empty:
        errors.append("unity_render is empty")
        return
    if "render_tick_id" not in table or "variant_id" not in table:
        errors.append("unity_render requires render_tick_id and variant_id")
        return
    metrics["render_tick_count"] = int(table["render_tick_id"].nunique())
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


def _check_admission_matrix(session: EvalSessionV2, variants: set[str], errors: list[str], metrics: dict[str, Any]) -> None:
    """每个 candidate 必须在所有 variant 上有明确 admission 行。"""

    table = session.unity_admission
    if table.empty:
        errors.append("unity_admission is empty")
        return
    if "candidate_id" not in table or "variant_id" not in table:
        errors.append("unity_admission requires candidate_id and variant_id")
        return
    metrics["candidate_count"] = int(table["candidate_id"].nunique())
    for candidate_id, group in table.groupby("candidate_id", dropna=False):
        observed = {str(item) for item in group["variant_id"].dropna()}
        missing = variants - observed
        if missing:
            errors.append(f"candidate {candidate_id!r} missing admission variants: {sorted(missing)}")
        if group.duplicated(["candidate_id", "variant_id"]).any():
            errors.append(f"candidate {candidate_id!r} contains duplicate admission variants")


def _check_forbidden_fields(session: EvalSessionV2, errors: list[str]) -> None:
    """Reject retired RQ/legacy fields anywhere in formal schema tables."""

    forbidden = ("rq1_", "rq2_", "session_manifest", "unity_capture", "unity_output")
    for name, table in (
        ("python_candidates", session.python_candidates),
        ("unity_reference", session.unity_reference),
        ("unity_admission", session.unity_admission),
        ("unity_render", session.unity_render),
        ("events", session.events),
    ):
        hits = [str(column) for column in table.columns if any(token in str(column).lower() for token in forbidden)]
        if hits:
            errors.append(f"{name} contains forbidden legacy fields: {sorted(hits)}")


__all__ = ["SchemaQcReport", "run_schema_qc"]

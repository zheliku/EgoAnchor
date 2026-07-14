"""schema-v2 session reader 与 normalized table 容器。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .paths import EvalV2Paths
from .rows import SCHEMA_VERSION, SchemaV2Error, validate_schema_mapping


@dataclass(frozen=True)
class EvalSessionV2:
    """加载后的 schema-v2 session；表均为 pandas normalized long tables。"""

    paths: EvalV2Paths
    manifest: dict[str, Any]
    python_candidates: pd.DataFrame
    unity_reference: pd.DataFrame
    unity_admission: pd.DataFrame
    unity_render: pd.DataFrame
    events: pd.DataFrame

    @property
    def session_id(self) -> str:
        """返回 manifest 中的 session id。"""

        return str(self.manifest["session_id"])


def join_candidate_admission(session: EvalSessionV2) -> pd.DataFrame:
    """Join Python candidates to Unity admission rows without duplicating keys.

    Admission is a candidate x variant table, so the candidate fields are
    repeated for every configured runtime variant.  The join is intentionally
    left-preserving and uses ``candidate_id`` (plus session_id when present)
    rather than frame_id, which may have multiple candidates.
    """

    candidates = session.python_candidates.copy()
    admission = session.unity_admission.copy()
    if candidates.empty or admission.empty:
        return pd.DataFrame()
    keys = ["candidate_id"]
    if "session_id" in candidates.columns and "session_id" in admission.columns:
        keys.insert(0, "session_id")
    return admission.merge(candidates, on=keys, how="left", suffixes=("", "_candidate"), validate="many_to_one")


def join_render_reference(session: EvalSessionV2) -> pd.DataFrame:
    """Join display/render rows to the captured platform reference by frame."""

    render = session.unity_render.copy()
    reference = session.unity_reference.copy()
    if render.empty or reference.empty:
        return pd.DataFrame()
    render_key = "frame_id" if "frame_id" in render.columns else "source_frame_id"
    if render_key not in render.columns or "frame_id" not in reference.columns:
        raise SchemaV2Error("unity_render requires source_frame_id and unity_reference requires frame_id for joining")
    left_on = [render_key]
    right_on = ["frame_id"]
    if "session_id" in render.columns and "session_id" in reference.columns:
        left_on.insert(0, "session_id")
        right_on.insert(0, "session_id")
    return render.merge(
        reference,
        left_on=left_on,
        right_on=right_on,
        how="left",
        suffixes=("", "_reference"),
        validate="many_to_one",
    )


def select_trials(session: EvalSessionV2, experiment_id: str) -> EvalSessionV2:
    """Return a session view containing rows for one experiment id."""

    if not experiment_id:
        raise ValueError("experiment_id must be non-empty")

    admission = session.unity_admission
    render = session.unity_render
    def by_experiment(table: pd.DataFrame) -> pd.DataFrame:
        if table.empty or "experiment_id" not in table.columns:
            return table.copy()
        return table[table["experiment_id"].astype(str) == experiment_id].copy()

    admission_filtered = by_experiment(admission)
    render_filtered = by_experiment(render)

    def by_values(table: pd.DataFrame, column: str, values: set[Any]) -> pd.DataFrame:
        if table.empty or column not in table.columns:
            return table.copy()
        return table[table[column].isin(values)].copy()

    candidate_ids = set(admission_filtered.get("candidate_id", pd.Series(dtype=str)).dropna())
    frame_ids = set(admission_filtered.get("frame_id", pd.Series(dtype=int)).dropna())
    frame_ids.update(render_filtered.get("source_frame_id", pd.Series(dtype=int)).dropna())
    trial_ids = set(admission_filtered.get("trial_id", pd.Series(dtype=str)).dropna())
    trial_ids.update(render_filtered.get("trial_id", pd.Series(dtype=str)).dropna())

    def filter_events(events: pd.DataFrame) -> pd.DataFrame:
        if events.empty:
            return events.copy()
        if "experiment_id" in events.columns:
            return events[events["experiment_id"].astype(str) == experiment_id].copy()
        return by_values(events, "trial_id", trial_ids)

    manifest = dict(session.manifest)
    if isinstance(manifest.get("experiment_ids"), list):
        manifest["experiment_ids"] = [experiment_id] if experiment_id in manifest["experiment_ids"] else []
    return EvalSessionV2(
        paths=session.paths,
        manifest=manifest,
        python_candidates=by_values(session.python_candidates, "candidate_id", candidate_ids),
        unity_reference=by_values(session.unity_reference, "frame_id", frame_ids),
        unity_admission=admission_filtered,
        unity_render=render_filtered,
        events=filter_events(session.events),
    )


def load_session_v2(session_dir: str | Path) -> EvalSessionV2:
    """严格读取固定 schema-v2 文件并转换为 DataFrame。"""

    paths = EvalV2Paths.for_session(session_dir)
    if not paths.manifest.is_file():
        if (paths.session_dir / "session_manifest.json").exists():
            raise SchemaV2Error("schema-v2 requires manifest.json; legacy session_manifest.json is unsupported")
        raise SchemaV2Error(f"schema-v2 requires {paths.manifest.name}")
    if not paths.audit_samples.is_dir():
        raise SchemaV2Error(f"schema-v2 requires directory {paths.audit_samples.name}/")

    try:
        manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SchemaV2Error(f"cannot read {paths.manifest}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise SchemaV2Error("manifest.json must contain an object")
    validate_schema_mapping(manifest)
    session_id = manifest.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise SchemaV2Error("manifest.json requires non-empty session_id")

    # 前四个数据文件各自只有一种固定行类型；events.jsonl 则承载
    # session_started、trial_started、runtime_error 等多种事件，不应锁死事件名。
    expected_events = ("python_candidate", "unity_reference", "unity_admission", "unity_render", None)
    tables = [
        _read_jsonl(path, session_id=session_id, expected_event=event)
        for path, event in zip(paths.jsonl_paths(), expected_events, strict=True)
    ]
    return EvalSessionV2(
        paths=paths,
        manifest=manifest,
        python_candidates=tables[0],
        unity_reference=tables[1],
        unity_admission=tables[2],
        unity_render=tables[3],
        events=tables[4],
    )


def _read_jsonl(path: Path, *, session_id: str, expected_event: str | None) -> pd.DataFrame:
    """读取单个 JSONL 文件并验证每行固定 schema。"""

    if not path.is_file():
        raise SchemaV2Error(f"schema-v2 requires {path.name}")
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SchemaV2Error(f"cannot read {path}: {exc}") from exc
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SchemaV2Error(f"{path.name}:{line_number}: invalid JSON: {exc.msg}") from exc
        if not isinstance(row, dict):
            raise SchemaV2Error(f"{path.name}:{line_number}: JSON row must be an object")
        try:
            validate_schema_mapping(row, expected_event=expected_event)
        except SchemaV2Error as exc:
            raise SchemaV2Error(f"{path.name}:{line_number}: {exc}") from exc
        if row.get("session_id") != session_id:
            raise SchemaV2Error(f"{path.name}:{line_number}: session_id does not match manifest")
        rows.append(row)
    return pd.DataFrame.from_records(rows)


__all__ = [
    "EvalSessionV2",
    "join_candidate_admission",
    "join_render_reference",
    "load_session_v2",
    "select_trials",
]

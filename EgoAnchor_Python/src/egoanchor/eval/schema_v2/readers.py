"""schema-v2 session reader 与 normalized table 容器。"""

from __future__ import annotations

import json
import math
import types
import uuid
from copy import deepcopy
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Union, get_args, get_origin, get_type_hints

import pandas as pd

from .paths import EvalV2Paths
from .rows import (
    EventRow,
    ManifestV2,
    PythonCandidateRow,
    SchemaV2Error,
    UnityAdmissionRow,
    UnityReferenceRow,
    UnityRenderRow,
    validate_schema_mapping,
)


_PYTHON_FRAGMENT_NAME = "python_session.json"
"""Python runtime 停止时写入的统计片段文件名。"""

TRIAL_KEY_COLUMNS = ("session_id", "experiment_id", "scenario_id", "trial_id")
"""完成、作废和跨表投影共用的 trial 稳定键。"""


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
    """按稳定 candidate_id 连接 Python candidate 与 Unity admission。"""

    candidates = session.python_candidates.copy()
    admission = session.unity_admission.copy()
    keys = ["session_id", "candidate_id"]
    try:
        joined = admission.merge(
            candidates,
            on=keys,
            how="left",
            suffixes=("", "_candidate"),
            validate="many_to_one",
            indicator=True,
        )
    except pd.errors.MergeError as exc:
        raise SchemaV2Error(f"candidate/admission join cardinality violation: {exc}") from exc
    missing = joined.loc[joined["_merge"] != "both", "candidate_id"].astype(str).unique().tolist()
    if missing:
        raise SchemaV2Error(f"unity_admission references unknown candidate_id values: {sorted(missing)}")
    return joined.drop(columns="_merge")


def join_render_reference(session: EvalSessionV2) -> pd.DataFrame:
    """按 source_frame_id 连接 render 行与采集时刻平台参考。"""

    render = session.unity_render.copy()
    reference = session.unity_reference.copy()
    try:
        joined = render.merge(
            reference,
            left_on=["session_id", "source_frame_id"],
            right_on=["session_id", "frame_id"],
            how="left",
            suffixes=("", "_reference"),
            validate="many_to_one",
            indicator=True,
        )
    except pd.errors.MergeError as exc:
        raise SchemaV2Error(f"render/reference join cardinality violation: {exc}") from exc
    missing_mask = (joined["source_frame_id"] >= 0) & (joined["_merge"] != "both")
    missing = joined.loc[missing_mask, "source_frame_id"].unique().tolist()
    if missing:
        raise SchemaV2Error(f"unity_render references unknown source_frame_id values: {sorted(missing)}")
    return joined.drop(columns="_merge")


def select_trials(session: EvalSessionV2, experiment_id: str) -> EvalSessionV2:
    """返回单个实验及其关联 candidate/reference/event 的严格 session 视图。"""

    if not experiment_id:
        raise ValueError("experiment_id must be non-empty")

    experiment_ids = session.manifest.get("experiment_ids")
    if not isinstance(experiment_ids, list) or experiment_id not in experiment_ids:
        raise SchemaV2Error(f"manifest does not declare experiment_id={experiment_id!r}")

    admission = session.unity_admission
    render = session.unity_render

    def by_experiment(table: pd.DataFrame) -> pd.DataFrame:
        """按必需 experiment_id 列筛选。"""

        if table.empty:
            return table.copy()
        return table[table["experiment_id"].astype(str) == experiment_id].copy()

    admission_filtered = by_experiment(admission)
    render_filtered = by_experiment(render)

    def by_values(table: pd.DataFrame, column: str, values: set[Any]) -> pd.DataFrame:
        """按已由实验行确定的稳定键筛选关联表。"""

        if table.empty:
            return table.copy()
        return table[table[column].isin(values)].copy()

    candidate_ids = set(admission_filtered.get("candidate_id", pd.Series(dtype=str)).dropna())
    frame_ids = set(admission_filtered.get("frame_id", pd.Series(dtype=int)).dropna())
    frame_ids.update(render_filtered.get("source_frame_id", pd.Series(dtype=int)).dropna())

    def filter_events(events: pd.DataFrame) -> pd.DataFrame:
        """保留目标实验事件和 experiment_id 为空的 session-global 事件。"""

        if events.empty:
            return events.copy()
        values = events["experiment_id"].astype(str)
        return events[(values == experiment_id) | (values == "")].copy()

    manifest = dict(session.manifest)
    return EvalSessionV2(
        paths=session.paths,
        manifest=manifest,
        python_candidates=by_values(session.python_candidates, "candidate_id", candidate_ids),
        unity_reference=by_values(session.unity_reference, "frame_id", frame_ids),
        unity_admission=admission_filtered,
        unity_render=render_filtered,
        events=filter_events(session.events),
    )


def select_completed_trials(session: EvalSessionV2) -> EvalSessionV2:
    """只保留已正常结束且没有被 ``trial_rejected`` 作废的 trial。

    原始 schema-v2 表保持不可变，基础 QC 仍检查全部行。实验一/二的正式 QC、指标和
    risk-coverage 使用本投影视图，从而允许操作者保留错误尝试的审计记录并只重做该任务。
    """

    trial_columns = TRIAL_KEY_COLUMNS
    events = session.events
    accepted = accepted_trial_keys(session)

    def by_trial(table: pd.DataFrame) -> pd.DataFrame:
        """按完整 trial 键投影一张带实验上下文的表。"""

        if table.empty:
            return table.copy()
        keys = table.loc[:, trial_columns].astype(str)
        mask = [tuple(values) in accepted for values in keys.itertuples(index=False, name=None)]
        return table.loc[mask].copy()

    admission = by_trial(session.unity_admission)
    render = by_trial(session.unity_render)
    candidate_ids = set(admission.get("candidate_id", pd.Series(dtype=str)).dropna())
    frame_ids = set(admission.get("frame_id", pd.Series(dtype=int)).dropna())
    frame_ids.update(
        value
        for value in render.get("source_frame_id", pd.Series(dtype=int)).dropna()
        if int(value) >= 0
    )

    if events.empty:
        filtered_events = events.copy()
    else:
        trial_ids = events["trial_id"].astype(str)
        global_events = trial_ids.eq("")
        event_keys = events.loc[:, trial_columns].astype(str)
        accepted_events = [
            tuple(values) in accepted
            for values in event_keys.itertuples(index=False, name=None)
        ]
        filtered_events = events.loc[global_events | pd.Series(accepted_events, index=events.index)].copy()

    def by_values(table: pd.DataFrame, column: str, values: set[Any]) -> pd.DataFrame:
        """按完成 trial 关联出的稳定键裁剪无上下文表。"""

        if table.empty:
            return table.copy()
        return table[table[column].isin(values)].copy()

    return EvalSessionV2(
        paths=session.paths,
        manifest=dict(session.manifest),
        python_candidates=by_values(session.python_candidates, "candidate_id", candidate_ids),
        unity_reference=by_values(session.unity_reference, "frame_id", frame_ids),
        unity_admission=admission,
        unity_render=render,
        events=filtered_events,
    )


def accepted_trial_keys(session: EvalSessionV2) -> set[tuple[str, ...]]:
    """从生命周期事件返回已结束且未作废的 trial 稳定键。"""

    events = session.events
    if events.empty:
        return set()
    required = {"event_type", *TRIAL_KEY_COLUMNS}
    missing = sorted(required - set(events.columns))
    if missing:
        raise SchemaV2Error(f"events requires completed-trial columns: {missing}")

    lifecycle = events[
        events["event_type"].astype(str).isin({"trial_ended", "trial_rejected"})
    ]
    records: dict[str, set[tuple[str, ...]]] = {
        "trial_ended": set(),
        "trial_rejected": set(),
    }
    for _, row in lifecycle.iterrows():
        key = tuple(str(row[column]) for column in TRIAL_KEY_COLUMNS)
        if any(not value for value in key):
            raise SchemaV2Error(
                f"{row['event_type']} requires non-empty " + "/".join(TRIAL_KEY_COLUMNS)
            )
        records[str(row["event_type"])].add(key)
    return records["trial_ended"] - records["trial_rejected"]


def accepted_trial_table(session: EvalSessionV2) -> pd.DataFrame:
    """把当前 session 的最终完成 trial 转为稳定、去重、排序的数据表。"""

    columns = list(TRIAL_KEY_COLUMNS)
    records = [dict(zip(columns, key, strict=True)) for key in accepted_trial_keys(session)]
    if not records:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame.from_records(records, columns=columns).sort_values(columns).reset_index(drop=True)


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
    _require_fields(manifest, ManifestV2, "manifest.json")
    _validate_field_types(manifest, ManifestV2, "manifest.json")
    session_id = manifest.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise SchemaV2Error("manifest.json requires non-empty session_id")

    # 先确认 Python 已正常停止，且 Mutagen 已完整同步两端事件分片；只有全部统计
    # 与实际行数一致后，才允许在本机发布可重建的最终 events.jsonl。
    manifest, python_event_rows, unity_event_rows = _merge_python_fragment(paths, manifest)
    merge_event_fragments(
        paths,
        session_id=session_id,
        expected_python_rows=python_event_rows,
        expected_unity_rows=unity_event_rows,
    )

    # 前四个数据文件各自只有一种固定行类型；events.jsonl 则承载
    # session_started、trial_started、runtime_error 等多种事件，不应锁死事件名。
    expected_events = ("python_candidate", "unity_reference", "unity_admission", "unity_render", None)
    row_types = (PythonCandidateRow, UnityReferenceRow, UnityAdmissionRow, UnityRenderRow, EventRow)
    tables = [
        _read_jsonl(path, session_id=session_id, expected_event=event, row_type=row_type)
        for path, event, row_type in zip(paths.jsonl_paths(), expected_events, row_types, strict=True)
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


def _read_jsonl(
    path: Path,
    *,
    session_id: str,
    expected_event: str | None,
    row_type: type[Any],
) -> pd.DataFrame:
    """读取单个 JSONL 文件并验证每行固定 schema。"""

    rows = _read_jsonl_rows(path, session_id=session_id, expected_event=expected_event, row_type=row_type)
    if rows:
        return pd.DataFrame.from_records(rows)
    return pd.DataFrame(columns=[item.name for item in fields(row_type)])


def _read_jsonl_rows(
    path: Path,
    *,
    session_id: str,
    expected_event: str | None,
    row_type: type[Any],
) -> list[dict[str, Any]]:
    """读取并验证 JSONL，保留原始字典供分片合并使用。"""

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
        _require_fields(row, row_type, f"{path.name}:{line_number}")
        _validate_field_types(row, row_type, f"{path.name}:{line_number}")
        _validate_stable_keys(row, row_type, f"{path.name}:{line_number}")
        rows.append(row)
    return rows


def _require_fields(row: dict[str, Any], row_type: type[Any], source: str) -> None:
    """按 schema dataclass 字段检查固定行必需键，允许额外诊断字段。"""

    required = {item.name for item in fields(row_type)}
    missing = sorted(required - row.keys())
    if missing:
        raise SchemaV2Error(f"{source}: missing required fields: {', '.join(missing)}")


def _validate_field_types(row: dict[str, Any], row_type: type[Any], source: str) -> None:
    """按 dataclass 注解严格验证 JSON 字段类型和定长 pose 向量。"""

    type_hints = get_type_hints(row_type)
    for item in fields(row_type):
        value = row[item.name]
        expected = type_hints[item.name]
        if not _matches_type(value, expected):
            raise SchemaV2Error(
                f"{source}: {item.name} has invalid type {type(value).__name__}; expected {expected}"
            )
        expected_length = _fixed_vector_length(item.name)
        if value is not None and expected_length is not None and len(value) != expected_length:
            raise SchemaV2Error(
                f"{source}: {item.name} must contain exactly {expected_length} values"
            )


def _matches_type(value: Any, expected: Any) -> bool:
    """验证 JSON 可表达值是否满足 dataclass 类型，拒绝 bool 冒充数值。"""

    if expected is Any:
        return True
    origin = get_origin(expected)
    arguments = get_args(expected)
    # Python 3.14 会把 ``T | None`` 的 origin 暴露为 typing.Union；
    # 早期版本则可能返回 types.UnionType，两种形式都必须按联合类型处理。
    if origin in (types.UnionType, Union):
        return any(_matches_type(value, item) for item in arguments)
    if origin is list:
        return isinstance(value, list) and all(_matches_type(item, arguments[0]) for item in value)
    if origin is dict:
        return isinstance(value, dict) and all(
            _matches_type(key, arguments[0]) and _matches_type(item, arguments[1])
            for key, item in value.items()
        )
    if expected is type(None):
        return value is None
    if expected is bool:
        return isinstance(value, bool)
    if expected is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if expected is float:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return False
        try:
            return math.isfinite(value)
        except OverflowError:
            return False
    if expected is str:
        return isinstance(value, str)
    return isinstance(value, expected)


def _fixed_vector_length(field_name: str) -> int | None:
    """返回 schema 中矩阵、位置和四元数数组的固定长度。"""

    if field_name == "pose_matrix_cv_camera":
        return 16
    if field_name.endswith("_pos"):
        return 3
    if field_name.endswith("_rot"):
        return 4
    return None


def _validate_stable_keys(row: dict[str, Any], row_type: type[Any], source: str) -> None:
    """验证跨表 join 和矩阵检查依赖的稳定键类型与取值范围。"""

    _nonempty_string(row, "session_id", source)
    _nonempty_string(row, "event", source)
    if row_type is PythonCandidateRow:
        _nonempty_string(row, "candidate_id", source)
        _bounded_int(row, "frame_id", source, minimum=0)
        _validate_candidate_id(row, source)
    elif row_type is UnityReferenceRow:
        _bounded_int(row, "frame_id", source, minimum=0)
    elif row_type is UnityAdmissionRow:
        _nonempty_string(row, "candidate_id", source)
        _nonempty_string(row, "variant_id", source)
        _bounded_int(row, "frame_id", source, minimum=0)
        _validate_candidate_id(row, source)
    elif row_type is UnityRenderRow:
        _nonempty_string(row, "variant_id", source)
        _bounded_int(row, "render_tick_id", source, minimum=0)
        _bounded_int(row, "source_frame_id", source, minimum=-1)
    elif row_type is EventRow:
        _nonempty_string(row, "event_type", source)


def _nonempty_string(row: dict[str, Any], key: str, source: str) -> None:
    """要求稳定字符串键为非空字符串。"""

    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise SchemaV2Error(f"{source}: {key} must be a non-empty string")


def _bounded_int(row: dict[str, Any], key: str, source: str, *, minimum: int) -> None:
    """要求稳定整数键不低于给定下界，并拒绝 bool 冒充整数。"""

    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise SchemaV2Error(f"{source}: {key} must be an integer >= {minimum}")


def _validate_candidate_id(row: dict[str, Any], source: str) -> None:
    """校验 candidate_id 的 session、frame 与 frame-local sequence 语义。"""

    candidate_id = str(row["candidate_id"])
    parts = candidate_id.rsplit(":", 2)
    if len(parts) != 3:
        raise SchemaV2Error(f"{source}: candidate_id must use session_id:frame_id:frame_local_seq")
    id_session, id_frame_text, sequence_text = parts
    try:
        id_frame = int(id_frame_text)
        sequence = int(sequence_text)
    except ValueError as exc:
        raise SchemaV2Error(f"{source}: candidate_id frame and sequence must be integers") from exc
    if id_session != row["session_id"] or id_frame != row["frame_id"] or sequence < 1:
        raise SchemaV2Error(f"{source}: candidate_id does not match session_id/frame_id or has invalid sequence")


def merge_event_fragments(
    session_dir: str | Path | EvalV2Paths,
    *,
    session_id: str | None = None,
    expected_python_rows: int | None = None,
    expected_unity_rows: int | None = None,
) -> dict[str, int]:
    """把 Python/Unity 事件分片确定性合并为最终 ``events.jsonl``。

    两个分片由 Mutagen 分别同步，不再争用同一个锁文件。发布前必须确认 Python
    已正常停止，且两个分片实际行数与各端冻结统计一致。合并按创建时间、来源、
    单调时间和规范 JSON 排序，结果通过临时文件原子替换；``events.jsonl`` 是派生
    文件，完整权威分片到齐后允许确定性重建。只有旧 ``events.jsonl`` 而没有两个
    分片的输入明确视为旧 schema。
    """

    paths = session_dir if isinstance(session_dir, EvalV2Paths) else EvalV2Paths.for_session(session_dir)
    expected_session = session_id
    if expected_session is None and paths.manifest.is_file():
        try:
            manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
            expected_session = manifest.get("session_id") if isinstance(manifest, dict) else None
        except (OSError, json.JSONDecodeError) as exc:
            raise SchemaV2Error(f"cannot read manifest.json before event merge: {exc}") from exc
    if not isinstance(expected_session, str) or not expected_session:
        raise SchemaV2Error("event merge requires non-empty session_id")

    _require_event_fragment_paths(paths)
    fragment_paths = (paths.python_events, paths.unity_events)
    if expected_python_rows is None or expected_unity_rows is None:
        if expected_python_rows is not None or expected_unity_rows is not None:
            raise ValueError("event merge expected row counts must be provided together")
        if not paths.manifest.is_file():
            raise SchemaV2Error("event merge requires manifest.json to validate frozen writer stats")
        try:
            manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SchemaV2Error(f"cannot read manifest.json before event merge: {exc}") from exc
        if not isinstance(manifest, dict):
            raise SchemaV2Error("manifest.json must contain an object")
        _, expected_python_rows, expected_unity_rows = _merge_python_fragment(paths, manifest)

    rows: list[tuple[int, dict[str, Any]]] = []
    for source_rank, path in enumerate(fragment_paths):
        fragment_rows = _read_jsonl_rows(
            path,
            session_id=expected_session,
            expected_event=None,
            row_type=EventRow,
        )
        for row in fragment_rows:
            row_source = str(row.get("source") or ("python_runtime" if source_rank == 0 else "unity"))
            row["source"] = row_source
            rows.append((source_rank, row))

    actual_python_rows = sum(1 for source_rank, _ in rows if source_rank == 0)
    actual_unity_rows = sum(1 for source_rank, _ in rows if source_rank == 1)
    if actual_python_rows != expected_python_rows:
        raise SchemaV2Error(
            f"python_events.jsonl row count {actual_python_rows} does not match "
            f"python writer stats {expected_python_rows}"
        )
    if actual_unity_rows != expected_unity_rows:
        raise SchemaV2Error(
            f"unity_events.jsonl row count {actual_unity_rows} does not match "
            f"Unity writer stats {expected_unity_rows}"
        )

    def sort_key(item: tuple[int, dict[str, Any]]) -> tuple[float, int, float, str, str, str]:
        """为跨机器事件提供不依赖 monotonic 时钟的稳定全序。"""

        source_rank, row = item
        created = float(row.get("created_unix_ms", 0.0))
        mono = float(row.get("mono_ms", 0.0))
        canonical = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return (
            created,
            source_rank,
            mono,
            str(row.get("event_type", row.get("event", ""))),
            str(row.get("event_id", "")),
            canonical,
        )

    rows.sort(key=sort_key)
    encoded = "".join(
        json.dumps(row, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
        for _, row in rows
    )
    try:
        existing_matches = paths.events.is_file() and paths.events.read_text(encoding="utf-8") == encoded
    except OSError as exc:
        raise SchemaV2Error(f"cannot read existing events.jsonl: {exc}") from exc
    if existing_matches:
        pass
    else:
        temporary = paths.events.with_name(f".{paths.events.name}.{uuid.uuid4().hex}.merge.tmp")
        try:
            temporary.write_text(encoded, encoding="utf-8", newline="\n")
            temporary.replace(paths.events)
        except OSError as exc:
            raise SchemaV2Error(f"cannot publish merged events.jsonl: {exc}") from exc
        finally:
            temporary.unlink(missing_ok=True)
    return {
        "python_rows": actual_python_rows,
        "unity_rows": actual_unity_rows,
        "rows": len(rows),
    }


def _merge_python_fragment(
    paths: EvalV2Paths,
    manifest: dict[str, Any],
) -> tuple[dict[str, Any], int, int]:
    """验证停止片段与事件分片，并合并 Python writer stats。"""

    fragment_path = paths.session_dir / _PYTHON_FRAGMENT_NAME
    if not fragment_path.is_file():
        raise SchemaV2Error(f"schema-v2 requires {_PYTHON_FRAGMENT_NAME}")
    try:
        fragment = json.loads(fragment_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SchemaV2Error(f"cannot read {_PYTHON_FRAGMENT_NAME}: {exc}") from exc
    if not isinstance(fragment, dict):
        raise SchemaV2Error(f"{_PYTHON_FRAGMENT_NAME} must contain an object")
    validate_schema_mapping(fragment)
    if fragment.get("session_id") != manifest.get("session_id"):
        raise SchemaV2Error(f"{_PYTHON_FRAGMENT_NAME} session_id does not match manifest")
    if fragment.get("object_id") != manifest.get("object_id"):
        raise SchemaV2Error(f"{_PYTHON_FRAGMENT_NAME} object_id does not match manifest")
    expected_files = {"python_candidates": "python_candidates.jsonl", "python_events": "python_events.jsonl"}
    if fragment.get("python_log_filename") != "python_candidates.jsonl":
        raise SchemaV2Error(f"{_PYTHON_FRAGMENT_NAME} requires python_log_filename=python_candidates.jsonl")
    if fragment.get("python_events_log_filename") != "python_events.jsonl":
        raise SchemaV2Error(
            f"{_PYTHON_FRAGMENT_NAME} requires python_events_log_filename=python_events.jsonl"
        )
    if fragment.get("log_files") != expected_files:
        raise SchemaV2Error(f"{_PYTHON_FRAGMENT_NAME}.log_files must equal fixed schema-v2 mapping")
    for key in ("python_host", "python_version"):
        value = fragment.get(key)
        if not isinstance(value, str) or not value.strip():
            raise SchemaV2Error(f"{_PYTHON_FRAGMENT_NAME}.{key} must be a non-empty string")

    if fragment.get("state") != "python_stopped":
        raise SchemaV2Error(
            f"{_PYTHON_FRAGMENT_NAME}.state must be python_stopped before event merge; "
            f"observed={fragment.get('state')!r}"
        )

    fragment_stats = fragment.get("log_writer_stats")
    if not isinstance(fragment_stats, dict):
        raise SchemaV2Error(f"{_PYTHON_FRAGMENT_NAME}.log_writer_stats must be an object")
    python_candidates = _python_stats(fragment_stats, "python_candidates.jsonl")
    python_events = _python_stats(fragment_stats, "python_events.jsonl")

    merged = deepcopy(manifest)
    stats = merged.get("log_writer_stats")
    if not isinstance(stats, dict):
        raise SchemaV2Error("manifest.log_writer_stats must be an object")
    stats["python_candidates.jsonl"] = {**python_candidates, "status": "merged"}

    event_stats = stats.get("events.jsonl")
    unity_events = event_stats.get("unity") if isinstance(event_stats, dict) else None
    if not isinstance(unity_events, dict):
        raise SchemaV2Error("manifest events.jsonl stats require unity source stats before merge")
    unity_rows = _nonnegative_int(unity_events, "rows_written", "manifest events unity stats")
    unity_dropped = _nonnegative_int(unity_events, "dropped_rows", "manifest events unity stats")
    unity_error = str(unity_events.get("write_error") or "")
    stats["events.jsonl"] = {
        "rows_written": unity_rows + python_events["rows_written"],
        "dropped_rows": unity_dropped + python_events["dropped_rows"],
        "log_write_failures": python_events["log_write_failures"] + int(bool(unity_error)),
        "write_error": unity_error,
        "status": "merged",
        "sources": {"unity": unity_events, "python": python_events},
    }
    merged["python_host"] = fragment["python_host"]
    merged["python_version"] = fragment["python_version"]
    _require_event_fragment_paths(paths)
    python_fragment_rows = _read_jsonl_rows(
        paths.python_events,
        session_id=str(manifest["session_id"]),
        expected_event=None,
        row_type=EventRow,
    )
    unity_fragment_rows = _read_jsonl_rows(
        paths.unity_events,
        session_id=str(manifest["session_id"]),
        expected_event=None,
        row_type=EventRow,
    )
    if len(python_fragment_rows) != python_events["rows_written"]:
        raise SchemaV2Error(
            f"python_events.jsonl row count {len(python_fragment_rows)} does not match "
            f"python writer stats {python_events['rows_written']}"
        )
    if len(unity_fragment_rows) != unity_rows:
        raise SchemaV2Error(
            f"unity_events.jsonl row count {len(unity_fragment_rows)} does not match "
            f"Unity writer stats {unity_rows}"
        )
    return merged, python_events["rows_written"], unity_rows


def _require_event_fragment_paths(paths: EvalV2Paths) -> None:
    """要求两个端的事件分片同时存在，并区分旧共享事件输入。"""

    fragment_paths = (paths.python_events, paths.unity_events)
    existing = [path for path in fragment_paths if path.is_file()]
    if not existing:
        if paths.events.is_file():
            raise SchemaV2Error(
                "events.jsonl is a legacy shared event file; expected python_events.jsonl and unity_events.jsonl"
            )
        raise SchemaV2Error("event merge requires python_events.jsonl and unity_events.jsonl")
    if len(existing) != len(fragment_paths):
        missing = ", ".join(path.name for path in fragment_paths if not path.is_file())
        raise SchemaV2Error(f"event merge is incomplete; missing fragment: {missing}")


def _python_stats(fragment_stats: dict[str, Any], name: str) -> dict[str, int]:
    """读取一个 Python writer 的完整非负统计。"""

    raw = fragment_stats.get(name)
    if not isinstance(raw, dict):
        raise SchemaV2Error(f"{_PYTHON_FRAGMENT_NAME} missing writer stats for {name}")
    return {
        "rows_written": _nonnegative_int(raw, "rows_written", f"{_PYTHON_FRAGMENT_NAME} {name}"),
        "dropped_rows": _nonnegative_int(raw, "dropped_rows", f"{_PYTHON_FRAGMENT_NAME} {name}"),
        "log_write_failures": _nonnegative_int(raw, "log_write_failures", f"{_PYTHON_FRAGMENT_NAME} {name}"),
    }


def _nonnegative_int(raw: dict[str, Any], key: str, source: str) -> int:
    """读取严格非负整数，拒绝 bool、null 和字符串伪装的统计。"""

    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SchemaV2Error(f"{source}.{key} must be a non-negative integer")
    return value


__all__ = [
    "EvalSessionV2",
    "join_candidate_admission",
    "join_render_reference",
    "load_session_v2",
    "select_completed_trials",
    "select_trials",
]

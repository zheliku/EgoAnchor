"""Stage 1 schema-v2 task 的只读流式解析与来源追踪。"""

from __future__ import annotations

import hashlib
import json
import math
import types
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Iterator, Mapping, Union, get_args, get_origin, get_type_hints

from ..schema_v2 import (
    EventRow,
    ManifestV2,
    PythonCandidateRow,
    SCHEMA_VERSION,
    SchemaV2Error,
    UnityAdmissionRow,
    UnityReferenceRow,
    UnityRenderRow,
    validate_schema_mapping,
)


JSON_DOCUMENT_FILES = ("manifest.json", "python_session.json")
"""Stage 1 必须读取的 JSON 文档。"""

JSONL_TABLE_FILES = {
    "python_candidates": "python_candidates.jsonl",
    "python_events": "python_events.jsonl",
    "unity_reference": "unity_reference.jsonl",
    "unity_admission": "unity_admission.jsonl",
    "unity_render": "unity_render.jsonl",
    "unity_events": "unity_events.jsonl",
    "events": "events.jsonl",
}
"""逻辑事实表到固定 JSONL 文件名的映射。"""

_ROW_CONTRACT_CACHE: dict[type[Any], tuple[tuple[str, Any], ...]] = {}
"""dataclass 类型到字段契约的进程内缓存。"""

EXPECTED_EVENTS = {
    "python_candidates": "python_candidate",
    "unity_reference": "unity_reference",
    "unity_admission": "unity_admission",
    "unity_render": "unity_render",
}
"""事件类型固定的 JSONL 表；事件流允许多种事件类型。"""

ROW_TYPES = {
    "python_candidates": PythonCandidateRow,
    "python_events": EventRow,
    "unity_reference": UnityReferenceRow,
    "unity_admission": UnityAdmissionRow,
    "unity_render": UnityRenderRow,
    "unity_events": EventRow,
    "events": EventRow,
}
"""各事实表使用的 schema-v2 dataclass 行契约。"""

REQUIRED_FILE_NAMES = JSON_DOCUMENT_FILES + tuple(JSONL_TABLE_FILES.values())
"""一个完整 schema-v2 task 的固定文件集合。"""


@dataclass(frozen=True, slots=True)
class SourceRow:
    """一条带原始来源位置与行摘要的 JSONL 行。"""

    source_file: str
    """相对 task 根目录的固定文件名。"""

    source_line: int
    """从 1 开始的物理行号。"""

    source_row_sha256: str
    """去除行尾换行符后原始 UTF-8 字节的 SHA-256。"""

    data: Mapping[str, Any]
    """解析后的 JSON 对象。"""

    def to_dict(self) -> dict[str, Any]:
        """返回包含来源字段和原始列的普通字典。"""

        return {
            "source_file": self.source_file,
            "source_line": self.source_line,
            "source_row_sha256": self.source_row_sha256,
            **dict(self.data),
        }


@dataclass(frozen=True, slots=True)
class NormalizedValue:
    """嵌套 JSON 叶节点或空容器的规范化记录。"""

    json_path: str
    """以点和方括号表达的稳定 JSON path。"""

    value_type: str
    """null、bool、int、float、text、object 或 array。"""

    value: Any
    """叶节点值；空容器保留为空 dict 或 list。"""

    def to_dict(self) -> dict[str, Any]:
        """返回可写入规范化子表的普通字典。"""

        return asdict(self)


@dataclass(frozen=True, slots=True)
class SourceFileInfo:
    """一个原始输入文件的存在性、容量、行数和完整摘要。"""

    relative_path: str
    """相对 task 根目录的固定路径。"""

    exists: bool
    """文件是否存在。"""

    byte_count: int
    """文件字节数。"""

    row_count: int
    """JSON 文档记为 1 行，JSONL 记实际物理行数。"""

    sha256: str
    """整个文件的 SHA-256。"""

    def to_dict(self) -> dict[str, Any]:
        """返回可写入 source_files sheet 的普通字典。"""

        return asdict(self)


@dataclass(frozen=True, slots=True)
class TaskDataset:
    """一个 schema-v2 task 的只读文档与事实表入口。"""

    root: Path
    """task 根目录。"""

    manifest: Mapping[str, Any]
    """manifest.json 对象。"""

    python_session: Mapping[str, Any]
    """python_session.json 对象。"""

    def iter_rows(self, table: str) -> Iterator[SourceRow]:
        """按逻辑表名重新打开文件并逐行返回来源行。"""

        try:
            filename = JSONL_TABLE_FILES[table]
        except KeyError as exc:
            raise KeyError(f"未知 schema-v2 事实表：{table}") from exc
        yield from iter_jsonl(
            self.root / filename,
            expected_event=EXPECTED_EVENTS.get(table),
            row_type=ROW_TYPES[table],
        )

    def source_files(self) -> tuple[SourceFileInfo, ...]:
        """计算全部固定输入文件的容量、行数和 SHA-256。"""

        return tuple(source_file_info(self.root / name) for name in REQUIRED_FILE_NAMES)


def read_task(task_dir: str | Path) -> TaskDataset:
    """读取 task 的两个 JSON 文档并返回流式事实表入口。"""

    root = Path(task_dir).expanduser()
    if not root.is_dir():
        raise SchemaV2Error(f"schema-v2 task 目录不存在：{root}")
    missing = [name for name in REQUIRED_FILE_NAMES if not (root / name).is_file()]
    if missing:
        raise SchemaV2Error(f"schema-v2 task 缺少固定文件：{', '.join(missing)}")

    manifest = read_json_document(root / "manifest.json")
    python_session = read_json_document(root / "python_session.json")
    _validate_row_contract(manifest, ManifestV2)
    return TaskDataset(root=root, manifest=manifest, python_session=python_session)


def read_json_document(path: str | Path) -> Mapping[str, Any]:
    """严格读取一个 UTF-8 JSON 对象文档。"""

    source = Path(path)
    try:
        raw = source.read_bytes()
        value = json.loads(raw.decode("utf-8-sig"), parse_constant=_reject_json_constant)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise SchemaV2Error(f"无法读取 JSON 文档 {source.name}：{exc}") from exc
    if not isinstance(value, dict):
        raise SchemaV2Error(f"JSON 文档必须是对象：{source.name}")
    return value


def iter_jsonl(
    path: str | Path,
    *,
    expected_event: str | None = None,
    row_type: type[Any] | None = None,
) -> Iterator[SourceRow]:
    """以二进制逐行读取 JSONL，并附加来源行号和原始行摘要。"""

    source = Path(path)
    try:
        handle = source.open("rb")
    except OSError as exc:
        raise SchemaV2Error(f"无法打开 JSONL 文件 {source.name}：{exc}") from exc

    with handle:
        for line_number, raw_with_newline in enumerate(handle, start=1):
            raw = raw_with_newline.rstrip(b"\r\n")
            if not raw.strip():
                raise SchemaV2Error(f"JSONL 不允许空行：{source.name}:{line_number}")
            try:
                row = json.loads(raw.decode("utf-8-sig"), parse_constant=_reject_json_constant)
            except (UnicodeDecodeError, ValueError) as exc:
                raise SchemaV2Error(f"JSONL 行无法解析：{source.name}:{line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise SchemaV2Error(f"JSONL 行必须是对象：{source.name}:{line_number}")
            try:
                validate_schema_mapping(row, expected_event=expected_event)
                if row_type is not None:
                    _validate_row_contract(row, row_type)
            except SchemaV2Error as exc:
                raise SchemaV2Error(f"{source.name}:{line_number}: {exc}") from exc
            yield SourceRow(
                source_file=source.name,
                source_line=line_number,
                source_row_sha256=hashlib.sha256(raw).hexdigest(),
                data=row,
            )


def flatten_json(value: Any, *, prefix: str = "") -> Iterator[NormalizedValue]:
    """确定性展开嵌套对象与数组，空容器也保留一条记录。"""

    if isinstance(value, Mapping):
        if not value:
            yield NormalizedValue(prefix, "object", {})
            return
        for key in sorted(value, key=str):
            child_path = _join_path(prefix, str(key))
            yield from flatten_json(value[key], prefix=child_path)
        return
    if isinstance(value, (list, tuple)):
        if not value:
            yield NormalizedValue(prefix, "array", [])
            return
        for index, item in enumerate(value):
            child_path = f"{prefix}[{index}]" if prefix else f"[{index}]"
            yield from flatten_json(item, prefix=child_path)
        return
    yield NormalizedValue(prefix, _value_type(value), value)


def source_file_info(path: str | Path) -> SourceFileInfo:
    """流式计算一个固定输入文件的行数和 SHA-256。"""

    source = Path(path)
    if not source.is_file():
        return SourceFileInfo(source.name, False, 0, 0, "")

    digest = hashlib.sha256()
    row_count = 0
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if source.suffix == ".jsonl":
        with source.open("rb") as handle:
            row_count = sum(1 for _ in handle)
    else:
        row_count = 1
    return SourceFileInfo(
        relative_path=source.name,
        exists=True,
        byte_count=source.stat().st_size,
        row_count=row_count,
        sha256=digest.hexdigest(),
    )


def _join_path(prefix: str, key: str) -> str:
    """连接对象键，保持根路径不带前导点。"""

    return f"{prefix}.{key}" if prefix else key


def _value_type(value: Any) -> str:
    """返回规范化子表使用的稳定 JSON 叶节点类型。"""

    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    return "text"


def _reject_json_constant(value: str) -> None:
    """拒绝 JSON 标准之外的 NaN 与 Infinity 常量。"""

    raise ValueError(f"JSON 不允许非有限常量：{value}")


def _validate_row_contract(row: Mapping[str, Any], row_type: type[Any]) -> None:
    """按 schema-v2 dataclass 检查全部固定字段和严格 JSON 类型。"""

    contract = _row_contract(row_type)
    missing = [name for name, _ in contract if name not in row]
    if missing:
        raise SchemaV2Error(f"缺少固定字段：{', '.join(missing)}")
    for name, annotation in contract:
        if not _matches_annotation(row[name], annotation):
            raise SchemaV2Error(
                f"字段 {name} 类型错误：期望 {annotation!s}，实际 {type(row[name]).__name__}"
            )


def _row_contract(row_type: type[Any]) -> tuple[tuple[str, Any], ...]:
    """缓存 dataclass 字段和解析后的类型提示，避免逐行重复反射。"""

    cached = _ROW_CONTRACT_CACHE.get(row_type)
    if cached is not None:
        return cached
    type_hints = get_type_hints(row_type)
    contract = tuple((field.name, type_hints.get(field.name, Any)) for field in fields(row_type))
    _ROW_CONTRACT_CACHE[row_type] = contract
    return contract


def _matches_annotation(value: Any, annotation: Any) -> bool:
    """按 dataclass 注解检查 JSON 值，float 接受整数但拒绝 bool。"""

    if annotation is Any:
        return True
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin in (types.UnionType, Union):
        return any(_matches_annotation(value, item) for item in args)
    if origin is list:
        return isinstance(value, list) and all(_matches_annotation(item, args[0]) for item in value)
    if origin is dict:
        return isinstance(value, dict) and all(
            _matches_annotation(key, args[0]) and _matches_annotation(item, args[1])
            for key, item in value.items()
        )
    if annotation is type(None):
        return value is None
    if annotation is bool:
        return type(value) is bool
    if annotation is int:
        return type(value) is int
    if annotation is float:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        )
    if annotation is str:
        return type(value) is str
    return isinstance(value, annotation)


__all__ = [
    "EXPECTED_EVENTS",
    "JSONL_TABLE_FILES",
    "ROW_TYPES",
    "REQUIRED_FILE_NAMES",
    "NormalizedValue",
    "SourceFileInfo",
    "SourceRow",
    "TaskDataset",
    "flatten_json",
    "iter_jsonl",
    "read_json_document",
    "read_task",
    "source_file_info",
]

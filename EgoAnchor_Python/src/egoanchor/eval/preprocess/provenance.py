"""Stage 1 工作簿的来源文件清单、摘要和可复现构建信息。"""

from __future__ import annotations

import hashlib
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from .reader import JSON_DOCUMENT_FILES, JSONL_TABLE_FILES


@dataclass(frozen=True, slots=True)
class SourceFileRecord:
    """一个 task 来源文件的相对路径、容量、行数和完整摘要。"""

    relative_path: str
    """相对 task 根目录的 POSIX 路径。"""

    source_kind: str
    """json_document、jsonl_table、audit_sample 或 other。"""

    exists: bool
    """生成清单时文件是否存在。"""

    byte_count: int
    """文件字节数。"""

    row_count: int
    """JSON 文档记一行、JSONL 记物理行数，其他文件记零行。"""

    sha256: str
    """文件完整字节的 SHA-256。"""

    def to_dict(self) -> dict[str, Any]:
        """返回可直接写入 source_files sheet 的普通字典。"""

        return asdict(self)


def collect_source_files(task_dir: str | Path) -> tuple[SourceFileRecord, ...]:
    """递归收集 task 目录中的全部文件并按相对路径稳定排序。"""

    root = Path(task_dir).expanduser()
    if not root.is_dir():
        raise FileNotFoundError(f"task 目录不存在：{root}")
    records = [_source_file_record(root, path) for path in root.rglob("*") if path.is_file()]
    records.sort(key=lambda item: item.relative_path)
    return tuple(records)


def source_set_sha256(files: Iterable[SourceFileRecord]) -> str:
    """计算有序 `relative_path\\0file_sha256\\n` 来源集合摘要。"""

    digest = hashlib.sha256()
    previous_path = ""
    for item in sorted(files, key=lambda record: record.relative_path):
        if previous_path and item.relative_path == previous_path:
            raise ValueError(f"来源文件相对路径重复：{item.relative_path}")
        previous_path = item.relative_path
        digest.update(item.relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.sha256.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def file_sha256(path: str | Path) -> str:
    """流式计算一个文件的 SHA-256。"""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reproducible_generated_at(manifest: Mapping[str, Any]) -> datetime:
    """返回无时区的 UTC 构建时间，优先使用 `SOURCE_DATE_EPOCH`。"""

    raw_epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if raw_epoch is not None:
        try:
            unix_seconds = float(raw_epoch)
        except ValueError as exc:
            raise ValueError("SOURCE_DATE_EPOCH 必须是 Unix 秒数") from exc
    else:
        created_unix_ms = manifest.get("created_unix_ms")
        if isinstance(created_unix_ms, bool) or not isinstance(created_unix_ms, (int, float)):
            raise ValueError("manifest.created_unix_ms 必须是有限数值")
        unix_seconds = float(created_unix_ms) / 1000.0
    return datetime.fromtimestamp(unix_seconds, tz=UTC).replace(tzinfo=None, microsecond=0)


def stable_workbook_id(session_id: str, source_digest: str) -> str:
    """由 session ID 和来源集合摘要构造稳定 workbook ID。"""

    if not session_id or len(source_digest) != 64:
        raise ValueError("session_id 和来源集合 SHA-256 必须有效")
    return f"{session_id}:{source_digest[:16]}"


def _source_file_record(root: Path, path: Path) -> SourceFileRecord:
    """读取一个已发现文件的来源记录。"""

    relative_path = path.relative_to(root).as_posix()
    return SourceFileRecord(
        relative_path=relative_path,
        source_kind=_source_kind(relative_path),
        exists=True,
        byte_count=path.stat().st_size,
        row_count=_row_count(path),
        sha256=file_sha256(path),
    )


def _source_kind(relative_path: str) -> str:
    """按固定输入路径返回稳定来源类别。"""

    if relative_path in JSON_DOCUMENT_FILES:
        return "json_document"
    if relative_path in JSONL_TABLE_FILES.values():
        return "jsonl_table"
    if relative_path.startswith("audit_samples/"):
        return "audit_sample"
    return "other"


def _row_count(path: Path) -> int:
    """返回 JSON/JSONL 的审计行数，非结构化文件返回零。"""

    if path.suffix.lower() == ".json":
        return 1
    if path.suffix.lower() != ".jsonl":
        return 0
    with path.open("rb") as handle:
        return sum(1 for _ in handle)


__all__ = [
    "SourceFileRecord",
    "collect_source_files",
    "file_sha256",
    "reproducible_generated_at",
    "source_set_sha256",
    "stable_workbook_id",
]

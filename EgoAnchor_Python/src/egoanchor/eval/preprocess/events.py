"""把 Python 与 Unity 事件分片确定性物化为最终事件总表。"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from egoanchor.utils import get_logger

from ..schema_v2 import EventRow, validate_schema_mapping
from .provenance import file_sha256
from .reader import iter_jsonl, read_json_document


_EVENT_FILE_NAME = "events.jsonl"
"""跨端事件分片的最终派生文件名。"""

_WINDOWS_FILE_RETRY_ATTEMPTS = 12
"""Windows 短暂共享锁下替换或清理文件的最大尝试次数。"""

_WINDOWS_FILE_RETRY_DELAY_SECONDS = 0.25
"""Windows 文件操作重试的基础等待秒数。"""

_STALE_MERGE_LOCK_SECONDS = 30.0
"""崩溃进程遗留事件物化锁的回收阈值。"""

LOGGER = get_logger(__name__, component="EvalEventMerge")
"""事件物化的统一日志门面。"""


def merged_event_text(
    fragment_events: Sequence[tuple[int, Mapping[str, Any]]],
) -> str:
    """按冻结跨进程全序序列化事件分片。

    参数：
        fragment_events: ``(source_rank, row)`` 序列；Python rank 为零，Unity rank 为一。
    """

    def sort_key(item: tuple[int, Mapping[str, Any]]) -> tuple[float, int, float, str, str, str]:
        """返回不跨进程比较单调时钟的稳定排序键。"""

        source_rank, row = item
        canonical = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return (
            float(row.get("created_unix_ms", 0.0)),
            source_rank,
            float(row.get("mono_ms", 0.0)),
            str(row.get("event_type") or row.get("event") or ""),
            str(row.get("event_id") or ""),
            canonical,
        )

    ordered = sorted(fragment_events, key=sort_key)
    return "".join(
        json.dumps(row, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
        for _, row in ordered
    )


def finalize_task_events(task_dir: str | Path) -> Path:
    """在缺少事件总表时验证双分片并原子生成派生文件。

    参数：
        task_dir: 已完成 Mutagen 同步的 schema-v2 task 目录。

    返回：
        已存在或新生成的 ``events.jsonl`` 路径。

    说明：
        已存在的事件总表不会在这里覆盖；其内容仍由后续只读 QC 验证。
    """

    root = Path(task_dir).expanduser()
    if not root.is_dir():
        raise FileNotFoundError(f"schema-v2 task 目录不存在：{root}")
    target = root / _EVENT_FILE_NAME
    with _event_merge_lock(root):
        if target.is_file():
            return target

        source_paths = tuple(
            root / name
            for name in (
                "manifest.json",
                "python_session.json",
                "python_events.jsonl",
                "unity_events.jsonl",
            )
        )
        source_hashes = {path: file_sha256(path) for path in source_paths}
        manifest = read_json_document(root / "manifest.json")
        python_session = read_json_document(root / "python_session.json")
        _validate_documents(manifest, python_session)
        session_id = str(manifest["session_id"])

        fragments: list[tuple[int, Mapping[str, Any]]] = []
        fragment_counts: dict[str, int] = {}
        for source_rank, filename in enumerate(("python_events.jsonl", "unity_events.jsonl")):
            rows = tuple(iter_jsonl(root / filename, row_type=EventRow))
            for source_row in rows:
                if source_row.data.get("session_id") != session_id:
                    raise ValueError(f"{filename}:{source_row.source_line} 的 session_id 与 manifest 不一致")
                fragments.append((source_rank, source_row.data))
            fragment_counts[filename] = len(rows)

        _validate_fragment_stats(manifest, python_session, fragment_counts)
        encoded = merged_event_text(fragments).encode("utf-8")

        def validate_sources() -> None:
            """确认当前来源仍与本轮开始时的字节快照一致。"""

            _ensure_sources_unchanged(source_paths, source_hashes)

        created = _atomic_write_new_file(target, encoded, validate_sources)
        try:
            validate_sources()
        except (OSError, ValueError) as source_error:
            if created:
                try:
                    _remove_owned_target(target, encoded)
                except OSError as cleanup_error:
                    source_error.add_note(f"陈旧 events.jsonl 撤回失败：{cleanup_error}")
            raise
        return target


def _ensure_sources_unchanged(
    source_paths: Sequence[Path],
    expected_hashes: Mapping[Path, str],
) -> None:
    """复算事件来源摘要，拒绝同步期间发生的任何字节变化。"""

    if any(file_sha256(path) != expected_hashes[path] for path in source_paths):
        raise ValueError("事件来源文件在 events.jsonl 物化期间发生变化，请等待同步完成后重试")


def _validate_documents(
    manifest: Mapping[str, Any],
    python_session: Mapping[str, Any],
) -> None:
    """验证事件物化所需的 schema、session 和固定文件声明。"""

    validate_schema_mapping(manifest)
    validate_schema_mapping(python_session)
    session_id = manifest.get("session_id")
    if not isinstance(session_id, str) or not session_id or python_session.get("session_id") != session_id:
        raise ValueError("manifest 与 python_session 的 session_id 必须一致且非空")
    if manifest.get("run_kind") != "formal":
        raise ValueError("生成 events.jsonl 前 manifest.run_kind 必须为 formal")
    if manifest.get("object_id") != python_session.get("object_id"):
        raise ValueError("manifest 与 python_session 的 object_id 必须一致")
    if python_session.get("state") != "python_stopped":
        raise ValueError("生成 events.jsonl 前 python_session.state 必须为 python_stopped")
    expected_manifest_files = {
        "python_candidates": "python_candidates.jsonl",
        "unity_reference": "unity_reference.jsonl",
        "unity_admission": "unity_admission.jsonl",
        "unity_render": "unity_render.jsonl",
        "events": "events.jsonl",
    }
    if manifest.get("log_files") != expected_manifest_files:
        raise ValueError("生成 events.jsonl 前 manifest.log_files 必须符合 schema-v2 固定映射")
    expected_python_files = {
        "python_candidates": "python_candidates.jsonl",
        "python_events": "python_events.jsonl",
    }
    if python_session.get("log_files") != expected_python_files:
        raise ValueError("生成 events.jsonl 前 python_session.log_files 必须符合 schema-v2 固定映射")


def _validate_fragment_stats(
    manifest: Mapping[str, Any],
    python_session: Mapping[str, Any],
    fragment_counts: Mapping[str, int],
) -> None:
    """验证两个分片的停止态统计、零丢行和零写入失败。"""

    python_stats = python_session.get("log_writer_stats")
    manifest_stats = manifest.get("log_writer_stats")
    if not isinstance(python_stats, Mapping) or not isinstance(manifest_stats, Mapping):
        raise ValueError("生成 events.jsonl 前两端 log_writer_stats 必须完整")
    _validate_single_fragment(
        "python_events.jsonl",
        python_stats.get("python_events.jsonl"),
        fragment_counts["python_events.jsonl"],
        is_python=True,
    )
    event_stats = manifest_stats.get("events.jsonl")
    unity_stats = event_stats.get("unity") if isinstance(event_stats, Mapping) else None
    _validate_single_fragment(
        "unity_events.jsonl",
        unity_stats,
        fragment_counts["unity_events.jsonl"],
        is_python=False,
    )


def _validate_single_fragment(
    filename: str,
    raw_stats: Any,
    actual_rows: int,
    *,
    is_python: bool,
) -> None:
    """验证一个事件分片的行数和 writer 停止态。"""

    if not isinstance(raw_stats, Mapping):
        raise ValueError(f"生成 events.jsonl 前缺少 {filename} writer 统计")
    rows_written = raw_stats.get("rows_written")
    dropped_rows = raw_stats.get("dropped_rows")
    if type(rows_written) is not int or rows_written != actual_rows:
        raise ValueError(f"{filename} 实际行数 {actual_rows} 与 writer 行数 {rows_written!r} 不一致")
    if type(dropped_rows) is not int or dropped_rows != 0:
        raise ValueError(f"{filename} dropped_rows 必须为 0")
    if is_python:
        failures = raw_stats.get("log_write_failures")
        if type(failures) is not int or failures != 0:
            raise ValueError(f"{filename} log_write_failures 必须为 0")
        return
    write_error = raw_stats.get("write_error")
    if not isinstance(write_error, str) or write_error:
        raise ValueError(f"{filename} write_error 必须为空字符串")


def _atomic_write_new_file(
    target: Path,
    content: bytes,
    validate_sources: Callable[[], None],
) -> bool:
    """写入并刷新临时文件，复核来源后以硬链接原子发布。"""

    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    active_error: BaseException | None = None
    created = False
    try:
        with temporary.open("xb", buffering=0) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        validate_sources()
        created = _link_with_retry(temporary, target)
        return created
    except BaseException as exc:
        active_error = exc
        raise
    finally:
        try:
            _unlink_with_retry(temporary)
        except OSError as cleanup_error:
            if active_error is not None:
                active_error.add_note(f"事件物化临时文件清理失败：{cleanup_error}")
            else:
                LOGGER.warning(
                    "events.jsonl 已发布或已由其他进程创建，但临时文件清理失败 path=%s error=%s",
                    temporary,
                    cleanup_error,
                )


def _link_with_retry(source: Path, destination: Path) -> bool:
    """原子发布完整文件；目标已存在时保持其字节不变。"""

    for attempt in range(_WINDOWS_FILE_RETRY_ATTEMPTS):
        try:
            os.link(source, destination)
            return True
        except FileExistsError:
            return False
        except PermissionError:
            if attempt + 1 == _WINDOWS_FILE_RETRY_ATTEMPTS:
                raise
            time.sleep(_WINDOWS_FILE_RETRY_DELAY_SECONDS * (attempt + 1))
    raise AssertionError("事件总表硬链接重试循环必须显式返回或抛出")


def _unlink_with_retry(path: Path) -> None:
    """清理临时文件，并对 Windows 短暂共享锁做有界重试。"""

    for attempt in range(_WINDOWS_FILE_RETRY_ATTEMPTS):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            if attempt + 1 == _WINDOWS_FILE_RETRY_ATTEMPTS:
                raise
            time.sleep(_WINDOWS_FILE_RETRY_DELAY_SECONDS * (attempt + 1))


def _remove_owned_target(target: Path, expected_content: bytes) -> None:
    """来源竞态发生时，仅删除本轮创建且字节仍未被外部修改的目标。"""

    expected_sha256 = hashlib.sha256(expected_content).hexdigest()
    try:
        if file_sha256(target) == expected_sha256:
            _unlink_with_retry(target)
    except FileNotFoundError:
        return


@contextmanager
def _event_merge_lock(root: Path) -> Iterator[None]:
    """在 task 内持有跨进程独占锁，串行化事件总表物化。"""

    lock_path = root / f".{_EVENT_FILE_NAME}.merge.lock"
    for attempt in range(_WINDOWS_FILE_RETRY_ATTEMPTS):
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(descriptor)
            break
        except (FileExistsError, PermissionError):
            _remove_stale_lock(lock_path)
            if attempt + 1 == _WINDOWS_FILE_RETRY_ATTEMPTS:
                raise TimeoutError(f"事件总表物化锁等待超时：{lock_path}")
            time.sleep(_WINDOWS_FILE_RETRY_DELAY_SECONDS * (attempt + 1))
    active_error: BaseException | None = None
    try:
        yield
    except BaseException as exc:
        active_error = exc
        raise
    finally:
        try:
            _unlink_with_retry(lock_path)
        except OSError as cleanup_error:
            if active_error is not None:
                active_error.add_note(f"事件物化锁清理失败：{cleanup_error}")
            else:
                LOGGER.warning("事件总表已处理，但物化锁清理失败 path=%s error=%s", lock_path, cleanup_error)


def _remove_stale_lock(lock_path: Path) -> None:
    """只回收超过阈值的崩溃遗留锁，不触碰活跃物化过程。"""

    try:
        if time.time() - lock_path.stat().st_mtime >= _STALE_MERGE_LOCK_SECONDS:
            lock_path.unlink(missing_ok=True)
    except (FileNotFoundError, PermissionError):
        return


__all__ = ["finalize_task_events"]

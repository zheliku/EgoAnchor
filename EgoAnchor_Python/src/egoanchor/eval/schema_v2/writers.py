"""schema-v2 严格 JSONL writer。"""

from __future__ import annotations

import json
import math
import os
import threading
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Mapping

from .rows import SCHEMA_VERSION, SchemaV2Error, validate_schema_mapping


class JsonlTableWriter:
    """将 schema-v2 行同步写入固定 JSONL 文件。

    writer 不丢行；任何非法行都会抛出并保持 `dropped_rows` 统计为零。每行 flush
    并可选地 `fsync`，便于 session 结束时对照 manifest 中的 writer stats。
    """

    def __init__(self, path: str | Path, *, expected_event: str | None = None, fsync: bool = False) -> None:
        """创建父目录并打开 UTF-8 JSONL 文件。"""

        self.path = Path(path)
        self.expected_event = expected_event
        self.fsync = fsync
        self.rows_written = 0
        self.dropped_rows = 0
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a", encoding="utf-8", newline="\n")

    def write(self, row: Mapping[str, Any] | Any) -> None:
        """校验并写入一行；拒绝 NaN/Infinity，非有限数序列化为 JSON null。"""

        data = _row_mapping(row)
        try:
            validate_schema_mapping(data, expected_event=self.expected_event)
            payload = _json_safe(data)
            encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        except (TypeError, ValueError, OverflowError, SchemaV2Error):
            self.dropped_rows += 1
            raise
        with self._lock:
            self._handle.write(encoded + "\n")
            self._handle.flush()
            if self.fsync:
                os.fsync(self._handle.fileno())
            self.rows_written += 1

    def close(self) -> None:
        """关闭文件句柄。"""

        if not self._handle.closed:
            self._handle.close()

    def __enter__(self) -> "JsonlTableWriter":
        """进入上下文管理器。"""

        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        """离开上下文时关闭文件。"""

        self.close()


def _row_mapping(row: Mapping[str, Any] | Any) -> dict[str, Any]:
    """将 dataclass 或 Mapping 归一为普通字典。"""

    to_dict = getattr(row, "to_dict", None)
    if callable(to_dict):
        data = to_dict()
        if isinstance(data, Mapping):
            return dict(data)
        raise TypeError("schema-v2 row to_dict() must return a Mapping")
    if is_dataclass(row) and not isinstance(row, type):
        return asdict(row)
    if isinstance(row, Mapping):
        return dict(row)
    raise TypeError("schema-v2 writer expects a Mapping or dataclass row")


def _json_safe(value: Any) -> Any:
    """把 NumPy 标量/数组及非有限浮点转换为 JSON 原生值。"""

    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except (TypeError, ValueError):
            pass
    if hasattr(value, "tolist"):
        try:
            return _json_safe(value.tolist())
        except (TypeError, ValueError):
            pass
    return value


__all__ = ["JsonlTableWriter"]

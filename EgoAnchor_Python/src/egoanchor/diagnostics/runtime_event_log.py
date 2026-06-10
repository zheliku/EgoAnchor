"""TrackingRuntime 结构化事件日志。"""

from __future__ import annotations

import json
import math
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO


class RuntimeEventLogger:
    """把论文实验关心的 runtime 事件写入 JSONL。

    日志器只做同步轻量写入，不理解 ZMQ/NATS/模型语义；TrackingRuntime 决定什么时候
    记录 pose、状态、心跳和命令事件。每个 Python 进程会话使用一个时间戳命名的
    JSONL 文件，便于按实验时间排序；跨端对齐仍依赖每行里的 session_id。
    """

    def __init__(
        self,
        *,
        enabled: bool,
        output_dir: str | Path,
        session_id: str | None = None,
        filename: str = "events.jsonl",
        flush_every: int = 1,
    ) -> None:
        """保存日志配置；启用时懒创建 session 文件。"""

        self.enabled = bool(enabled)
        """是否实际写入日志。"""

        self.output_dir = Path(output_dir).expanduser()
        """日志根目录；日志文件直接写在该目录下。"""

        self.session_id = str(session_id or uuid.uuid4().hex)
        """本次 Python server 会话 ID。"""

        self.timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        """当前日志文件时间戳，使用本地时间。"""

        self.filename = Path(str(filename or f"{self.timestamp}.jsonl")).name
        """JSONL 文件名；默认使用时间戳，且只取文件名避免在日志根目录下再建子目录。"""

        self.flush_every = max(1, int(flush_every))
        """每写入多少行 flush 一次。"""

        self._file: TextIO | None = None
        """当前打开的 JSONL 文件句柄。"""

        self._written_since_flush = 0
        """上一次 flush 之后写入的行数。"""

    @property
    def log_path(self) -> Path:
        """返回当前 JSONL 文件路径。"""

        return self.output_dir / self.filename

    def write(self, event: str, **fields: Any) -> None:
        """写入一条结构化事件。"""

        if not self.enabled:
            return

        row = {
            "event": str(event or ""),
            "session_id": self.session_id,
            "log_filename": self.filename,
            "created_unix_ms": time.time() * 1000.0,
            "mono_ms": time.monotonic() * 1000.0,
        }
        row.update(self._json_safe(fields))
        handle = self._ensure_file()
        handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")
        self._written_since_flush += 1
        if self._written_since_flush >= self.flush_every:
            handle.flush()
            self._written_since_flush = 0

    def close(self) -> None:
        """关闭日志文件。"""

        if self._file is None:
            return
        self._file.flush()
        self._file.close()
        self._file = None
        self._written_since_flush = 0

    def _ensure_file(self) -> TextIO:
        """懒创建日志根目录并打开 JSONL 文件。"""

        if self._file is None:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self._file = self.log_path.open("a", encoding="utf-8")
        return self._file

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        """把常见对象递归转换成 JSON 可写结构。"""

        if value is None or isinstance(value, (str, int, bool)):
            return value
        if isinstance(value, float):
            return value if math.isfinite(value) else None
        if isinstance(value, dict):
            return {str(key): cls._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [cls._json_safe(item) for item in value]
        if hasattr(value, "value"):
            return cls._json_safe(getattr(value, "value"))
        return str(value)


__all__ = ["RuntimeEventLogger"]

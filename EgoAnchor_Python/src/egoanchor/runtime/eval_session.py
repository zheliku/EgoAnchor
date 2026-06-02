"""Python 评估 session 目录协调。

Python 先启动时在 `data/eval/<session_id>/` 下写入 `python_session.json`，
Unity 录制开始时即可自动复用该目录，避免手动填写 runtime log 文件名。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class EvalSessionPaths:
    """一次 Python eval session 的目录与文件命名。"""

    session_id: str
    """人类可读 session id，例如 `20260602_155723_controller_right`。"""

    object_id: str
    """本次追踪对象 ID。"""

    session_dir: Path
    """共享 eval session 目录。"""

    python_log_filename: str
    """Python runtime JSONL 文件名。"""

    metadata_path: Path
    """Unity 自动配对读取的 metadata JSON 路径。"""


def create_eval_session(
    root: str | Path,
    object_id: str,
    *,
    now: datetime | None = None,
    metadata_filename: str = "python_session.json",
    python_log_filename: str = "",
) -> EvalSessionPaths:
    """创建一个可被 Unity 自动复用的 Python eval session 目录。"""

    root_path = Path(root).expanduser()
    safe_object_id = sanitize_session_token(object_id or "default")
    session_id = _resolve_unique_session_id(root_path, build_eval_session_id(now or datetime.now(), safe_object_id))
    session_dir = root_path / session_id
    session_dir.mkdir(parents=True, exist_ok=False)
    log_filename = Path(python_log_filename).name if python_log_filename else f"{session_id}_python_runtime.jsonl"
    metadata_path = session_dir / Path(metadata_filename).name
    paths = EvalSessionPaths(
        session_id=session_id,
        object_id=safe_object_id,
        session_dir=session_dir,
        python_log_filename=log_filename,
        metadata_path=metadata_path,
    )
    write_python_session_metadata(paths)
    return paths


def write_python_session_metadata(paths: EvalSessionPaths) -> None:
    """写出 Unity 侧自动配对需要的 Python session metadata。"""

    created_unix_ms = time.time() * 1000.0
    metadata = {
        "session_id": paths.session_id,
        "object_id": paths.object_id,
        "python_log_filename": paths.python_log_filename,
        "python_log_relative_path": paths.python_log_filename,
        "created_unix_ms": created_unix_ms,
        "created_utc": datetime.fromtimestamp(created_unix_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "state": "python_started",
    }
    paths.metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")


def build_eval_session_id(now: datetime, object_id: str) -> str:
    """按本地时间和对象 ID 构造 `yyyyMMdd_HHmmss_object` session id。"""

    return f"{now.strftime('%Y%m%d_%H%M%S')}_{sanitize_session_token(object_id or 'default')}"


def sanitize_session_token(value: str) -> str:
    """把对象名转换为可用于目录名的短 token。"""

    token = re.sub(r"[^0-9A-Za-z_-]+", "_", str(value or "")).strip("_-")
    return token or "default"


def _resolve_unique_session_id(root: Path, base_session_id: str) -> str:
    """同秒重复启动时追加 `_02`、`_03` 等后缀。"""

    candidate = base_session_id
    suffix = 2
    while (root / candidate).exists():
        candidate = f"{base_session_id}_{suffix:02d}"
        suffix += 1
    return candidate


__all__ = [
    "EvalSessionPaths",
    "build_eval_session_id",
    "create_eval_session",
    "sanitize_session_token",
    "write_python_session_metadata",
]

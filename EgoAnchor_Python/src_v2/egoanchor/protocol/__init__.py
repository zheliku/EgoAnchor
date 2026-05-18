"""EgoAnchor v2 protocol 包级入口。

本模块集中导出：
- v2 生成的 Protobuf Python 模块；
- `subjects.v1.json` 中定义的逻辑 channel 常量；
- 读取 subject 契约的小工具。

业务代码优先从 `egoanchor.protocol` 导入，避免散落到生成代码目录。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from egoanchor.protocol.v1 import anchor_pb2, common_pb2, quest_pb2


QUEST_STEREO = "egoanchor.v1.quest.stereo"
QUEST_CAMERA_INFO = "egoanchor.v1.quest.camera_info"
POSE_RESULT = "egoanchor.v1.pose.result"
ANCHOR_STATUS = "egoanchor.v1.anchor.status"
SERVER_HEARTBEAT = "egoanchor.v1.server.heartbeat"
CMD_ANCHOR_RESET = "egoanchor.v1.cmd.anchor.reset"
CMD_ANCHOR_REACQUIRE = "egoanchor.v1.cmd.anchor.reacquire"
CMD_ANCHOR_CONTROL = "egoanchor.v1.cmd.anchor.control"


@dataclass(frozen=True)
class SubjectSpec:
    """`subjects.v1.json` 中单个逻辑 channel 的契约。"""

    name: str
    transport: str
    direction: str
    protobuf: str
    mode: str
    latest_only: bool | None = None
    reply: str | None = None
    idempotent_by: str | None = None


def _repo_root() -> Path:
    """返回仓库根目录 EgoAnchor。"""

    return Path(__file__).resolve().parents[4]


def default_subjects_path() -> Path:
    """返回共享 subjects 契约文件路径。"""

    return _repo_root() / "EgoAnchor_Protocol" / "subjects.v1.json"


@lru_cache(maxsize=4)
def _load_subjects_cached(subjects_path: str) -> dict[str, SubjectSpec]:
    path = Path(subjects_path)
    with path.open("r", encoding="utf-8") as f:
        raw: dict[str, dict[str, Any]] = json.load(f)

    return {
        name: SubjectSpec(
            name=name,
            transport=str(spec.get("transport", "")),
            direction=str(spec.get("direction", "")),
            protobuf=str(spec.get("protobuf", "")),
            mode=str(spec.get("mode", "")),
            latest_only=spec.get("latest_only"),
            reply=spec.get("reply"),
            idempotent_by=spec.get("idempotent_by"),
        )
        for name, spec in raw.items()
    }


def load_subjects(subjects_path: str | Path | None = None) -> dict[str, SubjectSpec]:
    """读取 v2 逻辑 channel 契约。"""

    path = Path(subjects_path) if subjects_path is not None else default_subjects_path()
    return dict(_load_subjects_cached(str(path.resolve())))


__all__ = [
    "ANCHOR_STATUS",
    "CMD_ANCHOR_CONTROL",
    "CMD_ANCHOR_REACQUIRE",
    "CMD_ANCHOR_RESET",
    "POSE_RESULT",
    "QUEST_CAMERA_INFO",
    "QUEST_STEREO",
    "SERVER_HEARTBEAT",
    "SubjectSpec",
    "anchor_pb2",
    "common_pb2",
    "default_subjects_path",
    "load_subjects",
    "quest_pb2",
]
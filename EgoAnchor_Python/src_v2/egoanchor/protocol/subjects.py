"""v2 逻辑 channel 契约读取与常量。

subjects.v1.json 是 Python/Unity v2 的唯一 channel 契约来源。
本模块只做轻量读取和校验，不负责网络连接，也不负责 Protobuf 编解码。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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
    """单个逻辑 channel 的契约信息。"""

    name: str
    transport: str
    direction: str
    protobuf: str
    mode: str
    latest_only: bool = False
    reply: str | None = None
    idempotent_by: str | None = None


def default_subjects_path() -> Path:
    """返回仓库内 subjects.v1.json 的默认位置。"""

    return Path(__file__).resolve().parents[4] / "EgoAnchor_Protocol" / "subjects.v1.json"


def load_subjects(path: str | Path | None = None) -> dict[str, SubjectSpec]:
    """读取 subjects.v1.json 并转换为 SubjectSpec 字典。"""

    subjects_path = default_subjects_path() if path is None else Path(path)
    with subjects_path.open("r", encoding="utf-8") as f:
        raw: dict[str, dict[str, Any]] = json.load(f)

    specs: dict[str, SubjectSpec] = {}
    for name, item in raw.items():
        specs[name] = SubjectSpec(
            name=name,
            transport=str(item["transport"]),
            direction=str(item["direction"]),
            protobuf=str(item["protobuf"]),
            mode=str(item["mode"]),
            latest_only=bool(item.get("latest_only", False)),
            reply=item.get("reply"),
            idempotent_by=item.get("idempotent_by"),
        )
    return specs


def zmq_data_plane_topics(path: str | Path | None = None) -> list[str]:
    """返回 v2 ZMQ 数据面需要订阅的 topic 列表。

    目前应包含：
    - egoanchor.v1.quest.stereo
    - egoanchor.v1.quest.camera_info
    """

    specs = load_subjects(path)
    return [name for name, spec in specs.items() if spec.transport == "zmq"]

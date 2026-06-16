"""共享 subject 契约读取与常量定义。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

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
    """`subjects.v1.json` 中单个逻辑 channel 的结构化描述。"""

    name: str
    transport: str
    direction: str
    protobuf: str
    mode: str
    latest_only: bool | None = None
    reply: str | None = None
    idempotent_by: str | None = None


class SubjectRegistry:
    """共享 subject 契约注册表。"""

    def __init__(self, specs: dict[str, SubjectSpec]) -> None:
        """保存 subject -> spec 映射。"""

        self._specs = dict(specs)

    @classmethod
    def load(cls, subjects_path: str | Path | None = None) -> "SubjectRegistry":
        """从默认或指定路径加载 subject 契约。"""

        return cls(load_subjects(subjects_path))

    def require(self, name: str) -> SubjectSpec:
        """读取指定 subject；不存在时抛出清晰错误。"""

        try:
            return self._specs[name]
        except KeyError as exc:
            raise KeyError(f"subjects 契约中未定义 {name!r}") from exc

    def by_transport(self, transport: str) -> list[SubjectSpec]:
        """按传输类型过滤 subject，例如 `zmq` 或 `nats`。"""

        return [spec for spec in self._specs.values() if spec.transport == transport]

    def by_mode(self, mode: str) -> list[SubjectSpec]:
        """按通信模式过滤 subject，例如 `pubsub` 或 `request_reply`。"""

        return [spec for spec in self._specs.values() if spec.mode == mode]

    def names(self) -> tuple[str, ...]:
        """返回所有 subject 名称，顺序按字典插入顺序保留。"""

        return tuple(self._specs.keys())

    def ensure_defined(self, names: Iterable[str]) -> None:
        """批量校验 subject 是否存在。"""

        for name in names:
            self.require(name)


def _protocol_root() -> Path:
    """返回 Python 运行时随包携带的协议资源目录。"""

    return Path(__file__).resolve().parent


def default_subjects_path() -> Path:
    """返回共享 subject 契约文件路径。"""

    return _protocol_root() / "subjects.v1.json"


@lru_cache(maxsize=4)
def _load_subjects_cached(subjects_path: str) -> dict[str, SubjectSpec]:
    """读取并缓存 subject 契约，避免每帧重复解析 JSON。"""

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
    """加载共享 subject 契约并返回普通字典副本。"""

    path = Path(subjects_path) if subjects_path is not None else default_subjects_path()
    return dict(_load_subjects_cached(str(path.resolve())))

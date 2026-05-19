"""v3 runtime command 数据模型。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum

from google.protobuf.message import Message


class CommandType(str, Enum):
    """v3 runtime 当前支持的命令类型。"""

    RESET = "reset"
    REACQUIRE = "reacquire"
    CONTROL = "control"


@dataclass(frozen=True, slots=True)
class RuntimeCommand:
    """已接受、等待 TrackingRuntime 在 frame 边界执行的命令。"""

    command_type: CommandType
    request_id: str
    anchor_id: str
    message: Message
    created_mono_ms: float

    @classmethod
    def from_message(cls, command_type: CommandType, message: Message) -> "RuntimeCommand":
        """从 protobuf command message 中提取 header 并构造 runtime command。"""

        header = getattr(message, "header", None)
        return cls(
            command_type=command_type,
            request_id=str(getattr(header, "request_id", "")),
            anchor_id=str(getattr(header, "anchor_id", "")),
            message=message,
            created_mono_ms=time.monotonic() * 1000.0,
        )


__all__ = ["CommandType", "RuntimeCommand"]
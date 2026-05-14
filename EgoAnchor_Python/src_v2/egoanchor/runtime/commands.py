from __future__ import annotations

"""
v2 command queue。

NATS request handler 只负责“接受/拒绝命令并快速 ack”，不能直接执行 GPU
pipeline 操作。本队列用于把 reset/reacquire/control 命令交给后续单一
TrackingRuntime 顺序执行。

当前实现是内存优先级队列：reset/reacquire 优先级高于普通 control。
"""

import heapq
import itertools
import time
from dataclasses import dataclass, field
from enum import Enum

from google.protobuf.message import Message


class CommandType(str, Enum):
    """v2 runtime 当前认识的命令类型。"""

    RESET = "reset"
    REACQUIRE = "reacquire"
    CONTROL = "control"


_PRIORITY = {
    CommandType.RESET: 0,
    CommandType.REACQUIRE: 0,
    CommandType.CONTROL: 10,
}


@dataclass(order=True)
class _QueueItem:
    priority: int
    sequence: int
    command: "QueuedCommand" = field(compare=False)


@dataclass(frozen=True)
class QueuedCommand:
    """已接受、等待 runtime 执行的命令对象。"""

    command_type: CommandType
    request_id: str
    anchor_id: str
    message: Message
    created_mono_ms: float


class CommandQueue:
    """轻量内存命令队列。

    第一阶段不做持久化，也不跨进程共享；如果队列满，handler 返回 rejected ack。
    """

    def __init__(self, max_size: int = 128) -> None:
        self._max_size = max(1, max_size)
        self._items: list[_QueueItem] = []
        self._seq = itertools.count()

    def put(self, command: QueuedCommand) -> bool:
        """按优先级入队；队列满时返回 False。"""
        if len(self._items) >= self._max_size:
            return False
        heapq.heappush(
            self._items,
            _QueueItem(_PRIORITY.get(command.command_type, 100), next(self._seq), command),
        )
        return True

    def accept(self, command_type: CommandType, message: Message) -> bool:
        """从 protobuf command message 中提取 header 并入队。"""
        header = getattr(message, "header", None)
        request_id = str(getattr(header, "request_id", ""))
        anchor_id = str(getattr(header, "anchor_id", ""))
        return self.put(
            QueuedCommand(
                command_type=command_type,
                request_id=request_id,
                anchor_id=anchor_id,
                message=message,
                created_mono_ms=time.monotonic() * 1000.0,
            )
        )

    def get_nowait(self) -> QueuedCommand | None:
        """非阻塞取出一个命令；空队列返回 None。"""
        if not self._items:
            return None
        return heapq.heappop(self._items).command

    def drain(self) -> list[QueuedCommand]:
        """一次性取出全部命令，保持优先级顺序。"""
        out: list[QueuedCommand] = []
        while self._items:
            out.append(heapq.heappop(self._items).command)
        return out

    def __len__(self) -> int:
        """当前队列长度。"""
        return len(self._items)

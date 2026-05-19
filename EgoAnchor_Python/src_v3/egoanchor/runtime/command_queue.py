"""v3 command queue。

NATS request handler 只 ack/enqueue，不直接执行 pipeline 操作。
TrackingRuntime 在主循环 frame 边界 drain 队列并顺序执行命令。
"""

from __future__ import annotations

import heapq
import itertools
import threading
from dataclasses import dataclass, field

from google.protobuf.message import Message

from egoanchor.runtime import CommandType, RuntimeCommand

_PRIORITY = {
    CommandType.RESET: 0,
    CommandType.REACQUIRE: 0,
    CommandType.CONTROL: 10,
}


@dataclass(order=True)
class _QueueItem:
    priority: int
    sequence: int
    command: RuntimeCommand = field(compare=False)


class CommandQueue:
    """线程安全轻量优先级命令队列。"""

    def __init__(self, max_size: int = 128) -> None:
        self._max_size = max(1, int(max_size))
        self._items: list[_QueueItem] = []
        self._seq = itertools.count()
        self._lock = threading.Lock()

    def put(self, command: RuntimeCommand) -> bool:
        """按优先级入队；队列满时返回 False。"""

        with self._lock:
            if len(self._items) >= self._max_size:
                return False
            heapq.heappush(self._items, _QueueItem(_PRIORITY.get(command.command_type, 100), next(self._seq), command))
            return True

    def accept(self, command_type: CommandType, message: Message) -> bool:
        """从 protobuf command message 构造 RuntimeCommand 并入队。"""

        return self.put(RuntimeCommand.from_message(command_type, message))

    def drain(self) -> list[RuntimeCommand]:
        """一次性取出全部命令，保持优先级顺序。"""

        with self._lock:
            out: list[RuntimeCommand] = []
            while self._items:
                out.append(heapq.heappop(self._items).command)
            return out

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


__all__ = ["CommandQueue"]
"""v2 command queue。

NATS request handler 后续只负责 parse/ack/enqueue，不直接调用 GPU 或 pipeline。
TrackingRuntime 再从该队列顺序消费命令，保证状态所有权清晰。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque


@dataclass(frozen=True)
class RuntimeCommand:
    """运行时命令的最小表示。"""

    command_type: str
    request_id: str
    anchor_id: str = ""
    action: str = ""
    stage: int | None = None


class CommandQueue:
    """单生产/单消费命令队列。"""

    def __init__(self) -> None:
        self._items: Deque[RuntimeCommand] = deque()

    def push(self, command: RuntimeCommand) -> None:
        self._items.append(command)

    def pop(self) -> RuntimeCommand | None:
        if not self._items:
            return None
        return self._items.popleft()

    def __len__(self) -> int:
        return len(self._items)

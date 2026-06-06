"""handler registry。

handler 只做 protobuf 已解析后的轻量校验、dedup、写 command queue 和快速 ack。
它不直接调用 GPU pipeline，也不直接改 FoundationPose/Cutie 状态。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from google.protobuf.message import Message


@dataclass(slots=True)
class HandlerContext:
    """handler 执行上下文。

    routing 层不绑定具体 runtime 类型；测试可注入 fake queue/dedup。
    """

    commands: object | None = None
    dedup: object | None = None


class Handler(Protocol):
    """subject handler 函数协议。"""

    def __call__(self, ctx: HandlerContext, message: Message) -> Message | None: ...


class HandlerRegistry:
    """subject -> handler 的注册与分发器。"""

    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    def request(self, subject: str) -> Callable[[Handler], Handler]:
        """注册 request/reply handler。"""

        def decorator(handler: Handler) -> Handler:
            if subject in self._handlers:
                raise ValueError(f"handler already registered for subject={subject!r}")
            self._handlers[subject] = handler
            return handler

        return decorator

    def get(self, subject: str) -> Handler:
        """读取 subject 对应 handler；未注册时抛出清晰错误。"""

        try:
            return self._handlers[subject]
        except KeyError as exc:
            raise KeyError(f"no handler registered for subject={subject!r}") from exc

    def dispatch(self, subject: str, ctx: HandlerContext, message: Message) -> Message | None:
        """调用同步 handler 并返回可选 reply message。"""

        return self.get(subject)(ctx, message)


__all__ = ["Handler", "HandlerContext", "HandlerRegistry"]

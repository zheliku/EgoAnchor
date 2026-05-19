"""v3 handler registry。

handler 只做 protobuf 已解析后的轻量校验、dedup、写 command queue 和快速 ack。
它不直接调用 GPU pipeline，也不直接改 FoundationPose/Cutie 状态。
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
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

    def __call__(self, ctx: HandlerContext, message: Message) -> Message | None | Awaitable[Message | None]: ...


class HandlerRegistry:
    """subject -> handler 的注册与分发器。"""

    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    def request(self, subject: str) -> Callable[[Handler], Handler]:
        """注册 request/reply handler。"""

        return self._register(subject)

    def subscribe(self, subject: str) -> Callable[[Handler], Handler]:
        """注册 pub/sub handler。v3 首期主要预留给未来 Python 接收配置/调试消息。"""

        return self._register(subject)

    def get(self, subject: str) -> Handler:
        """读取 subject 对应 handler；未注册时抛出清晰错误。"""

        try:
            return self._handlers[subject]
        except KeyError as exc:
            raise KeyError(f"no handler registered for subject={subject!r}") from exc

    async def dispatch(self, subject: str, ctx: HandlerContext, message: Message) -> Message | None:
        """调用 handler，并兼容同步/异步返回。"""

        result = self.get(subject)(ctx, message)
        if inspect.isawaitable(result):
            return await result
        return result

    def subjects(self) -> tuple[str, ...]:
        """返回已注册 subject 列表。"""

        return tuple(self._handlers.keys())

    def _register(self, subject: str) -> Callable[[Handler], Handler]:
        def decorator(handler: Handler) -> Handler:
            if subject in self._handlers:
                raise ValueError(f"handler already registered for subject={subject!r}")
            self._handlers[subject] = handler
            return handler

        return decorator


__all__ = ["Handler", "HandlerContext", "HandlerRegistry"]
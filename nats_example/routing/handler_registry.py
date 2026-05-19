from __future__ import annotations

"""
v2 handler registry。

职责：把 subject 绑定到轻量 handler 函数。

约束：
- handler 只做 protobuf 已解析后的轻量校验、写 latest store、写 command queue；
- handler 不直接调用 GPU pipeline，也不调用 `pipeline.reset_tracking_state()`；
- 真正会改变 tracking 状态的操作必须由后续单一 `TrackingRuntime` 顺序执行。
"""

import inspect
from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol

from google.protobuf.message import Message


@dataclass
class HandlerContext:
    """handler 执行时可访问的上下文对象。

    这里用 object 类型是为了让 registry 保持轻量，不把 routing 层绑定到具体
    runtime 实现；测试中也可以传 fake store/queue。
    """

    latest_inputs: object | None = None
    commands: object | None = None
    dedup: object | None = None


class Handler(Protocol):
    def __call__(self, ctx: HandlerContext, message: Message) -> Message | None | Awaitable[Message | None]: ...


class HandlerRegistry:
    """subject -> handler 的注册和分发器。"""

    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    def subscribe(self, subject: str) -> Callable[[Handler], Handler]:
        """注册 pub/sub handler 的装饰器。"""
        return self._register(subject)

    def request(self, subject: str) -> Callable[[Handler], Handler]:
        """注册 request/reply handler 的装饰器。"""
        return self._register(subject)

    def _register(self, subject: str) -> Callable[[Handler], Handler]:
        def decorator(handler: Handler) -> Handler:
            if subject in self._handlers:
                raise ValueError(f"Handler already registered for {subject}")
            self._handlers[subject] = handler
            return handler

        return decorator

    def get(self, subject: str) -> Handler:
        """获取 subject 对应 handler；没有注册说明 server 组装不完整。"""
        try:
            return self._handlers[subject]
        except KeyError as exc:
            raise KeyError(f"No handler registered for {subject}") from exc

    async def dispatch(self, subject: str, ctx: HandlerContext, message: Message) -> Message | None:
        """调用 handler，并兼容同步/异步 handler。"""
        result = self.get(subject)(ctx, message)
        if inspect.isawaitable(result):
            return await result
        return result

    def subjects(self) -> tuple[str, ...]:
        """返回已注册 handler 的 subject 列表，主要用于测试和诊断。"""
        return tuple(self._handlers.keys())

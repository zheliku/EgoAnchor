from __future__ import annotations

"""
Python v2 NATS transport adapter。

本类只封装 nats-py 的连接、publish、request、subscribe，不理解 EgoAnchor 的
pose/anchor/pipeline 语义。这样后续替换 transport 或调整重连策略时，不会影响
handler/runtime 业务代码。

本模块直接依赖 nats-py。也就是说：如果要运行 v2 server，环境必须已经安装
`nats-py`；协议/handler 单测若不触碰 transport，也不会导入本模块。
"""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from nats.aio.client import Client as _Nats  # type: ignore


MessageCallback = Callable[[str, bytes, str | None], Awaitable[bytes | None]]


@dataclass
class SubscriptionHandle:
    raw: Any


class NatsClient:
    """Core NATS 轻量封装。"""

    def __init__(self, url: str = "nats://127.0.0.1:4222", name: str = "egoanchor-python-v2") -> None:
        self.url = url
        self.name = name
        self._nc: Any = None

    async def connect(self) -> None:
        """连接 NATS server。"""
        if self._nc is not None:
            return
        self._nc = _Nats()
        await self._nc.connect(servers=[self.url], name=self.name)

    async def publish(self, subject: str, payload: bytes) -> None:
        """发布 bytes payload 到 subject。"""
        await self._nc.publish(subject, payload)

    async def request(self, subject: str, payload: bytes, timeout: float = 2.0) -> bytes:
        """发送 request/reply，返回 reply bytes。"""
        reply = await self._nc.request(subject, payload, timeout=timeout)
        return bytes(reply.data)

    async def subscribe(self, subject: str, callback: MessageCallback) -> SubscriptionHandle:
        """订阅 subject，并把 NATS msg 转为 `(subject, data, reply)` 回调。"""
        async def _wrapped(msg: Any) -> None:
            response = await callback(str(msg.subject), bytes(msg.data), getattr(msg, "reply", None) or None)
            if msg.reply and response is not None:
                await self._nc.publish(msg.reply, response)

        sub = await self._nc.subscribe(subject, cb=_wrapped)
        return SubscriptionHandle(sub)

    async def close(self) -> None:
        """Drain 并关闭连接。"""
        if self._nc is not None:
            await self._nc.drain()
            await self._nc.close()
            self._nc = None

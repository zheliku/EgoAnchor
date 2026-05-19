from __future__ import annotations

"""
NATS subject router。

Router 是 transport 和应用 handler 之间的桥：
1. 根据 subject registry 找到 protobuf 类型；
2. 用 protobuf registry 把 bytes parse 成 message；
3. 调 handler registry；
4. 对 request/reply subject，把 handler 返回的 protobuf 序列化为 reply bytes。

Router 不包含 pipeline 业务逻辑，也不写 if-else 分支判断具体命令类型。
"""

import logging

from egoanchor.routing.handler_registry import HandlerContext, HandlerRegistry
from egoanchor.routing.protobuf_registry import ProtobufRegistry
from egoanchor.routing.subjects import SubjectRegistry

LOGGER = logging.getLogger(__name__)


class NatsRouter:
    """基于 subject registry 的 NATS 消息分发器。"""

    def __init__(
        self,
        subjects: SubjectRegistry,
        protobufs: ProtobufRegistry,
        handlers: HandlerRegistry,
        context: HandlerContext,
    ) -> None:
        self._subjects = subjects
        self._protobufs = protobufs
        self._handlers = handlers
        self._context = context

    async def handle_message(self, subject: str, payload: bytes, reply: str | None = None) -> bytes | None:
        """处理一条 NATS 消息，供真实 NATS callback 或单测直接调用。"""
        spec = self._subjects.get(subject)
        try:
            message = self._protobufs.parse(spec.protobuf, payload)
            result = await self._handlers.dispatch(subject, self._context, message)
            if spec.is_request_reply:
                if result is None:
                    raise RuntimeError(f"Request handler returned no reply for {subject}")
                response = self._protobufs.serialize(result)
                LOGGER.debug("[v2.router] request subject=%s reply_bytes=%d", subject, len(response))
                return response
            LOGGER.debug("[v2.router] pubsub subject=%s payload_bytes=%d", subject, len(payload))
            return None
        except Exception:
            LOGGER.exception("EgoAnchor v2 router failed subject=%s reply=%s", subject, bool(reply))
            raise

    async def attach(self, client: object) -> None:
        """把所有 Unity->Python subject 注册到 NATS client。"""
        for spec in self._subjects.all():
            if spec.direction == "unity_to_python":
                await client.subscribe(spec.subject, self.handle_message)

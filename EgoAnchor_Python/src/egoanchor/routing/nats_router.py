"""NATS subject router。

Router 是 transport 和 application handler 之间的桥：
subject -> protobuf parse -> handler dispatch -> reply serialize。
Router 不包含 reset/reacquire/control 的业务 if-else。
"""

from __future__ import annotations

from egoanchor.protocol import ProtobufRegistry, SubjectRegistry
from egoanchor.utils import get_logger
from .handler_registry import HandlerContext, HandlerRegistry

LOGGER = get_logger(__name__, component="NatsRouter")


class NatsRouter:
    """基于 subject registry 的 NATS bytes 消息分发器。"""

    def __init__(
        self,
        subjects: SubjectRegistry,
        protobufs: ProtobufRegistry,
        handlers: HandlerRegistry,
        context: HandlerContext,
    ) -> None:
        """保存 subject/protobuf/handler 注册表和 handler 上下文。"""

        self._subjects = subjects
        self._protobufs = protobufs
        self._handlers = handlers
        self._context = context

    async def handle_message(self, subject: str, payload: bytes, reply: str | None = None) -> bytes | None:
        """处理一条 NATS message，供真实 NATS callback 或单测直接调用。"""

        spec = self._subjects.require(subject)
        try:
            message = self._protobufs.parse(spec.protobuf, payload)
            result = self._handlers.get(subject)(self._context, message)
            if spec.mode == "request_reply":
                if result is None:
                    raise RuntimeError(f"request handler returned no reply for subject={subject!r}")
                response = self._protobufs.serialize(result)
                LOGGER.debug("request subject=%s reply_bytes=%d", subject, len(response))
                return response
            LOGGER.debug("pubsub subject=%s payload_bytes=%d", subject, len(payload))
            return None
        except Exception:
            LOGGER.exception("failed subject=%s has_reply=%s", subject, bool(reply))
            raise


__all__ = ["NatsRouter"]

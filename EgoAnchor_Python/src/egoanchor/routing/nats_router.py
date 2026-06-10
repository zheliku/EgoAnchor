"""NATS subject router。

Router 是 transport 和 application handler 之间的桥：
subject -> protobuf parse -> handler dispatch -> reply serialize。
Router 不包含 reset/reacquire/control 的业务 if-else。
"""

from __future__ import annotations

import time
import uuid

from google.protobuf.message import DecodeError, Message

from egoanchor.protocol import ProtobufRegistry, SubjectRegistry
from egoanchor.utils import get_logger
from .handler_registry import HandlerContext, HandlerNotRegisteredError, HandlerRegistry

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
        message: Message | None = None
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
        except Exception as exc:
            error_reply = self._build_error_reply(spec.reply, message, exc) if spec.mode == "request_reply" else None
            if error_reply is not None:
                self._log_request_error(subject, reply, exc)
                return error_reply
            LOGGER.exception("failed subject=%s has_reply=%s", subject, bool(reply))
            raise

    def _build_error_reply(self, reply_type_name: str | None, source_message: Message | None, exc: Exception) -> bytes | None:
        """为 request/reply 失败构造协议级错误回复；无法构造时返回 None。"""

        if not reply_type_name:
            return None
        try:
            reply_type = self._protobufs.get_type(reply_type_name)
            response = reply_type()
            if not hasattr(response, "accepted") or not hasattr(response, "status"):
                return None

            status, code, text = self._classify_error(exc)
            now_ms = time.monotonic() * 1000.0
            source_header = getattr(source_message, "header", None)
            target_header = getattr(response, "header", None)
            if target_header is not None:
                if source_header is not None:
                    target_header.CopyFrom(source_header)
                target_header.message_id = uuid.uuid4().hex
                target_header.sender_mono_ms = now_ms
                target_header.created_unix_ms = time.time() * 1000.0
                target_header.schema_version = "v1"

            response.accepted = False
            if hasattr(response, "duplicate"):
                response.duplicate = False
            response.status = status
            if hasattr(response, "message"):
                response.message = text
            if hasattr(response, "accepted_mono_ms"):
                response.accepted_mono_ms = now_ms

            error = getattr(response, "error", None)
            if error is not None:
                error.code = code
                error.message = text
                error.details = f"{type(exc).__name__}: {exc}"
            payload = self._protobufs.serialize(response)
            LOGGER.debug("request error reply type=%s bytes=%d status=%s", reply_type_name, len(payload), status)
            return payload
        except Exception:
            LOGGER.exception("failed to build request error reply type=%s", reply_type_name)
            return None

    @staticmethod
    def _classify_error(exc: Exception) -> tuple[str, str, str]:
        """把 router 层异常映射为 CommandAck 使用的稳定状态文本。"""

        if isinstance(exc, DecodeError):
            return "INVALID_ARGUMENT", "INVALID_ARGUMENT", "request protobuf payload is malformed"
        if isinstance(exc, HandlerNotRegisteredError):
            return "UNIMPLEMENTED", "UNIMPLEMENTED", str(exc)
        return "INTERNAL", "INTERNAL", "request handler failed"

    @staticmethod
    def _log_request_error(subject: str, reply: str | None, exc: Exception) -> None:
        """记录已转换成错误 ack 的 request 异常。"""

        if isinstance(exc, (DecodeError, HandlerNotRegisteredError)):
            LOGGER.warning("request rejected subject=%s has_reply=%s error=%s", subject, bool(reply), exc)
            return
        LOGGER.exception("request failed subject=%s has_reply=%s", subject, bool(reply))


__all__ = ["NatsRouter"]

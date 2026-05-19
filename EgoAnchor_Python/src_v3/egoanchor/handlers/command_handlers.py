"""v3 command request/reply handlers。

Unity 通过 NATS 发 reset/reacquire/control request 后，router 会解析 protobuf 并调用这里。
handler 只负责：校验 request_id、dedup、入 CommandQueue、立即返回 CommandAck。
CommandAck.accepted=true 只表示 server 接受命令，不表示命令已经执行完成。
"""

from __future__ import annotations

import logging
import time

from google.protobuf.message import Message

from egoanchor.protocol import (
    CMD_ANCHOR_CONTROL,
    CMD_ANCHOR_REACQUIRE,
    CMD_ANCHOR_RESET,
    CommandAck,
    ErrorInfo,
    MessageHeader,
)
from egoanchor.routing import HandlerContext, HandlerRegistry
from egoanchor.runtime import CommandType

LOGGER = logging.getLogger(__name__)


def _ack_for(message: Message, *, accepted: bool, status: str, text: str, code: str = "") -> Message:
    """根据 request message 构造 CommandAck，并复制 header 便于追踪。"""

    source_header = getattr(message, "header", None)
    header = MessageHeader(schema_version="v1")
    if source_header is not None:
        header.CopyFrom(source_header)
    ack = CommandAck(
        header=header,
        accepted=accepted,
        duplicate=False,
        status=status,
        message=text,
        accepted_mono_ms=time.monotonic() * 1000.0,
    )
    if code:
        ack.error.CopyFrom(ErrorInfo(code=code, message=text))
    return ack


def _accept(ctx: HandlerContext, message: Message, command_type: CommandType) -> Message:
    """通用命令接受逻辑。"""

    header = getattr(message, "header", None)
    request_id = str(getattr(header, "request_id", ""))
    if not request_id:
        ack = _ack_for(message, accepted=False, status="INVALID_ARGUMENT", text="header.request_id is required", code="INVALID_ARGUMENT")
        LOGGER.info("[CommandHandler:v3] type=%s accepted=false status=%s", command_type.value, ack.status)
        return ack

    if ctx.dedup is not None:
        duplicate = ctx.dedup.get(request_id)
        if duplicate is not None:
            LOGGER.info("[CommandHandler:v3] type=%s request_id=%s duplicate=true", command_type.value, request_id)
            return duplicate

    if ctx.commands is None:
        ack = _ack_for(message, accepted=False, status="UNAVAILABLE", text="command queue is not configured", code="UNAVAILABLE")
    elif ctx.commands.accept(command_type, message):
        ack = _ack_for(message, accepted=True, status="ACCEPTED", text=f"{command_type.value} accepted")
    else:
        ack = _ack_for(message, accepted=False, status="RESOURCE_EXHAUSTED", text="command queue is full", code="RESOURCE_EXHAUSTED")

    if ctx.dedup is not None:
        ctx.dedup.remember(request_id, ack)
    LOGGER.info(
        "[CommandHandler:v3] type=%s request_id=%s anchor_id=%s accepted=%s status=%s queue=%s",
        command_type.value,
        request_id,
        getattr(header, "anchor_id", ""),
        ack.accepted,
        ack.status,
        len(ctx.commands) if ctx.commands is not None else -1,
    )
    return ack


def register_command_handlers(registry: HandlerRegistry) -> None:
    """注册 reset/reacquire/control 三个 command request handler。"""

    @registry.request(CMD_ANCHOR_RESET)
    def handle_reset(ctx: HandlerContext, message: Message) -> Message:
        return _accept(ctx, message, CommandType.RESET)

    @registry.request(CMD_ANCHOR_REACQUIRE)
    def handle_reacquire(ctx: HandlerContext, message: Message) -> Message:
        return _accept(ctx, message, CommandType.REACQUIRE)

    @registry.request(CMD_ANCHOR_CONTROL)
    def handle_control(ctx: HandlerContext, message: Message) -> Message:
        return _accept(ctx, message, CommandType.CONTROL)


__all__ = ["register_command_handlers"]
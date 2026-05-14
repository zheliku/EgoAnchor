from __future__ import annotations

"""
v2 command request/reply handlers。

Unity 发起 reset/reacquire/control request 后，NATS router 会解析 protobuf 并调用
这里的 handler。handler 只做：
1. 校验 request_id；
2. 检查幂等缓存；
3. 把命令入 `CommandQueue`；
4. 立即返回 `CommandAck`。

注意：`CommandAck.accepted=true` 不代表 reset 已执行完成，只代表 server 已接受
命令。真正执行会在后续 TrackingRuntime 中发生，并通过 status/pose 反馈。
"""

import logging
import time

from google.protobuf.message import Message

from egoanchor.protocol.v1.anchor_pb2 import AnchorControlRequest, ReacquireAnchorRequest, ResetTrackingRequest
from egoanchor.protocol.v1.common_pb2 import CommandAck, ErrorInfo, MessageHeader
from egoanchor.routing.handler_registry import HandlerContext, HandlerRegistry
from egoanchor.runtime.commands import CommandType

LOGGER = logging.getLogger(__name__)


def _ack_for(message: Message, *, accepted: bool, status: str, text: str, code: str = "") -> CommandAck:
    """根据请求 message 构造 CommandAck，并复制原始 header 便于端到端追踪。"""
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


def _accept(ctx: HandlerContext, message: Message, command_type: CommandType) -> CommandAck:
    """通用命令接受逻辑：幂等检查、入队、记录 ack。"""
    header = getattr(message, "header", None)
    request_id = str(getattr(header, "request_id", ""))
    if not request_id:
        ack = _ack_for(message, accepted=False, status="INVALID_ARGUMENT", text="header.request_id is required", code="INVALID_ARGUMENT")
        LOGGER.info("[v2.command] type=%s accepted=false status=%s reason=%s", command_type.value, ack.status, ack.message)
        return ack

    if ctx.dedup is not None:
        duplicate = ctx.dedup.get(request_id)
        if duplicate is not None:
            LOGGER.info(
                "[v2.command] type=%s request_id=%s duplicate=true accepted=%s status=%s",
                command_type.value,
                request_id,
                duplicate.accepted,
                duplicate.status,
            )
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
        "[v2.command] type=%s request_id=%s anchor_id=%s accepted=%s status=%s queue=%s",
        command_type.value,
        request_id,
        getattr(header, "anchor_id", ""),
        ack.accepted,
        ack.status,
        len(ctx.commands) if ctx.commands is not None else -1,
    )
    return ack


def register_command_handlers(registry: HandlerRegistry) -> None:
    """向 handler registry 注册三个 command subject。"""
    @registry.request("egoanchor.v1.cmd.anchor.reset")
    def handle_reset(ctx: HandlerContext, message: ResetTrackingRequest) -> CommandAck:
        return _accept(ctx, message, CommandType.RESET)

    @registry.request("egoanchor.v1.cmd.anchor.reacquire")
    def handle_reacquire(ctx: HandlerContext, message: ReacquireAnchorRequest) -> CommandAck:
        return _accept(ctx, message, CommandType.REACQUIRE)

    @registry.request("egoanchor.v1.cmd.anchor.control")
    def handle_control(ctx: HandlerContext, message: AnchorControlRequest) -> CommandAck:
        return _accept(ctx, message, CommandType.CONTROL)

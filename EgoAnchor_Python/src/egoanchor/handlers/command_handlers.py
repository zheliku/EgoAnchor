"""command request/reply handlers。

Unity 通过 NATS 发 reset/reacquire/control request 后，router 会解析 protobuf 并调用这里。
handler 只负责：校验 request_id、dedup、入 CommandQueue、立即返回 CommandAck。
CommandAck.accepted=true 只表示 server 接受命令，不表示命令已经执行完成。
"""

from __future__ import annotations

import time
import uuid
from functools import partial

from google.protobuf.message import Message

from egoanchor.protocol import (
    AnchorControlRequest,
    CMD_ANCHOR_CONTROL,
    CMD_ANCHOR_REACQUIRE,
    CMD_ANCHOR_RESET,
    CommandAck,
    ErrorInfo,
    MessageHeader,
    ReacquireAnchorRequest,
    ResetTrackingRequest,
)
from egoanchor.routing import HandlerContext, HandlerRegistry
from egoanchor.runtime import CommandType, RuntimeCommand
from egoanchor.utils import get_logger

LOGGER = get_logger(__name__, component="CommandHandler")


def _ack_for(message: Message, *, accepted: bool, status: str, text: str, code: str = "") -> CommandAck:
    """根据 request message 构造 CommandAck，并复制 header 便于追踪。"""

    source_header = getattr(message, "header", None)
    header = MessageHeader(schema_version="v1")
    if source_header is not None:
        header.CopyFrom(source_header)
    accepted_mono_ms = time.monotonic() * 1000.0
    header.message_id = uuid.uuid4().hex
    header.sender_mono_ms = accepted_mono_ms
    header.created_unix_ms = time.time() * 1000.0
    header.schema_version = "v1"
    ack = CommandAck(
        header=header,
        accepted=accepted,
        duplicate=False,
        status=status,
        message=text,
        accepted_mono_ms=accepted_mono_ms,
    )
    if code:
        ack.error.CopyFrom(ErrorInfo(code=code, message=text))
    return ack


def _validate(message: Message, command_type: CommandType) -> tuple[bool, str]:
    """对 command 做轻量参数校验。

    handler 层只做不会触碰 GPU/pipeline 的基础校验：消息类型、枚举值、stage 范围等。
    真正的 reset/reacquire/control 执行仍由 TrackingRuntime 在主循环边界顺序完成。
    """

    if command_type == CommandType.RESET:
        if not isinstance(message, ResetTrackingRequest):
            return False, "reset command protobuf type mismatch"
        return True, ""

    if command_type == CommandType.REACQUIRE:
        if not isinstance(message, ReacquireAnchorRequest):
            return False, "reacquire command protobuf type mismatch"
        valid_modes = {
            ReacquireAnchorRequest.NEXT_VALID_FRAME,
            ReacquireAnchorRequest.LATEST_FRAME_IF_AVAILABLE,
            ReacquireAnchorRequest.FORCE_DETECT,
        }
        if int(message.mode) not in valid_modes:
            return False, f"invalid reacquire mode: {int(message.mode)}"
        return True, ""

    if command_type == CommandType.CONTROL:
        if not isinstance(message, AnchorControlRequest):
            return False, "control command protobuf type mismatch"
        valid_actions = {
            AnchorControlRequest.SET_STAGE,
            AnchorControlRequest.PAUSE,
            AnchorControlRequest.RESUME,
        }
        if int(message.action) not in valid_actions:
            return False, f"invalid control action: {int(message.action)}"
        if int(message.action) == AnchorControlRequest.SET_STAGE and not 1 <= int(message.stage) <= 4:
            return False, f"SET_STAGE stage must be in 1..4, got {int(message.stage)}"
        return True, ""

    return False, f"unsupported command type: {command_type.value}"


def _accept(ctx: HandlerContext, message: Message, command_type: CommandType) -> CommandAck:
    """通用命令接受逻辑。"""

    header = getattr(message, "header", None)
    request_id = str(getattr(header, "request_id", ""))
    if not request_id:
        ack = _ack_for(message, accepted=False, status="INVALID_ARGUMENT", text="header.request_id is required", code="INVALID_ARGUMENT")
        LOGGER.info("type=%s accepted=false status=%s", command_type.value, ack.status)
        return ack

    if ctx.dedup is not None:
        duplicate = ctx.dedup.get(request_id)
        if duplicate is not None:
            LOGGER.info("type=%s request_id=%s duplicate=true", command_type.value, request_id)
            return duplicate

    valid, invalid_reason = _validate(message, command_type)
    if not valid:
        ack = _ack_for(message, accepted=False, status="INVALID_ARGUMENT", text=invalid_reason, code="INVALID_ARGUMENT")
        if ctx.dedup is not None:
            ctx.dedup.remember(request_id, ack)
        LOGGER.info(
            "type=%s request_id=%s accepted=false status=%s reason=%s",
            command_type.value,
            request_id,
            ack.status,
            invalid_reason,
        )
        return ack

    if ctx.commands is None:
        ack = _ack_for(message, accepted=False, status="UNAVAILABLE", text="command queue is not configured", code="UNAVAILABLE")
    elif ctx.commands.put(RuntimeCommand.from_message(command_type, message)):
        ack = _ack_for(message, accepted=True, status="ACCEPTED", text=f"{command_type.value} accepted")
    else:
        ack = _ack_for(message, accepted=False, status="RESOURCE_EXHAUSTED", text="command queue is full", code="RESOURCE_EXHAUSTED")

    # 只缓存确定性结果（接受或参数非法）。UNAVAILABLE/RESOURCE_EXHAUSTED 是瞬时状态，
    # 缓存会让客户端在 TTL 内用同一 request_id 重试时拿到陈旧失败 ack，反而无法恢复。
    if ctx.dedup is not None and ack.accepted:
        ctx.dedup.remember(request_id, ack)
    LOGGER.info(
        "type=%s request_id=%s anchor_id=%s accepted=%s status=%s queue=%s",
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

    specs = (
        (CMD_ANCHOR_RESET, CommandType.RESET),
        (CMD_ANCHOR_REACQUIRE, CommandType.REACQUIRE),
        (CMD_ANCHOR_CONTROL, CommandType.CONTROL),
    )
    for subject, command_type in specs:
        registry.request(subject)(partial(_accept, command_type=command_type))


__all__ = ["register_command_handlers"]

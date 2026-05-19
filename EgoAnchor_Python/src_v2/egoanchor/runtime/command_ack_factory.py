"""CommandAck Protobuf 构造工具。"""

from __future__ import annotations

import time
import uuid

from egoanchor.protocol import common_pb2


def make_command_ack(
    *,
    request_header: common_pb2.MessageHeader | None = None,
    accepted: bool,
    status: str,
    message: str = "",
    duplicate: bool = False,
    error_code: str = "",
    error_message: str = "",
) -> common_pb2.CommandAck:
    """根据请求 header 构造 CommandAck。"""

    ack = common_pb2.CommandAck(
        header=common_pb2.MessageHeader(
            message_id=str(uuid.uuid4()),
            request_id=request_header.request_id if request_header is not None else "",
            session_id=request_header.session_id if request_header is not None else "",
            client_id="egoanchor-python-v2",
            anchor_id=request_header.anchor_id if request_header is not None else "",
            frame_id=request_header.frame_id if request_header is not None else 0,
            sender_mono_ms=time.perf_counter() * 1000.0,
            created_unix_ms=time.time() * 1000.0,
            schema_version="v1",
        ),
        accepted=accepted,
        duplicate=duplicate,
        status=status,
        message=message,
        accepted_mono_ms=time.perf_counter() * 1000.0,
    )
    if error_code or error_message:
        ack.error.code = error_code
        ack.error.message = error_message
    return ack


__all__ = ["make_command_ack"]
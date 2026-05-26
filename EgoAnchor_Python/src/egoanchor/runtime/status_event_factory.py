"""AnchorStatusEvent 构造器。"""

from __future__ import annotations

import time
import uuid

from egoanchor.protocol import anchor_pb2, common_pb2
from egoanchor.runtime import RuntimeState, runtime_state_value

SCHEMA_VERSION = "v1"
"""当前共享协议 schema 版本字符串。"""


class StatusEventFactory:
    """构造 Python -> Unity 的 AnchorStatusEvent。

    factory 位于 runtime 层，负责把 Python runtime 状态变化、命令执行结果和重要错误
    映射成共享 Protobuf。它不发布网络消息，也不接触 pipeline/GPU 状态。
    """

    def __init__(self, *, client_id: str = "egoanchor-python", anchor_id: str = "default", session_id: str = "") -> None:
        """保存 status event 消息头中的发布端和 anchor 标识。"""

        self.client_id = str(client_id)
        """发布端客户端标识。"""

        self.anchor_id = str(anchor_id)
        """目标 anchor 标识；当前单目标主线使用 default。"""

        self.session_id = str(session_id or uuid.uuid4().hex)
        """Python 进程会话 ID，用于 Unity 侧区分重启前后的状态事件。"""

    def build(
        self,
        state: RuntimeState | str,
        *,
        event: str,
        message: str = "",
        request_id: str = "",
        frame_id: int | None = None,
        anchor_id: str = "",
        error: common_pb2.ErrorInfo | None = None,
    ) -> anchor_pb2.AnchorStatusEvent:
        """构造一条 AnchorStatusEvent。"""

        msg = anchor_pb2.AnchorStatusEvent()
        msg.header.CopyFrom(self._build_header(request_id=request_id, frame_id=frame_id, anchor_id=anchor_id))
        msg.state = runtime_state_value(state)
        msg.event = str(event or "")
        msg.message = str(message or "")
        if error is not None:
            msg.error.CopyFrom(error)
        return msg

    def build_error(
        self,
        state: RuntimeState | str,
        *,
        event: str,
        code: str,
        message: str,
        details: str = "",
        request_id: str = "",
        frame_id: int | None = None,
        anchor_id: str = "",
    ) -> anchor_pb2.AnchorStatusEvent:
        """构造携带结构化 ErrorInfo 的状态事件。"""

        error = common_pb2.ErrorInfo(code=str(code or ""), message=str(message or ""), details=str(details or ""))
        return self.build(
            state,
            event=event,
            message=message,
            request_id=request_id,
            frame_id=frame_id,
            anchor_id=anchor_id,
            error=error,
        )

    def _build_header(self, *, request_id: str = "", frame_id: int | None = None, anchor_id: str = "") -> common_pb2.MessageHeader:
        """构造共享消息头。"""

        return common_pb2.MessageHeader(
            message_id=uuid.uuid4().hex,
            request_id=str(request_id or ""),
            session_id=self.session_id,
            client_id=self.client_id,
            anchor_id=str(anchor_id or self.anchor_id),
            frame_id=int(frame_id if frame_id is not None else -1),
            sender_mono_ms=time.monotonic() * 1000.0,
            created_unix_ms=time.time() * 1000.0,
            schema_version=SCHEMA_VERSION,
        )


__all__ = ["StatusEventFactory"]

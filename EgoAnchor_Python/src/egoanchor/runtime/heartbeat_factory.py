"""ServerHeartbeat 构造器。"""

from __future__ import annotations

import time
import uuid
from typing import Any

from egoanchor.protocol import anchor_pb2, common_pb2
from egoanchor.runtime import RuntimeState, runtime_state_value

SCHEMA_VERSION = "v1"
"""当前共享协议 schema 版本字符串。"""


class HeartbeatFactory:
    """构造 Python -> Unity 的 ServerHeartbeat。

    heartbeat 只描述 Python server 和输入链路健康状态，不包含 Unity world pose。
    Unity 侧根据 heartbeat 判断链路是否可用，并把异常映射到本地 anchor state。
    """

    def __init__(self, *, client_id: str = "egoanchor-python", anchor_id: str = "default", session_id: str = "") -> None:
        """保存 heartbeat 消息头中的发布端和 anchor 标识。"""

        self.client_id = str(client_id)
        """发布端客户端标识。"""

        self.anchor_id = str(anchor_id)
        """目标 anchor 标识；当前单目标主线使用 default。"""

        self.session_id = str(session_id or uuid.uuid4().hex)
        """Python 进程会话 ID，用于 Unity 侧诊断服务重启。"""

    def build(
        self,
        state: RuntimeState | str,
        *,
        input_stats: Any | None = None,
        runtime_fps: float = 0.0,
        publish_fps: float = 0.0,
        command_stats: dict[str, Any] | None = None,
        last_error: common_pb2.ErrorInfo | None = None,
    ) -> anchor_pb2.ServerHeartbeat:
        """构造一条 ServerHeartbeat。"""

        heartbeat = anchor_pb2.ServerHeartbeat()
        heartbeat.header.CopyFrom(self._build_header(input_stats))
        heartbeat.state = runtime_state_value(state)
        heartbeat.input_ready = self._is_input_ready(input_stats)
        heartbeat.latest_stereo_frame_id = int(getattr(input_stats, "latest_stereo_frame_id", -1) or -1)
        heartbeat.camera_info_version = int(getattr(input_stats, "camera_info_version", 0) or 0)
        heartbeat.runtime_fps = float(runtime_fps)
        heartbeat.publish_fps = float(publish_fps)
        heartbeat.command_queue_length = int((command_stats or {}).get("queue_length", 0) or 0)
        if last_error is not None:
            heartbeat.last_error.CopyFrom(last_error)
        return heartbeat

    def _build_header(self, input_stats: Any | None) -> common_pb2.MessageHeader:
        """构造共享消息头。"""

        frame_id = int(getattr(input_stats, "latest_stereo_frame_id", -1) or -1)
        return common_pb2.MessageHeader(
            message_id=uuid.uuid4().hex,
            session_id=self.session_id,
            client_id=self.client_id,
            anchor_id=self.anchor_id,
            frame_id=frame_id,
            sender_mono_ms=time.monotonic() * 1000.0,
            created_unix_ms=time.time() * 1000.0,
            schema_version=SCHEMA_VERSION,
        )

    @staticmethod
    def _is_input_ready(input_stats: Any | None) -> bool:
        """判断 Quest stereo 和 camera_info 是否都已到达。"""

        if input_stats is None:
            return False
        stereo_ready = bool(getattr(input_stats, "latest_stereo_frame_id", None) is not None or getattr(input_stats, "decoded_stereo", 0) > 0)
        calibration_ready = int(getattr(input_stats, "camera_info_version", 0) or 0) > 0
        return stereo_ready and calibration_ready


__all__ = ["HeartbeatFactory"]

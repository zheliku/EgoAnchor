"""Protobuf MessageHeader 读取工具。"""

from __future__ import annotations

from typing import Any


def _header(message: Any) -> Any | None:
    """返回消息中的 header；没有 header 字段或未设置时返回 None。"""

    has_field = getattr(message, "HasField", None)
    if not callable(has_field):
        return None
    try:
        if not has_field("header"):
            return None
    except ValueError:
        return None
    return getattr(message, "header", None)


def extract_frame_id(message: Any) -> int | None:
    """从 Protobuf header 中提取 frame_id；缺失时返回 None。"""

    header = _header(message)
    if header is None:
        return None
    return int(getattr(header, "frame_id", 0))


def extract_session_id(message: Any) -> str:
    """从 Protobuf header 中提取 Unity 发布会话 ID；缺失时返回空字符串。"""

    header = _header(message)
    if header is None:
        return ""
    return str(getattr(header, "session_id", ""))


def extract_client_id(message: Any) -> str:
    """从 Protobuf header 中提取客户端 ID；缺失时返回空字符串。"""

    header = _header(message)
    if header is None:
        return ""
    return str(getattr(header, "client_id", ""))


__all__ = ["extract_client_id", "extract_frame_id", "extract_session_id"]

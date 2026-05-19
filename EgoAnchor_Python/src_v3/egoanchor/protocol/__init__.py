"""v3 协议包级入口。

业务代码应从这里导入 Protobuf 模块和 subject 常量，避免直接依赖生成文件路径。
"""

from __future__ import annotations

from egoanchor.protocol.subjects import (
    ANCHOR_STATUS,
    CMD_ANCHOR_CONTROL,
    CMD_ANCHOR_REACQUIRE,
    CMD_ANCHOR_RESET,
    POSE_RESULT,
    QUEST_CAMERA_INFO,
    QUEST_STEREO,
    SERVER_HEARTBEAT,
    SubjectRegistry,
    SubjectSpec,
    default_subjects_path,
    load_subjects,
)
from egoanchor.protocol.v1 import anchor_pb2, common_pb2, quest_pb2

__all__ = [
    "ANCHOR_STATUS",
    "CMD_ANCHOR_CONTROL",
    "CMD_ANCHOR_REACQUIRE",
    "CMD_ANCHOR_RESET",
    "POSE_RESULT",
    "QUEST_CAMERA_INFO",
    "QUEST_STEREO",
    "SERVER_HEARTBEAT",
    "SubjectRegistry",
    "SubjectSpec",
    "anchor_pb2",
    "common_pb2",
    "default_subjects_path",
    "load_subjects",
    "quest_pb2",
]
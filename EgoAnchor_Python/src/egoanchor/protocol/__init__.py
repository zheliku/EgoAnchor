"""协议包级入口。

业务代码应从这里导入 Protobuf 模块和 subject 常量，避免直接依赖生成文件路径。
"""

from __future__ import annotations

from .subjects import (
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
from . import v1
from .protobuf_registry import ProtobufRegistry
from .header_utils import extract_client_id, extract_frame_id, extract_session_id

anchor_pb2 = v1.anchor_pb2
"""protocol.v1 anchor Protobuf 生成模块。"""

common_pb2 = v1.common_pb2
"""protocol.v1 common Protobuf 生成模块。"""

quest_pb2 = v1.quest_pb2
"""protocol.v1 Quest Protobuf 生成模块。"""

AnchorControlRequest = v1.AnchorControlRequest
"""anchor control command request 类型。"""

CommandAck = v1.CommandAck
"""command request/reply 的 ack 类型。"""

ErrorInfo = v1.ErrorInfo
"""共享错误信息类型。"""

MessageHeader = v1.MessageHeader
"""共享消息头类型。"""

Matrix4x4 = v1.Matrix4x4
"""4x4 矩阵消息类型。"""

PoseResult = v1.PoseResult
"""Python -> Unity pose result 类型。"""

QuestCameraInfo = v1.QuestCameraInfo
"""Quest 相机标定消息类型。"""

QuestStereoFrame = v1.QuestStereoFrame
"""Quest 双目帧消息类型。"""

ReacquireAnchorRequest = v1.ReacquireAnchorRequest
"""主动重新获取 anchor 的 command request 类型。"""

ResetTrackingRequest = v1.ResetTrackingRequest
"""重置 tracking 的 command request 类型。"""

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
    "AnchorControlRequest",
    "CommandAck",
    "ErrorInfo",
    "MessageHeader",
    "Matrix4x4",
    "PoseResult",
    "ProtobufRegistry",
    "QuestCameraInfo",
    "QuestStereoFrame",
    "ReacquireAnchorRequest",
    "ResetTrackingRequest",
    "anchor_pb2",
    "common_pb2",
    "default_subjects_path",
    "extract_client_id",
    "extract_frame_id",
    "extract_session_id",
    "load_subjects",
    "quest_pb2",
]

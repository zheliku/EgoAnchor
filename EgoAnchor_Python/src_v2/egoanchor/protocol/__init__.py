"""v2 Protobuf 协议包。

*_pb2.py 由 EgoAnchor_Protocol/tools/generate_proto.ps1 生成，请勿手改。
"""

from egoanchor.protocol import subjects
from egoanchor.protocol.subjects import (
    ANCHOR_STATUS,
    CMD_ANCHOR_CONTROL,
    CMD_ANCHOR_REACQUIRE,
    CMD_ANCHOR_RESET,
    POSE_RESULT,
    QUEST_CAMERA_INFO,
    QUEST_STEREO,
    SERVER_HEARTBEAT,
    SubjectSpec,
    load_subjects,
    zmq_data_plane_topics,
)

__all__ = [
    "subjects",
    "ANCHOR_STATUS",
    "CMD_ANCHOR_CONTROL",
    "CMD_ANCHOR_REACQUIRE",
    "CMD_ANCHOR_RESET",
    "POSE_RESULT",
    "QUEST_CAMERA_INFO",
    "QUEST_STEREO",
    "SERVER_HEARTBEAT",
    "SubjectSpec",
    "load_subjects",
    "zmq_data_plane_topics",
]

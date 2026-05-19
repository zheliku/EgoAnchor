"""protocol.v1 生成代码包级入口。

业务代码不直接导入具体 ``*_pb2.py`` 文件，而是从本包或上层
``egoanchor.protocol`` 入口获取 Protobuf 模块和常用消息类型。
"""

from __future__ import annotations

from . import anchor_pb2, common_pb2, quest_pb2

AnchorControlRequest = anchor_pb2.AnchorControlRequest
"""anchor control command request 类型。"""

CommandAck = common_pb2.CommandAck
"""command request/reply 的 ack 类型。"""

ErrorInfo = common_pb2.ErrorInfo
"""共享错误信息类型。"""

MessageHeader = common_pb2.MessageHeader
"""共享消息头类型。"""

ReacquireAnchorRequest = anchor_pb2.ReacquireAnchorRequest
"""主动重新获取 anchor 的 command request 类型。"""

ResetTrackingRequest = anchor_pb2.ResetTrackingRequest
"""重置 tracking 的 command request 类型。"""

__all__ = [
	"AnchorControlRequest",
	"CommandAck",
	"ErrorInfo",
	"MessageHeader",
	"ReacquireAnchorRequest",
	"ResetTrackingRequest",
	"anchor_pb2",
	"common_pb2",
	"quest_pb2",
]


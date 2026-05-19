"""v3 PoseObservation 到 Protobuf PoseResult 的映射。"""

from __future__ import annotations

import time
import uuid
from typing import Iterable

from egoanchor.perception import PoseObservation
from egoanchor.protocol import anchor_pb2, common_pb2

SCHEMA_VERSION = "v1"
"""当前共享协议 schema 版本字符串。"""


class PoseResultFactory:
    """把感知侧 PoseObservation 转成共享协议 PoseResult。

    factory 位于 runtime 层：它理解 perception 的观测结构，也理解 protocol 的 Protobuf 字段，
    但不负责 NATS 发布、不访问 Unity，也不修改 pipeline/GPU 状态。
    """

    def __init__(self, *, client_id: str = "egoanchor-python-v3", anchor_id: str = "default") -> None:
        """保存消息头中的客户端/anchor 标识。"""

        self.client_id = str(client_id)
        """发布端客户端标识。"""

        self.anchor_id = str(anchor_id)
        """目标 anchor 标识；当前单目标 demo 使用 default。"""

        self.session_id = uuid.uuid4().hex
        """本次 Python 进程会话 ID，用于 Unity 侧日志排查。"""

    def build(self, observation: PoseObservation) -> anchor_pb2.PoseResult:
        """从单帧 PoseObservation 构造 PoseResult。"""

        frame_id = int(observation.frame_id if observation.frame_id is not None else -1)
        matrix_values = tuple(observation.pose_matrix_cv_camera or ())
        has_pose = bool(observation.has_pose and len(matrix_values) == 16)
        result = anchor_pb2.PoseResult()
        result.header.CopyFrom(self._build_header(frame_id))
        result.has_pose = has_pose
        result.phase = str(observation.phase or "")
        result.stage = int(observation.stage)
        result.det_count = int(observation.det_count)
        result.depth_valid_ratio = float(observation.depth_valid_ratio)
        result.fps = float(observation.fps)
        result.timing.CopyFrom(
            common_pb2.TimingStats(
                yolo_ms=float(observation.yolo_ms),
                depth_ms=float(observation.depth_ms),
                cutie_ms=float(observation.cutie_ms),
                pose_ms=float(observation.pose_ms),
                total_ms=float(observation.total_ms),
            )
        )

        if has_pose:
            result.pose_matrix_cv_camera.CopyFrom(self._matrix_from_values(matrix_values))
        else:
            result.last_error.CopyFrom(self._build_error(observation))
        return result

    def _build_header(self, frame_id: int) -> common_pb2.MessageHeader:
        """构造共享消息头。"""

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
    def _matrix_from_values(values: Iterable[float]) -> common_pb2.Matrix4x4:
        """把 row-major 4x4 浮点序列写入 Protobuf Matrix4x4。"""

        matrix_values = [float(value) for value in values]
        if len(matrix_values) != 16:
            # 不抛出到上层发布循环；Unity 会按 has_pose=false 忽略非法 pose。
            matrix_values = []
        matrix = common_pb2.Matrix4x4()
        matrix.values.extend(matrix_values)
        return matrix

    @staticmethod
    def _build_error(observation: PoseObservation) -> common_pb2.ErrorInfo:
        """构造无 pose 时的结构化错误信息。"""

        code = str(observation.failure_reason or observation.phase or "NO_POSE")
        details = ",".join(str(flag) for flag in observation.reliability_flags)
        return common_pb2.ErrorInfo(code=code, message="当前帧没有可应用的 6DoF pose。", details=details)


__all__ = ["PoseResultFactory"]

"""PoseResult Protobuf 消息构造工具。

这里属于 runtime 层：它把 perception 输出的 `PoseObservation` 映射为共享协议
`PoseResult`。transport/nats 只发送 bytes/protobuf，不反向依赖 perception。
"""

from __future__ import annotations

import logging
import time
import uuid

from egoanchor.perception import PoseObservation
from egoanchor.protocol import anchor_pb2, common_pb2


def pose_result_from_observation(
    observation: PoseObservation,
    *,
    session_id: str = "",
    client_id: str = "egoanchor-python-v2",
    anchor_id: str = "default",
) -> anchor_pb2.PoseResult:
    """把 perception 层的 PoseObservation 转成共享 Protobuf PoseResult。

    约定：
    - `pose_matrix_cv_camera.values` 使用 numpy 默认 row-major 展平顺序；
    - 矩阵仍处于 OpenCV camera 坐标（x 右、y 下、z 前）；
    - Unity 端必须用同一个 `frame_id` 回查采集该帧时的 left camera world pose，
      再执行 OpenCV->Unity camera-local 坐标转换和 world transform；
    - `has_pose=false` 是合法结果，Unity 端不可应用 Transform，但可以记录诊断。
    """

    has_pose = bool(observation.has_pose)
    matrix_values = tuple(observation.pose_matrix_cv_camera or ())
    if has_pose and len(matrix_values) != 16:
        # 防御性降级：协议要求 has_pose=true 时必须带 16 个矩阵元素。
        # 这里不抛异常，避免单帧异常中断 runtime；Unity 端会收到 NO_POSE 诊断包。
        logging.warning(
            "[PoseResultFactory] PoseObservation frame_id=%s has_pose=true 但矩阵长度=%d，降级为 has_pose=false。",
            observation.frame_id,
            len(matrix_values),
        )
        has_pose = False
        matrix_values = ()

    msg = anchor_pb2.PoseResult(
        header=common_pb2.MessageHeader(
            message_id=str(uuid.uuid4()),
            session_id=session_id,
            client_id=client_id,
            anchor_id=anchor_id,
            frame_id=int(observation.frame_id or 0),
            sender_mono_ms=time.perf_counter() * 1000.0,
            created_unix_ms=time.time() * 1000.0,
            schema_version="v1",
        ),
        has_pose=has_pose,
        phase=str(observation.phase or ""),
        stage=int(observation.stage),
        det_count=int(observation.det_count),
        depth_valid_ratio=float(observation.depth_valid_ratio),
        fps=float(observation.fps),
        timing=common_pb2.TimingStats(
            yolo_ms=float(observation.yolo_ms),
            depth_ms=float(observation.depth_ms),
            cutie_ms=float(observation.cutie_ms),
            pose_ms=float(observation.pose_ms),
            total_ms=float(observation.yolo_ms + observation.depth_ms + observation.cutie_ms + observation.pose_ms),
        ),
    )
    if has_pose:
        msg.pose_matrix_cv_camera.values.extend(float(x) for x in matrix_values)
    else:
        msg.last_error.code = "NO_POSE"
        msg.last_error.message = str(observation.phase or "no valid pose")
    return msg


__all__ = ["pose_result_from_observation"]
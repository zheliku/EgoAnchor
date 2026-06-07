"""Quest stereo Protobuf 帧解码与图像预处理工具。

本模块只把 `QuestStereoFrame` 的 JPEG payload 变成 OpenCV 图像，并把左右图
归一化到算法处理分辨率；不做网络接收、模型推理或 runtime 状态管理。
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from egoanchor.protocol import quest_pb2
from egoanchor.utils import ensure_bgr_u8


@dataclass(frozen=True, slots=True)
class DecodedQuestStereoFrame:
    """解码后的 Quest 双目帧。"""

    frame_id: int | None
    """Unity/Quest frame_id；header 缺失时为 None。"""

    sender_mono_ms: float | None
    """Unity 发送端单调时钟时间戳，单位毫秒。"""

    unity_frame: int | None
    """Unity 帧号；header 缺失时为 None。"""

    left_bgr: np.ndarray
    """左目 BGR uint8 图像。"""

    right_bgr: np.ndarray
    """右目 BGR uint8 图像。"""


def decode_quest_stereo_frame(msg: quest_pb2.QuestStereoFrame) -> DecodedQuestStereoFrame | None:
    """把 QuestStereoFrame 中的左右 JPEG 解码为 OpenCV BGR 图像。"""

    if not msg.left_image_jpeg or not msg.right_image_jpeg:
        return None

    left = cv2.imdecode(np.frombuffer(bytes(msg.left_image_jpeg), dtype=np.uint8), cv2.IMREAD_COLOR)
    right = cv2.imdecode(np.frombuffer(bytes(msg.right_image_jpeg), dtype=np.uint8), cv2.IMREAD_COLOR)
    if left is None or right is None:
        return None

    header = msg.header if msg.HasField("header") else None
    return DecodedQuestStereoFrame(
        frame_id=int(header.frame_id) if header is not None else None,
        sender_mono_ms=float(header.sender_mono_ms) if header is not None else None,
        unity_frame=int(header.unity_frame) if header is not None else None,
        left_bgr=left,
        right_bgr=right,
    )


def preprocess_stereo_pair(left: np.ndarray, right: np.ndarray, target_width: int, target_height: int) -> tuple[np.ndarray, np.ndarray]:
    """把左右图像归一化到算法处理分辨率。"""

    left_bgr = ensure_bgr_u8(left)
    right_bgr = ensure_bgr_u8(right)

    if left_bgr.shape[:2] != right_bgr.shape[:2]:
        out_h = min(left_bgr.shape[0], right_bgr.shape[0])
        out_w = min(left_bgr.shape[1], right_bgr.shape[1])
        left_bgr = cv2.resize(left_bgr, (out_w, out_h), interpolation=cv2.INTER_LINEAR)
        right_bgr = cv2.resize(right_bgr, (out_w, out_h), interpolation=cv2.INTER_LINEAR)

    if target_width > 0 and target_height > 0:
        h, w = left_bgr.shape[:2]
        if w != target_width or h != target_height:
            interpolation = cv2.INTER_AREA if (target_width < w or target_height < h) else cv2.INTER_LINEAR
            left_bgr = cv2.resize(left_bgr, (target_width, target_height), interpolation=interpolation)
            right_bgr = cv2.resize(right_bgr, (target_width, target_height), interpolation=interpolation)

    return left_bgr, right_bgr

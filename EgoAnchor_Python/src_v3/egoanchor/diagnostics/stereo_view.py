"""Quest stereo 图像预览辅助函数。"""

from __future__ import annotations

import cv2
import numpy as np


def decode_jpeg(data: bytes) -> np.ndarray | None:
    """把 JPEG bytes 解码为 OpenCV BGR 图像。"""

    if not data:
        return None
    encoded = np.frombuffer(data, dtype=np.uint8)
    return cv2.imdecode(encoded, cv2.IMREAD_COLOR)


def make_waiting_image(width: int, height: int, title: str) -> np.ndarray:
    """生成等待输入时显示的占位画面。"""

    image = np.zeros((max(height, 1), max(width, 1), 3), dtype=np.uint8)
    cv2.putText(image, title, (24, height // 2 - 16), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (220, 220, 220), 2, cv2.LINE_AA)
    cv2.putText(
        image,
        "Data plane: ZMQ multipart [topic_utf8, protobuf_bytes]",
        (24, height // 2 + 28),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (160, 220, 255),
        1,
        cv2.LINE_AA,
    )
    return image


def stack_stereo(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    """把左右图等高横向拼接，便于观察双目同步情况。"""

    if left.shape[0] != right.shape[0]:
        target_height = min(left.shape[0], right.shape[0])
        left = cv2.resize(left, (max(1, int(left.shape[1] * target_height / left.shape[0])), target_height), interpolation=cv2.INTER_LINEAR)
        right = cv2.resize(
            right,
            (max(1, int(right.shape[1] * target_height / right.shape[0])), target_height),
            interpolation=cv2.INTER_LINEAR,
        )
    return np.hstack((left, right))


def draw_stereo_hud(
    image: np.ndarray,
    *,
    frame_id: int,
    left_shape: tuple[int, ...],
    right_shape: tuple[int, ...],
    camera_info_version: int,
    stereo_age_ms: float | None,
) -> None:
    """在 stereo 预览图上绘制 frame_id、尺寸和缓存状态。"""

    text = (
        f"frame_id={frame_id} "
        f"L{left_shape[1]}x{left_shape[0]} R{right_shape[1]}x{right_shape[0]} "
        f"camera_info_v={camera_info_version} age_ms={(stereo_age_ms or 0.0):.1f}"
    )
    cv2.putText(image, text, (16, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 0), 2, cv2.LINE_AA)
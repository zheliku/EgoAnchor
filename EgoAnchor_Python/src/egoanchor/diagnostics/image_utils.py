"""OpenCV 诊断图像通用工具。"""

from __future__ import annotations

import cv2
import numpy as np


def fit_to_width(image: np.ndarray, width: int) -> np.ndarray:
    """按目标宽度等比缩放图像。"""

    target_width = max(int(width), 1)
    if image.shape[1] == target_width:
        return image
    height = max(1, int(image.shape[0] * target_width / max(image.shape[1], 1)))
    return cv2.resize(image, (target_width, height), interpolation=cv2.INTER_AREA if target_width < image.shape[1] else cv2.INTER_LINEAR)


def fit_to_size(image: np.ndarray, width: int, height: int) -> np.ndarray:
    """缩放并居中填充到固定大小。"""

    target_width = max(int(width), 1)
    target_height = max(int(height), 1)
    scale = min(target_width / max(image.shape[1], 1), target_height / max(image.shape[0], 1))
    new_w = max(1, int(image.shape[1] * scale))
    new_h = max(1, int(image.shape[0] * scale))
    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
    canvas = np.zeros((target_height, target_width, 3), dtype=np.uint8)
    x0 = (target_width - new_w) // 2
    y0 = (target_height - new_h) // 2
    canvas[y0 : y0 + new_h, x0 : x0 + new_w] = resized
    return canvas


def stack_stereo(left_bgr: np.ndarray | None, right_bgr: np.ndarray | None) -> np.ndarray:
    """把左右图等高横向拼接，缺失时显示占位图。"""

    if left_bgr is None and right_bgr is None:
        return np.zeros((240, 640, 3), dtype=np.uint8)
    if left_bgr is None:
        left_bgr = np.zeros_like(right_bgr)
    if right_bgr is None:
        right_bgr = np.zeros_like(left_bgr)
    if left_bgr.shape[0] != right_bgr.shape[0]:
        target_height = min(left_bgr.shape[0], right_bgr.shape[0])
        left_bgr = cv2.resize(
            left_bgr,
            (max(1, int(left_bgr.shape[1] * target_height / left_bgr.shape[0])), target_height),
            interpolation=cv2.INTER_LINEAR,
        )
        right_bgr = cv2.resize(
            right_bgr,
            (max(1, int(right_bgr.shape[1] * target_height / right_bgr.shape[0])), target_height),
            interpolation=cv2.INTER_LINEAR,
        )
    return np.hstack([left_bgr, right_bgr])


__all__ = ["fit_to_size", "fit_to_width", "stack_stereo"]

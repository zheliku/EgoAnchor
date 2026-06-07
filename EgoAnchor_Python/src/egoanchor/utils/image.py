"""项目内通用图像输入规范化工具。"""

from __future__ import annotations

import cv2
import numpy as np


def ensure_bgr_u8(image: np.ndarray, *, subject: str = "图像") -> np.ndarray:
    """把灰度/浮点/多通道图像统一成 OpenCV BGR uint8 三通道。

    该函数只负责输入数组格式规范化，不做 resize、裁剪或业务语义判断。
    """

    if image.ndim == 2:
        out = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    elif image.ndim == 3:
        out = image[..., :3]
    else:
        raise ValueError(f"{subject}维度不正确，应为 (H,W) 或 (H,W,C)。")

    if out.dtype != np.uint8:
        out = np.clip(out, 0, 255).astype(np.uint8)
    return out


__all__ = ["ensure_bgr_u8"]

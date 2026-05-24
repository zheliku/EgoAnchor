"""OpenCV 窗口辅助函数。"""

from __future__ import annotations

import cv2


def create_fixed_window(name: str, width: int, height: int) -> None:
    """创建可调整大小的 OpenCV 窗口，并设置初始尺寸。"""

    cv2.namedWindow(name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(name, max(int(width), 1), max(int(height), 1))
"""OpenCV 窗口辅助工具。

统一管理 demo/debug 窗口创建逻辑，避免每个入口重复写 namedWindow/resizeWindow。
"""

from __future__ import annotations

import cv2


def create_fixed_window(window_name: str, width: int, height: int) -> None:
    """创建固定初始尺寸的 OpenCV 窗口。

    说明：
    - 使用 `WINDOW_NORMAL` 是为了允许 `resizeWindow` 生效。
    - 设置窗口尺寸后，OpenCV 会按给定大小显示，避免每次启动窗口过小。
    - 用户仍可手动拖动窗口；若强制 `WINDOW_AUTOSIZE`，反而无法按配置调整大小。
    """

    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, max(int(width), 1), max(int(height), 1))

"""OpenCV debug windows for object_tracking_server."""

from __future__ import annotations

import cv2
import numpy as np


DEBUG_WINDOW = "ObjectTrackingServer Debug"
STEREO_WINDOW = "ObjectTrackingServer Stereo"


def draw_text_block(
    image: np.ndarray,
    lines: list[str],
    x: int = 10,
    y: int = 24,
    gap: int = 22,
    anchor: str = "top-left",
    panel_alpha: float = 0.55,
) -> None:
    """在调试图上绘制半透明文本块，用于稳定显示服务端统计。"""
    if not lines:
        return

    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.55
    thickness = 1
    padding = 8

    sizes = [cv2.getTextSize(line, font, scale, thickness)[0] for line in lines]
    text_w = max((w for (w, _) in sizes), default=0)
    text_h = max((h for (_, h) in sizes), default=18)

    if anchor == "bottom-left":
        y = image.shape[0] - padding - (len(lines) - 1) * gap

    top = max(y - text_h - padding, 0)
    bottom = min(y + (len(lines) - 1) * gap + padding, image.shape[0] - 1)
    left = max(x - padding, 0)
    right = min(x + text_w + padding, image.shape[1] - 1)

    overlay = image.copy()
    cv2.rectangle(overlay, (left, top), (right, bottom), (0, 0, 0), -1)
    cv2.addWeighted(overlay, panel_alpha, image, 1.0 - panel_alpha, 0, image)

    for i, line in enumerate(lines):
        yy = y + i * gap
        cv2.putText(image, line, (x, yy), font, scale, (15, 15, 15), 2, cv2.LINE_AA)
        cv2.putText(image, line, (x, yy), font, scale, (245, 245, 245), 1, cv2.LINE_AA)


def make_waiting_placeholder(text: str) -> np.ndarray:
    """生成等待首帧期间的占位图，避免 OpenCV 窗口被系统判定未响应。"""
    image = np.zeros((240, 640, 3), dtype=np.uint8)
    cv2.putText(
        image,
        text,
        (20, 120),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (255, 255, 255),
        2,
    )
    return image


class TrackingServerDebugView:
    """管理 object_tracking_server 的 OpenCV 调试窗口。"""

    def __init__(self, enabled: bool, waiting_text: str) -> None:
        self.enabled = enabled
        self.waiting_placeholder = make_waiting_placeholder(waiting_text)

        if self.enabled:
            cv2.namedWindow(DEBUG_WINDOW, cv2.WINDOW_AUTOSIZE)
            cv2.namedWindow(STEREO_WINDOW, cv2.WINDOW_AUTOSIZE)
            cv2.setWindowProperty(DEBUG_WINDOW, cv2.WND_PROP_TOPMOST, 1)

    def show_waiting(self) -> int:
        """显示等待占位图并返回键盘输入。"""
        if not self.enabled:
            return -1
        cv2.imshow(DEBUG_WINDOW, self.waiting_placeholder)
        cv2.setWindowProperty(DEBUG_WINDOW, cv2.WND_PROP_TOPMOST, 1)
        return cv2.waitKey(1) & 0xFF

    def show_output(self, output: object, overlay_lines: list[str]) -> int:
        """显示 pipeline debug 输出并返回键盘输入。"""
        if not self.enabled or getattr(output, "debug", None) is None:
            return -1

        dashboard_bgr, stereo_bgr = output.debug
        debug_vis = dashboard_bgr.copy()
        draw_text_block(debug_vis, overlay_lines, anchor="bottom-left")
        cv2.imshow(DEBUG_WINDOW, debug_vis)
        cv2.imshow(STEREO_WINDOW, stereo_bgr)
        cv2.setWindowProperty(DEBUG_WINDOW, cv2.WND_PROP_TOPMOST, 1)
        cv2.setWindowProperty(STEREO_WINDOW, cv2.WND_PROP_TOPMOST, 0)
        return cv2.waitKey(1) & 0xFF

    def close(self) -> None:
        if self.enabled:
            cv2.destroyAllWindows()

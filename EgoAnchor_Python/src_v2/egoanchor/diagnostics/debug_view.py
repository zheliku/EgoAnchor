"""OpenCV debug view 工具。

这里集中放置可视化辅助函数，避免 perception pipeline 里混入大量绘图细节。
所有函数只处理 numpy 图像，不依赖 ZMQ/NATS，也不触碰模型状态。
"""

from __future__ import annotations

import cv2
import numpy as np


def draw_hud(
    image_bgr: np.ndarray,
    lines: str | list[str],
    x: int = 12,
    y: int = 28,
    line_gap: int = 24,
) -> None:
    """在 BGR 图像上绘制带黑色描边的 HUD 文本。"""

    line_list = [lines] if isinstance(lines, str) else lines
    max_chars = max((image_bgr.shape[1] - x - 12) // 9, 12)
    wrapped: list[str] = []

    for line in line_list:
        if len(line) <= max_chars:
            wrapped.append(line)
            continue
        current = ""
        for word in line.split(" "):
            candidate = f"{current} {word}".strip()
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    wrapped.append(current)
                current = word
        if current:
            wrapped.append(current)

    for idx, line in enumerate(wrapped):
        yy = y + idx * line_gap
        cv2.putText(image_bgr, line, (x, yy), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (15, 15, 15), 2, cv2.LINE_AA)
        cv2.putText(image_bgr, line, (x, yy), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (245, 245, 245), 1, cv2.LINE_AA)


def colorize_depth(depth_m: np.ndarray, min_depth: float, max_depth: float) -> np.ndarray:
    """把米制深度图转换为 Turbo 伪彩色 BGR 图。"""

    depth_f = np.asarray(depth_m, dtype=np.float32)
    denom = max(float(max_depth) - float(min_depth), 1e-6)
    norm = ((depth_f - float(min_depth)) / denom).clip(0.0, 1.0)
    vis = cv2.applyColorMap((norm * 255.0).astype(np.uint8), cv2.COLORMAP_TURBO)
    invalid = (depth_f <= float(min_depth)) | (depth_f >= float(max_depth)) | (~np.isfinite(depth_f))
    if invalid.any():
        vis[invalid] = 0
    return vis


def overlay_mask_contour(
    image_bgr: np.ndarray,
    mask_bw: np.ndarray,
    color: tuple[int, int, int] = (0, 255, 255),
) -> np.ndarray:
    """在图像上叠加 mask 半透明区域与外轮廓。"""

    vis = image_bgr.copy()
    if mask_bw is None or mask_bw.size == 0:
        return vis

    mask = (mask_bw > 0).astype(np.uint8)
    if mask.shape[:2] != vis.shape[:2]:
        mask = cv2.resize(mask, (vis.shape[1], vis.shape[0]), interpolation=cv2.INTER_NEAREST)

    color_img = np.zeros_like(vis)
    color_img[mask > 0] = color
    cv2.addWeighted(color_img, 0.35, vis, 1.0, 0.0, vis)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(vis, contours, -1, color, 2)
    return vis


def stack_stereo(left_bgr: np.ndarray, right_bgr: np.ndarray) -> np.ndarray:
    """左右图等高拼接。"""

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
    return np.hstack((left_bgr, right_bgr))


def tile_pose_depth_dashboard(pose_bgr: np.ndarray, depth_mask_bgr: np.ndarray) -> np.ndarray:
    """组合主 debug dashboard：左侧 pose/mask，右侧 depth+mask。"""

    h, w = pose_bgr.shape[:2]
    depth_panel = cv2.resize(depth_mask_bgr, (w, h), interpolation=cv2.INTER_AREA)
    draw_hud(pose_bgr, "POSE / MASK", x=8, y=22)
    draw_hud(depth_panel, "DEPTH + MASK", x=8, y=22)
    return np.hstack((pose_bgr, depth_panel))


def make_waiting_image(width: int = 960, height: int = 360, message: str = "Waiting for Quest stereo + camera_info...") -> np.ndarray:
    """生成等待画面，防止无输入时 OpenCV 窗口看起来像卡死。"""

    image = np.zeros((height, width, 3), dtype=np.uint8)
    draw_hud(
        image,
        [
            message,
            "Python v2 pose debug: ZMQ + Protobuf data plane only, no Unity pose output.",
            "Keys: 1/2/3/4 stage, r reset, q/ESC quit.",
        ],
        x=24,
        y=height // 2 - 28,
        line_gap=30,
    )
    return image

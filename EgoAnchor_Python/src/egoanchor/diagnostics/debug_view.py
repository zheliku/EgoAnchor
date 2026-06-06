"""pose debug OpenCV 可视化工具。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cv2
import numpy as np

from .image_utils import fit_to_size, stack_stereo
from egoanchor.perception import PoseObservation

if TYPE_CHECKING:
    from egoanchor.perception import FrameDiagnostics


def colorize_depth(depth: np.ndarray | None, min_depth: float = 0.1, max_depth: float = 5.0) -> np.ndarray:
    """把米制深度图转换为伪彩色 BGR 图。"""

    if depth is None:
        return np.zeros((240, 320, 3), dtype=np.uint8)
    depth = np.asarray(depth, dtype=np.float32)
    valid = np.isfinite(depth) & (depth > 0)
    if not np.any(valid):
        return np.zeros((depth.shape[0], depth.shape[1], 3), dtype=np.uint8)
    clipped = np.clip(depth, min_depth, max_depth)
    normalized = ((clipped - min_depth) / max(max_depth - min_depth, 1e-6) * 255.0).astype(np.uint8)
    color = cv2.applyColorMap(255 - normalized, cv2.COLORMAP_TURBO)
    color[~valid] = (0, 0, 0)
    return color


def overlay_mask_contour(image_bgr: np.ndarray, mask: np.ndarray | None, color: tuple[int, int, int] = (0, 255, 255)) -> np.ndarray:
    """在 BGR 图上叠加 mask 半透明区域和轮廓。"""

    output = image_bgr.copy()
    if mask is None:
        return output
    mask_u8 = (mask > 0).astype(np.uint8)
    if mask_u8.shape[:2] != output.shape[:2]:
        mask_u8 = cv2.resize(mask_u8, (output.shape[1], output.shape[0]), interpolation=cv2.INTER_NEAREST)
    color_layer = np.zeros_like(output)
    color_layer[mask_u8 > 0] = color
    output = cv2.addWeighted(output, 1.0, color_layer, 0.35, 0)
    contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(output, contours, -1, color, 2)
    return output


def make_waiting_image(width: int, height: int, title: str) -> np.ndarray:
    """生成 pose debug 等待画面。"""

    image = np.zeros((max(int(height), 1), max(int(width), 1), 3), dtype=np.uint8)
    cv2.putText(image, title, (24, height // 2 - 36), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (230, 230, 230), 2, cv2.LINE_AA)
    cv2.putText(image, "Waiting for Quest stereo + camera_info", (24, height // 2 + 2), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (160, 220, 255), 1, cv2.LINE_AA)
    cv2.putText(image, "Keys: 1/2/3/4 switch stage, r reset, q/ESC quit", (24, height // 2 + 34), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (160, 255, 180), 1, cv2.LINE_AA)
    return image


def draw_hud(image: np.ndarray, observation: PoseObservation | None, diagnostics: FrameDiagnostics) -> np.ndarray:
    """在 debug 图像左上角绘制关键诊断 HUD。"""

    output = image.copy()
    lines = [
        f"stage={diagnostics.stage} phase={diagnostics.phase} frame={diagnostics.frame_id}",
        f"pose={observation.has_pose if observation else False} source={observation.pose_source if observation else 'NONE'} score={observation.reliability_score if observation else 0.0:.2f}",
        f"det={diagnostics.det_count} mask={diagnostics.mask_area_ratio:.3f} mask_src={diagnostics.mask_source} depth(mask)={diagnostics.depth_valid_in_mask:.3f} depth(all)={diagnostics.depth_valid_ratio:.3f} depthScore={observation.depth_quality_score if observation else diagnostics.depth_quality_score:.2f}",
        f"depth med/iqr={diagnostics.depth_median_in_mask:.2f}/{diagnostics.depth_iqr_in_mask:.2f}m fps={diagnostics.fps:.1f}",
        f"ms yolo={diagnostics.timing.yolo_ms:.1f} depth={diagnostics.timing.depth_ms:.1f} cutie={diagnostics.timing.cutie_ms:.1f} pose={diagnostics.timing.pose_ms:.1f} total={diagnostics.timing.total_ms:.1f}",
    ]
    if diagnostics.segmenter_async:
        busy = "busy" if diagnostics.segmenter_busy else "idle"
        lines.append(
            f"seg_async={busy} done={diagnostics.segmenter_completed}/{diagnostics.segmenter_submitted} drop={diagnostics.segmenter_dropped}"
        )
    if observation and observation.reliability_flags:
        lines.append("flags=" + ",".join(observation.reliability_flags[:4]))
    if diagnostics.failure_reason:
        lines.append(f"failure={diagnostics.failure_reason}")
    if diagnostics.segmenter_error:
        lines.append(f"seg_error={diagnostics.segmenter_error[:96]}")

    y = 26
    for text in lines:
        cv2.putText(output, text, (14, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(output, text, (14, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 120), 1, cv2.LINE_AA)
        y += 24
    return output


def make_score_debug_view(
    diagnostics: FrameDiagnostics,
    observation: PoseObservation | None,
    width: int = 960,
    height: int = 540,
    min_depth: float = 0.1,
    max_depth: float = 5.0,
) -> np.ndarray:
    """构建独立 reliability / render consistency 调试窗口。"""

    canvas = np.zeros((max(int(height), 1), max(int(width), 1), 3), dtype=np.uint8)
    half_w = max(canvas.shape[1] // 2, 1)
    half_h = max(canvas.shape[0] // 2, 1)
    panels = [
        (_mask_panel(diagnostics.consistency_render_mask, "render mask", (0, 255, 120)), 0, 0),
        (_mask_panel(diagnostics.consistency_observed_mask, "observed mask", (0, 220, 255)), half_w, 0),
        (colorize_depth(diagnostics.consistency_render_depth, min_depth=min_depth, max_depth=max_depth), 0, half_h),
        (colorize_depth(diagnostics.consistency_observed_depth, min_depth=min_depth, max_depth=max_depth), half_w, half_h),
    ]
    labels = [
        ("render mask", 14, half_h - 14),
        ("observed mask", half_w + 14, half_h - 14),
        ("render depth", 14, canvas.shape[0] - 14),
        ("observed depth", half_w + 14, canvas.shape[0] - 14),
    ]
    for panel, x, y in panels:
        fitted = fit_to_size(panel, half_w, half_h)
        canvas[y : y + half_h, x : x + half_w] = fitted
    for text, x, y in labels:
        cv2.putText(canvas, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)

    lines = [
        f"score={observation.reliability_score if observation else 0.0:.2f} phase={diagnostics.score_phase:.2f} cons={diagnostics.score_consistency:.2f} depth={diagnostics.score_depth:.2f} jump={diagnostics.score_jump:.2f} mask={diagnostics.score_mask:.2f} reject={diagnostics.score_reject:.2f}",
        f"track_cons={diagnostics.track_consistency:.2f} iou={diagnostics.consistency_mask_iou:.2f} visible={diagnostics.consistency_render_visible_ratio:.2f} depthIn={diagnostics.consistency_depth_inlier:.2f} depthRes={diagnostics.consistency_depth_residual_m:.3f}m {diagnostics.consistency_ms:.1f}ms",
        f"status={diagnostics.consistency_status} expected={diagnostics.consistency_expected} renderArea={diagnostics.consistency_render_area_px} maskArea={diagnostics.mask_area_ratio:.3f} depthMask={diagnostics.depth_valid_in_mask:.3f} depthAll={diagnostics.depth_valid_ratio:.3f}",
    ]
    if observation and observation.reliability_flags:
        lines.append("flags=" + ",".join(observation.reliability_flags[:8]))
    y = 24
    for text in lines:
        cv2.putText(canvas, text, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(canvas, text, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 120), 1, cv2.LINE_AA)
        y += 24
    return canvas


def _mask_panel(mask: np.ndarray | None, title: str, color: tuple[int, int, int]) -> np.ndarray:
    """把二值 mask 转为彩色 debug panel。"""

    if mask is None:
        image = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.putText(image, "no signal", (10, 54), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (80, 160, 255), 1, cv2.LINE_AA)
    else:
        mask_u8 = (np.asarray(mask) > 0).astype(np.uint8)
        image = np.zeros((mask_u8.shape[0], mask_u8.shape[1], 3), dtype=np.uint8)
        image[mask_u8 > 0] = color
    cv2.putText(image, title, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
    return image


def tile_pose_depth_dashboard(
    diagnostics: FrameDiagnostics,
    observation: PoseObservation | None,
    width: int = 1280,
    height: int = 720,
    min_depth: float = 0.1,
    max_depth: float = 5.0,
) -> np.ndarray:
    """构建四宫格 pose debug dashboard。"""

    left = diagnostics.left_bgr if diagnostics.left_bgr is not None else np.zeros((240, 320, 3), dtype=np.uint8)
    right = diagnostics.right_bgr if diagnostics.right_bgr is not None else np.zeros_like(left)
    stereo = stack_stereo(left, right)
    mask_view = overlay_mask_contour(left, diagnostics.mask)
    if diagnostics.segmentation_overlay_bgr is not None:
        seg = diagnostics.segmentation_overlay_bgr
        if seg.shape[:2] != left.shape[:2]:
            seg = cv2.resize(seg, (left.shape[1], left.shape[0]), interpolation=cv2.INTER_LINEAR)
        mask_view = cv2.addWeighted(mask_view, 0.55, seg, 0.45, 0)
    depth_view = colorize_depth(diagnostics.depth, min_depth=min_depth, max_depth=max_depth)
    depth_view = overlay_mask_contour(depth_view, diagnostics.mask, color=(255, 255, 255))
    pose_view = diagnostics.pose_vis_bgr if diagnostics.pose_vis_bgr is not None else overlay_mask_contour(left, diagnostics.mask, color=(0, 255, 255))
    x, y, w, h = diagnostics.cutie_bbox_xywh
    if w > 0 and h > 0:
        cv2.rectangle(pose_view, (int(x), int(y)), (int(x + w), int(y + h)), (0, 255, 255), 2)

    cell_w = max(int(width) // 2, 1)
    cell_h = max(int(height) // 2, 1)
    top_left = fit_to_size(stereo, cell_w, cell_h)
    top_right = fit_to_size(mask_view, cell_w, cell_h)
    bottom_left = fit_to_size(depth_view, cell_w, cell_h)
    bottom_right = fit_to_size(pose_view, cell_w, cell_h)
    dashboard = np.vstack([np.hstack([top_left, top_right]), np.hstack([bottom_left, bottom_right])])
    dashboard = draw_hud(dashboard, observation, diagnostics)

    labels = [("stereo", 14, cell_h - 14), ("mask", cell_w + 14, cell_h - 14), ("depth", 14, height - 14), ("pose", cell_w + 14, height - 14)]
    for text, x, y in labels:
        cv2.putText(dashboard, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2, cv2.LINE_AA)
    return dashboard

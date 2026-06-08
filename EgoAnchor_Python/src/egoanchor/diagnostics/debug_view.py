"""pose debug OpenCV 可视化工具。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cv2
import numpy as np

from egoanchor.perception import PoseObservation
from egoanchor.utils import clamp01

from .image_utils import fit_to_size, stack_stereo

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
        f"det={diagnostics.det_count} mask={diagnostics.mask_area_ratio:.3f} mask_src={diagnostics.mask_source} depth(mask)={diagnostics.depth_valid_in_mask:.3f} depth(all)={diagnostics.depth_valid_ratio:.3f} depthScore={observation.score_depth if observation else diagnostics.score_depth:.2f}",
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
    """构建独立 reliability / render quality 调试窗口。"""

    canvas = np.zeros((max(int(height), 1), max(int(width), 1), 3), dtype=np.uint8)
    half_w = max(canvas.shape[1] // 2, 1)
    half_h = max(canvas.shape[0] // 2, 1)
    panels = [
        (
            _overlap_rgb_panel(
                diagnostics.render_quality_observed_rgb,
                diagnostics.render_quality_render_mask,
                diagnostics.render_quality_observed_mask,
            ),
            0,
            0,
        ),
        (
            _rgb_mask_panel(
                diagnostics.render_quality_render_rgb,
                diagnostics.render_quality_render_mask,
                "render RGB / projection",
                (0, 255, 120),
            ),
            half_w,
            0,
        ),
        (
            _depth_region_panel(
                diagnostics.render_quality_render_depth,
                diagnostics.render_quality_render_mask,
                "render surface depth",
                min_depth,
                max_depth,
                (0, 255, 120),
            ),
            0,
            half_h,
        ),
        (
            _depth_region_panel(
                diagnostics.render_quality_observed_depth,
                diagnostics.render_quality_observed_mask,
                "FFS depth / Cutie mask",
                min_depth,
                max_depth,
                (255, 255, 0),
            ),
            half_w,
            half_h,
        ),
    ]
    for panel, x, y in panels:
        fitted = fit_to_size(panel, half_w, half_h)
        canvas[y : y + half_h, x : x + half_w] = fitted

    lines = [
        f"score={observation.reliability_score if observation else 0.0:.2f} phase={diagnostics.score_phase:.2f} reproj={diagnostics.score_reprojection:.2f} depth={diagnostics.score_depth:.2f} jump={diagnostics.score_jump:.2f} mask={diagnostics.score_mask:.2f} reject={diagnostics.score_reject:.2f} conf={diagnostics.score_confidence:.2f}",
        f"track_reproj={diagnostics.track_reprojection:.2f} area={diagnostics.render_quality_area_ratio_score:.2f} iou={diagnostics.render_quality_mask_iou:.2f} renderCov={diagnostics.render_quality_render_visible_ratio:.2f} obsCov={diagnostics.render_quality_observed_visible_ratio:.2f}",
        f"depthIn={diagnostics.render_quality_depth_inlier:.2f} depthAlign={diagnostics.render_quality_depth_alignment:.2f} depthRes={diagnostics.render_quality_depth_residual_m:.3f}m status={diagnostics.render_quality_status} {diagnostics.render_quality_ms:.1f}ms",
        f"expected={diagnostics.render_quality_expected} renderArea={diagnostics.render_quality_render_area_px} maskArea={diagnostics.mask_area_ratio:.3f} depthMask={diagnostics.depth_valid_in_mask:.3f} depthAll={diagnostics.depth_valid_ratio:.3f}",
    ]
    if observation and observation.reliability_flags:
        lines.append("flags=" + ",".join(observation.reliability_flags[:8]))
    y = 24
    for text in lines:
        cv2.putText(canvas, text, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(canvas, text, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 120), 1, cv2.LINE_AA)
        y += 24
    _draw_score_bars(canvas, diagnostics, x=12, y=y + 4, width=min(420, canvas.shape[1] - 24), row_h=20)
    return canvas


def _overlap_rgb_panel(observed_rgb: np.ndarray | None, render_mask: np.ndarray | None, observed_mask: np.ndarray | None) -> np.ndarray:
    """在真实 RGB 上显示投影 mask、Cutie mask 和二者交集。"""

    image = _ensure_bgr(observed_rgb, "no observed RGB")
    render = _resize_mask_like(render_mask, image)
    observed = _resize_mask_like(observed_mask, image)
    overlay = np.zeros_like(image)
    if render is not None:
        overlay[render] = (0, 255, 120)
    if observed is not None:
        overlay[observed] = (255, 255, 0)
    if render is not None and observed is not None:
        overlay[render & observed] = (0, 220, 255)
    image = cv2.addWeighted(image, 1.0, overlay, 0.42, 0)
    _draw_mask_contour(image, render, (0, 255, 120))
    _draw_mask_contour(image, observed, (255, 255, 0))
    _put_panel_title(image, "observed RGB / overlap")
    return image


def _rgb_mask_panel(rgb: np.ndarray | None, mask: np.ndarray | None, title: str, color: tuple[int, int, int]) -> np.ndarray:
    """显示渲染 RGB，并用 mask 标出本帧投影区域。"""

    image = _ensure_bgr(rgb, "no render RGB")
    mask_bool = _resize_mask_like(mask, image)
    if mask_bool is not None:
        image[~mask_bool] = (0, 0, 0)
        image = overlay_mask_contour(image, mask_bool, color=color)
    _put_panel_title(image, title)
    return image


def _depth_region_panel(
    depth: np.ndarray | None,
    mask: np.ndarray | None,
    title: str,
    min_depth: float,
    max_depth: float,
    color: tuple[int, int, int],
) -> np.ndarray:
    """显示指定 mask 区域内的深度图，便于肉眼比较渲染深度和 FFS 深度。"""

    image = colorize_depth(depth, min_depth=min_depth, max_depth=max_depth)
    mask_bool = _resize_mask_like(mask, image)
    if mask_bool is not None:
        image[~mask_bool] = (0, 0, 0)
        image = overlay_mask_contour(image, mask_bool, color=color)
    _put_panel_title(image, title)
    return image


def _ensure_bgr(rgb: np.ndarray | None, empty_text: str) -> np.ndarray:
    """把 RGB debug 图转为 BGR；无信号时返回黑底提示图。"""

    if rgb is None:
        image = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.putText(image, empty_text, (10, 54), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (80, 160, 255), 1, cv2.LINE_AA)
        return image
    arr = np.asarray(rgb)
    if arr.ndim == 2:
        arr = np.repeat(arr[..., None], 3, axis=2)
    if np.issubdtype(arr.dtype, np.floating):
        finite = arr[np.isfinite(arr)]
        if finite.size > 0 and float(np.max(finite)) <= 1.0:
            arr = arr * 255.0
    image = np.clip(arr[..., :3], 0, 255).astype(np.uint8)
    return cv2.cvtColor(image, cv2.COLOR_RGB2BGR)


def _resize_mask_like(mask: np.ndarray | None, image_bgr: np.ndarray) -> np.ndarray | None:
    """把二值 mask 缩放到目标图像尺寸。"""

    if mask is None:
        return None
    mask_u8 = (np.asarray(mask) > 0).astype(np.uint8)
    if mask_u8.shape[:2] != image_bgr.shape[:2]:
        mask_u8 = cv2.resize(mask_u8, (image_bgr.shape[1], image_bgr.shape[0]), interpolation=cv2.INTER_NEAREST)
    return mask_u8 > 0


def _draw_mask_contour(image_bgr: np.ndarray, mask: np.ndarray | None, color: tuple[int, int, int]) -> None:
    """只绘制 mask 轮廓，用于在 RGB 面板上区分两个来源。"""

    if mask is None:
        return
    mask_u8 = (np.asarray(mask) > 0).astype(np.uint8)
    contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(image_bgr, contours, -1, color, 2)


def _put_panel_title(image_bgr: np.ndarray, title: str) -> None:
    """在 panel 左下角绘制标题，避免遮挡中心比较区域。"""

    y = max(image_bgr.shape[0] - 14, 18)
    cv2.putText(image_bgr, title, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(image_bgr, title, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)


def _draw_score_bars(canvas: np.ndarray, diagnostics: FrameDiagnostics, x: int, y: int, width: int, row_h: int) -> None:
    """在 score debug 画面绘制 Gate/Quality/Confidence 子分条，便于现场观察是哪一项降分。"""

    items = [
        ("phase", diagnostics.score_phase),
        ("reproj", diagnostics.score_reprojection),
        ("depth", diagnostics.score_depth),
        ("jump", diagnostics.score_jump),
        ("mask", diagnostics.score_mask),
        ("reject", diagnostics.score_reject),
        ("conf", diagnostics.score_confidence),
    ]
    label_w = 70
    bar_w = max(int(width) - label_w - 54, 1)
    for index, (name, value) in enumerate(items):
        row_y = int(y + index * row_h)
        score = clamp01(value)
        fill = int(round(bar_w * score))
        cv2.putText(canvas, name, (x, row_y + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 2, cv2.LINE_AA)
        cv2.putText(canvas, name, (x, row_y + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 240, 255), 1, cv2.LINE_AA)
        bar_x = x + label_w
        cv2.rectangle(canvas, (bar_x, row_y + 4), (bar_x + bar_w, row_y + 16), (55, 55, 55), 1)
        color = (0, 210, 80) if score >= 0.65 else (0, 180, 255) if score >= 0.35 else (0, 90, 255)
        cv2.rectangle(canvas, (bar_x + 1, row_y + 5), (bar_x + fill, row_y + 15), color, -1)
        cv2.putText(canvas, f"{score:.2f}", (bar_x + bar_w + 8, row_y + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 2, cv2.LINE_AA)
        cv2.putText(canvas, f"{score:.2f}", (bar_x + bar_w + 8, row_y + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 240, 255), 1, cv2.LINE_AA)


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

"""pose debug OpenCV 可视化工具。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cv2
import numpy as np

from egoanchor.perception import PoseObservation
from egoanchor.reliability import ReprojectionChecker, ReprojectionDiffMaps
from egoanchor.utils import clamp01

from .image_utils import fit_to_size, stack_stereo

if TYPE_CHECKING:
    from egoanchor.perception import FrameDiagnostics


POSE_HUD_LINE_COUNT = 10
"""主 pose debug 横幅固定行数；面板布局不能随诊断行出现/消失而跳动。"""

SCORE_HUD_LINE_COUNT = 5
"""评分 debug 横幅固定文本行数；缺失 flags 时保留空槽位。"""

SCORE_BAR_COUNT = 3
"""评分 debug 横幅中的 V/C/D 子分条数量。"""


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
    lines = _fit_banner_lines(_hud_lines(observation, diagnostics), POSE_HUD_LINE_COUNT, max(output.shape[1] - 28, 1))
    _draw_text_lines(output, lines, x=14, y=26)
    return output


def _hud_lines(observation: PoseObservation | None, diagnostics: FrameDiagnostics) -> list[str]:
    """生成 pose debug 主窗口顶部诊断文本，集中维护字段顺序。"""

    lines = [
        f"stage={diagnostics.stage} phase={diagnostics.phase} frame={diagnostics.frame_id}",
        f"pose={observation.has_pose if observation else False} source={observation.pose_source if observation else 'NONE'} score={observation.reliability_score if observation else 0.0:.2f}",
        f"det={diagnostics.det_count} depthScore={observation.score_depth if observation else diagnostics.score_depth:.2f} mask={diagnostics.mask_area_ratio:.3f} mask_src={diagnostics.mask_source} depth(mask)={diagnostics.depth_valid_in_mask:.3f} depth(all)={diagnostics.depth_valid_ratio:.3f}",
        f"depth med/iqr={diagnostics.depth_median_m:.2f}/{diagnostics.depth_iqr_m:.2f}m fps={diagnostics.fps:.1f}",
        f"ms yolo={diagnostics.timing.yolo_ms:.1f} depth={diagnostics.timing.depth_ms:.1f} cutie={diagnostics.timing.cutie_ms:.1f} pose={diagnostics.timing.pose_ms:.1f} rq={diagnostics.timing.render_quality_ms:.1f} total={diagnostics.timing.total_ms:.1f}",
        f"ui_render debug={diagnostics.debug_render_ms:.1f}ms score={diagnostics.score_render_ms:.1f}ms",
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
    return lines


def _pose_banner_height() -> int:
    """返回主窗口顶部信息区固定高度。"""

    return POSE_HUD_LINE_COUNT * 24 + 22


def _fit_banner_lines(lines: list[str], line_count: int, max_width: int) -> list[str]:
    """把横幅文本整理到固定槽位，并按窗口宽度截断长行。"""

    target_count = max(int(line_count), 0)
    visible = list(lines[:target_count])
    if len(lines) > target_count and target_count > 0:
        visible[-1] = f"{visible[-1]} ..."
    while len(visible) < target_count:
        visible.append("")
    return [_clip_text_to_width(text, max_width, scale=0.55, thickness=1) for text in visible]


def _clip_text_to_width(text: str, max_width: int, *, scale: float, thickness: int) -> str:
    """按 OpenCV 实际像素宽度截断调试文本，避免长状态串横向溢出。"""

    value = str(text)
    target_width = max(int(max_width), 1)
    if _text_width(value, scale, thickness) <= target_width:
        return value
    suffix = "..."
    if _text_width(suffix, scale, thickness) > target_width:
        return ""
    low = 0
    high = len(value)
    while low < high:
        mid = (low + high + 1) // 2
        candidate = value[:mid].rstrip() + suffix
        if _text_width(candidate, scale, thickness) <= target_width:
            low = mid
        else:
            high = mid - 1
    return value[:low].rstrip() + suffix


def _text_width(text: str, scale: float, thickness: int) -> int:
    """返回 OpenCV Hershey 字体文本宽度。"""

    return int(cv2.getTextSize(str(text), cv2.FONT_HERSHEY_SIMPLEX, float(scale), int(thickness))[0][0])


def _draw_text_lines(
    image: np.ndarray,
    lines: list[str],
    x: int,
    y: int,
    color: tuple[int, int, int] = (0, 255, 120),
    line_h: int = 24,
) -> None:
    """用黑色描边绘制多行调试文本，保证浅色图像上仍可读。"""

    row_y = int(y)
    for text in lines:
        cv2.putText(image, text, (x, row_y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(image, text, (x, row_y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 1, cv2.LINE_AA)
        row_y += line_h


def _paste_labeled_panel(
    canvas: np.ndarray,
    panel: np.ndarray,
    label: str,
    x: int,
    y: int,
    width: int,
    height: int,
    label_h: int = 30,
    background_color: tuple[int, int, int] = (0, 0, 0),
) -> None:
    """把面板图像贴到画布，并在图像下方绘制独立标签条。"""

    panel_w = max(int(width), 1)
    panel_h = max(int(height), 1)
    caption_h = min(max(int(label_h), 0), max(panel_h - 1, 0))
    image_h = max(panel_h - caption_h, 1)
    fitted = _fit_to_size(panel, panel_w, image_h, background_color)
    canvas[y : y + image_h, x : x + panel_w] = fitted
    if caption_h <= 0:
        return
    caption_y = y + image_h
    cv2.rectangle(canvas, (x, caption_y), (x + panel_w, y + panel_h), (10, 10, 10), -1)
    cv2.line(canvas, (x, caption_y), (x + panel_w, caption_y), (45, 45, 45), 1)
    if caption_h < 18:
        return
    text_y = caption_y + min(caption_h - 8, 21)
    _put_caption_label(canvas, label, x + 14, text_y, max(panel_w - 24, 1))


def _put_caption_label(canvas: np.ndarray, label: str, x: int, y: int, max_width: int) -> None:
    """在标签条内绘制自适应字号文本，避免长标签越界到相邻 panel。"""

    text = str(label)
    scale = 0.65
    thickness = 1
    while scale > 0.42:
        text_w, _text_h = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)[0]
        if text_w <= max_width:
            break
        scale -= 0.05
    if cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)[0][0] > max_width:
        while len(text) > 4 and cv2.getTextSize(text + "...", cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)[0][0] > max_width:
            text = text[:-1]
        text = text.rstrip() + "..."
    cv2.putText(canvas, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(canvas, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (235, 235, 235), thickness, cv2.LINE_AA)


def _fit_to_size(image: np.ndarray, width: int, height: int, background_color: tuple[int, int, int]) -> np.ndarray:
    """缩放 panel 并用指定背景填充 letterbox 区域。"""

    if tuple(background_color) == (0, 0, 0):
        return fit_to_size(image, width, height)
    target_width = max(int(width), 1)
    target_height = max(int(height), 1)
    scale = min(target_width / max(image.shape[1], 1), target_height / max(image.shape[0], 1))
    new_w = max(1, int(image.shape[1] * scale))
    new_h = max(1, int(image.shape[0] * scale))
    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
    canvas = np.full((target_height, target_width, 3), background_color, dtype=np.uint8)
    x0 = (target_width - new_w) // 2
    y0 = (target_height - new_h) // 2
    canvas[y0 : y0 + new_h, x0 : x0 + new_w] = resized
    return canvas


def make_score_debug_view(
    diagnostics: FrameDiagnostics,
    observation: PoseObservation | None,
    width: int = 960,
    height: int = 800,
    min_depth: float = 0.1,
    max_depth: float = 5.0,
) -> np.ndarray:
    """构建独立 reliability / render quality 调试窗口。"""

    canvas = np.zeros((max(int(height), 1), max(int(width), 1), 3), dtype=np.uint8)
    lines = _fit_banner_lines(_score_debug_lines(diagnostics, observation), SCORE_HUD_LINE_COUNT, max(canvas.shape[1] - 24, 1))
    banner_h = min(_score_banner_height(), max(canvas.shape[0] - 2, 1))
    panel_area_h = max(canvas.shape[0] - banner_h, 2)
    col_w = max(canvas.shape[1] // 3, 1)
    row_h = max(panel_area_h // 2, 1)
    right_w = max(canvas.shape[1] - col_w * 2, 1)
    bottom_h = max(panel_area_h - row_h, 1)
    diff_maps = _reprojection_diff_maps(diagnostics)
    panels = [
        (
            _observed_rgb_contour_panel(
                diagnostics.render_quality_observed_rgb,
                diagnostics.render_quality_render_mask,
                diagnostics.render_quality_observed_mask,
            ),
            "RGB: green render / cyan Cutie",
            0,
            banner_h,
            col_w,
            row_h,
        ),
        (
            _render_projection_panel(
                diagnostics.render_quality_render_rgb,
                diagnostics.render_quality_render_mask,
            ),
            "render RGB on checkerboard",
            col_w,
            banner_h,
            col_w,
            row_h,
        ),
        (
            _lab_residual_panel(diff_maps, diagnostics.render_quality_observed_rgb),
            _lab_residual_label(diff_maps),
            col_w * 2,
            banner_h,
            right_w,
            row_h,
        ),
        (
            _depth_map_panel(
                diagnostics.render_quality_observed_depth,
                diagnostics.render_quality_observed_mask,
                min_depth,
                max_depth,
                (255, 255, 0),
            ),
            "FFS observed depth",
            0,
            banner_h + row_h,
            col_w,
            bottom_h,
        ),
        (
            _depth_map_panel(
                diagnostics.render_quality_render_depth,
                diagnostics.render_quality_render_mask,
                min_depth,
                max_depth,
                (0, 255, 120),
            ),
            "render projected depth",
            col_w,
            banner_h + row_h,
            col_w,
            bottom_h,
        ),
        (
            _depth_residual_panel(
                diagnostics.render_quality_render_depth,
                diagnostics.render_quality_observed_depth,
                diagnostics.render_quality_render_mask,
                diagnostics.render_quality_observed_mask,
                diagnostics.render_quality_observed_rgb,
            ),
            "depth diff: blue aligned / red large",
            col_w * 2,
            banner_h + row_h,
            right_w,
            bottom_h,
        ),
    ]
    for panel, label, x, y, panel_w, panel_h in panels:
        _paste_labeled_panel(canvas, panel, label, x, y, panel_w, panel_h, background_color=(42, 42, 42))

    _draw_text_lines(canvas, lines, x=12, y=24)
    _draw_score_bars(canvas, diagnostics, x=12, y=24 + len(lines) * 24 + 4, width=min(420, canvas.shape[1] - 24), row_h=20)
    return canvas


def _score_debug_lines(diagnostics: FrameDiagnostics, observation: PoseObservation | None) -> list[str]:
    """生成 score debug 顶部横幅文本，集中维护字段顺序。"""

    # 计算 S_med (从 D 和 rho_inlier 反推)
    # D = 0.6*rho_inlier + 0.4*S_med
    # => S_med = (D - 0.6*rho_inlier) / 0.4
    rho_inlier = diagnostics.render_quality_depth_inlier
    depth_score = diagnostics.score_depth
    s_med = (depth_score - 0.6 * rho_inlier) / 0.4 if rho_inlier >= 0 else 0.0
    s_med = max(0.0, min(1.0, s_med))  # clamp to [0,1]

    lines = [
        f"R={observation.reliability_score if observation else 0.0:.3f} = V({diagnostics.score_mask:.3f}) x G(C={diagnostics.score_reprojection:.3f}, D={diagnostics.score_depth:.3f})",
        f"D = 0.6*rho_in({rho_inlier:.3f}) + 0.4*S_med({s_med:.3f})  |  med_res={diagnostics.render_quality_depth_residual_m*1000:.1f}mm",
        f"reproj={diagnostics.color_reprojection:.2f} area={diagnostics.render_quality_area_ratio_score:.2f} iou={diagnostics.render_quality_mask_iou:.2f} renderCov={diagnostics.render_quality_render_visible_ratio:.2f} obsCov={diagnostics.render_quality_observed_visible_ratio:.2f}",
        f"status={diagnostics.render_quality_status} depthAlign={diagnostics.render_quality_depth_alignment:.3f} renderArea={diagnostics.render_quality_render_area_px}px {diagnostics.render_quality_ms:.1f}ms",
    ]
    if observation and observation.reliability_flags:
        lines.append("flags=" + ",".join(observation.reliability_flags[:8]))
    return lines


def _score_banner_height() -> int:
    """返回评分窗口固定横幅高度。"""

    text_h = SCORE_HUD_LINE_COUNT * 24
    score_bar_h = SCORE_BAR_COUNT * 20
    return text_h + score_bar_h + 36


def _observed_rgb_contour_panel(observed_rgb: np.ndarray | None, render_mask: np.ndarray | None, observed_mask: np.ndarray | None) -> np.ndarray:
    """在真实 RGB 上只画轮廓，保留物体原始颜色供截图比较。"""

    image = _ensure_bgr(observed_rgb, "no observed RGB")
    render = _resize_mask_like(render_mask, image)
    observed = _resize_mask_like(observed_mask, image)
    if render is not None and observed is not None:
        _draw_mask_contour(image, render & observed, (255, 255, 255), thickness=1)
    _draw_mask_contour(image, render, (0, 255, 120))
    _draw_mask_contour(image, observed, (255, 255, 0))
    return image


def _reprojection_diff_maps(diagnostics: FrameDiagnostics) -> ReprojectionDiffMaps | None:
    """用重投影 checker 的同源逻辑生成 ZNCC debug 三联图数据。"""

    if (
        diagnostics.render_quality_render_rgb is None
        or diagnostics.render_quality_observed_rgb is None
        or diagnostics.render_quality_render_mask is None
        or diagnostics.render_quality_observed_mask is None
    ):
        return None
    try:
        return ReprojectionChecker.color_diff_maps(
            diagnostics.render_quality_render_rgb,
            diagnostics.render_quality_observed_rgb,
            diagnostics.render_quality_render_mask,
            diagnostics.render_quality_observed_mask,
        )
    except ValueError:
        return None


def _render_projection_panel(render_rgb: np.ndarray | None, render_mask: np.ndarray | None) -> np.ndarray:
    """把渲染 RGB 按投影 mask 放在棋盘背景上，避免黑底误导轮廓判断。"""

    image = _ensure_bgr(render_rgb, "no render RGB")
    mask_bool = _resize_mask_like(render_mask, image)
    if mask_bool is not None:
        background = _checkerboard_background(image.shape[0], image.shape[1])
        image = _composite_mask_region(image, mask_bool, background)
        _draw_mask_contour(image, mask_bool, (0, 255, 120))
    return image


def _lab_residual_panel(diff_maps: ReprojectionDiffMaps | None, observed_rgb: np.ndarray | None) -> np.ndarray:
    """把 LAB z-score 残差叠在观测图灰度上下文中，显示颜色差异位置。"""

    if diff_maps is None:
        return _empty_panel("no LAB residual")
    image = _context_panel(observed_rgb, diff_maps.residual_heatmap_bgr.shape[:2])
    heatmap = diff_maps.residual_heatmap_bgr.copy()
    core_mask = _resize_mask_like(diff_maps.core_mask, image)
    if core_mask is not None:
        blended = cv2.addWeighted(image, 0.35, heatmap, 0.65, 0)
        image[core_mask] = blended[core_mask]
        _draw_mask_contour(image, core_mask, (255, 255, 255), thickness=1)
    return _append_heatmap_legend(image, cv2.COLORMAP_JET, low_label="low", high_label="high")


def _lab_residual_label(diff_maps: ReprojectionDiffMaps | None) -> str:
    """生成 LAB 残差面板标签，把分数放到独立标签条而不是图像内。"""

    if diff_maps is None:
        return "LAB residual unavailable"
    return f"LAB residual on RGB ZNCC={diff_maps.score:.2f}"


def _depth_map_panel(
    depth: np.ndarray | None,
    mask: np.ndarray | None,
    min_depth: float,
    max_depth: float,
    color: tuple[int, int, int],
) -> np.ndarray:
    """显示原始深度伪彩色图，并只用轮廓标出对应 mask。"""

    image = _colorize_depth_neutral(depth, min_depth=min_depth, max_depth=max_depth)
    mask_bool = _resize_mask_like(mask, image)
    if mask_bool is not None:
        _draw_mask_contour(image, mask_bool, color)
    return image


def _depth_residual_panel(
    render_depth: np.ndarray | None,
    observed_depth: np.ndarray | None,
    render_mask: np.ndarray | None,
    observed_mask: np.ndarray | None,
    observed_rgb: np.ndarray | None,
) -> np.ndarray:
    """显示渲染深度与 FFS 深度在交集内的残差热力图。"""

    if render_depth is None or observed_depth is None:
        return _empty_panel("no depth residual")
    render = np.asarray(render_depth, dtype=np.float32)
    observed = np.asarray(observed_depth, dtype=np.float32)
    if render.shape != observed.shape:
        return _empty_panel("depth shape mismatch")
    image = _context_panel(observed_rgb, render.shape[:2])
    render_bool = _resize_mask_like(render_mask, image)
    observed_bool = _resize_mask_like(observed_mask, image)
    if render_bool is None:
        render_bool = np.isfinite(render) & (render > 0.0)
    if observed_bool is None:
        observed_bool = np.isfinite(observed) & (observed > 0.0)
    valid = render_bool & observed_bool & np.isfinite(render) & np.isfinite(observed) & (render > 0.0) & (observed > 0.0)
    if not np.any(valid):
        _draw_mask_contour(image, render_bool, (0, 255, 120))
        _draw_mask_contour(image, observed_bool, (255, 255, 0))
        return image

    residual = np.zeros(render.shape, dtype=np.float32)
    residual[valid] = np.abs(render[valid] - observed[valid])
    scale = max(float(np.percentile(residual[valid], 95)), 1e-3)
    normalized = np.clip(residual / scale * 255.0, 0.0, 255.0).astype(np.uint8)
    heatmap = cv2.applyColorMap(normalized, cv2.COLORMAP_TURBO)
    blended = cv2.addWeighted(image, 0.35, heatmap, 0.65, 0)
    image[valid] = blended[valid]
    _draw_mask_contour(image, render_bool, (0, 255, 120))
    _draw_mask_contour(image, observed_bool, (255, 255, 0))
    _draw_mask_contour(image, valid, (255, 255, 255), thickness=1)
    return _append_heatmap_legend(image, cv2.COLORMAP_TURBO, low_label="0", high_label=f"p95={_format_distance(scale)}")


def _append_heatmap_legend(
    image_bgr: np.ndarray,
    colormap: int,
    *,
    low_label: str,
    high_label: str,
) -> np.ndarray:
    """在热力图右侧追加竖向色标，说明冷色到热色的数值含义。"""

    image = np.asarray(image_bgr, dtype=np.uint8)
    height = max(int(image.shape[0]), 1)
    legend_w = 88
    bar_w = 14
    pad = 8
    legend = np.full((height, legend_w, 3), 34, dtype=np.uint8)
    bar_h = max(height - 36, 12)
    y0 = max((height - bar_h) // 2, 4)
    x0 = pad
    gradient = np.linspace(255, 0, bar_h, dtype=np.uint8).reshape(bar_h, 1)
    bar = cv2.applyColorMap(np.repeat(gradient, bar_w, axis=1), colormap)
    legend[y0 : y0 + bar_h, x0 : x0 + bar_w] = bar
    cv2.rectangle(legend, (x0, y0), (x0 + bar_w - 1, y0 + bar_h - 1), (225, 225, 225), 1)
    _put_tiny_text(legend, high_label, x0 + bar_w + 6, max(y0 + 10, 12))
    _put_tiny_text(legend, low_label, x0 + bar_w + 6, min(y0 + bar_h, height - 6))
    return np.hstack([image, legend])


def _put_tiny_text(image_bgr: np.ndarray, text: str, x: int, y: int) -> None:
    """绘制热力图色标小字，保留黑色描边以适应亮色背景。"""

    cv2.putText(image_bgr, text, (int(x), int(y)), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (0, 0, 0), 2, cv2.LINE_AA)
    cv2.putText(image_bgr, text, (int(x), int(y)), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (235, 235, 235), 1, cv2.LINE_AA)


def _format_distance(distance_m: float) -> str:
    """把米制残差格式化成适合色标显示的短文本。"""

    value = max(float(distance_m), 0.0)
    if value < 0.01:
        return f"{value * 1000.0:.1f}mm"
    if value < 1.0:
        return f"{value * 100.0:.1f}cm"
    return f"{value:.2f}m"


def _colorize_depth_neutral(depth: np.ndarray | None, min_depth: float, max_depth: float) -> np.ndarray:
    """把深度图转成伪彩色，并用中性灰背景显示无效区域。"""

    if depth is None:
        return _empty_panel("no depth")
    depth_arr = np.asarray(depth, dtype=np.float32)
    if depth_arr.ndim != 2:
        return _empty_panel("depth shape invalid")
    image = colorize_depth(depth_arr, min_depth=min_depth, max_depth=max_depth)
    valid = np.isfinite(depth_arr) & (depth_arr > 0.0)
    image[~valid] = (48, 48, 48)
    return image


def _ensure_bgr(rgb: np.ndarray | None, empty_text: str) -> np.ndarray:
    """把 RGB debug 图转为 BGR；无信号时返回中性占位图。"""

    if rgb is None:
        return _empty_panel(empty_text)
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


def _draw_mask_contour(image_bgr: np.ndarray, mask: np.ndarray | None, color: tuple[int, int, int], thickness: int = 2) -> None:
    """只绘制 mask 轮廓，用于在 RGB 面板上区分两个来源。"""

    if mask is None:
        return
    mask_u8 = (np.asarray(mask) > 0).astype(np.uint8)
    contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(image_bgr, contours, -1, color, max(1, int(thickness)))


def _context_panel(rgb: np.ndarray | None, shape_hw: tuple[int, int]) -> np.ndarray:
    """生成残差图背景；优先用观测 RGB 的灰度上下文，否则用中性棋盘。"""

    height, width = max(int(shape_hw[0]), 1), max(int(shape_hw[1]), 1)
    if rgb is None:
        return _checkerboard_background(height, width)
    image = _ensure_bgr(rgb, "no observed RGB")
    if image.shape[:2] != (height, width):
        image = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray_bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    return cv2.addWeighted(gray_bgr, 0.72, np.full_like(gray_bgr, 42), 0.28, 0)


def _checkerboard_background(height: int, width: int, tile: int = 12) -> np.ndarray:
    """生成中性棋盘背景，区分无数据区域但不抢物体颜色信息。"""

    target_h = max(int(height), 1)
    target_w = max(int(width), 1)
    tile_size = max(int(tile), 1)
    yy, xx = np.indices((target_h, target_w))
    pattern = ((xx // tile_size + yy // tile_size) % 2).astype(np.uint8)
    background = np.empty((target_h, target_w, 3), dtype=np.uint8)
    background[pattern == 0] = (46, 46, 46)
    background[pattern == 1] = (72, 72, 72)
    return background


def _composite_mask_region(image_bgr: np.ndarray, mask: np.ndarray, background_bgr: np.ndarray) -> np.ndarray:
    """只把 mask 内图像贴到背景上，避免 renderer 黑底参与视觉判断。"""

    mask_bool = np.asarray(mask) > 0
    output = background_bgr.copy()
    output[mask_bool] = image_bgr[mask_bool]
    return output


def _empty_panel(text: str, width: int = 320, height: int = 240) -> np.ndarray:
    """生成无信号占位 panel；只用于解释缺失数据，不承担普通标题。"""

    image = np.full((max(int(height), 1), max(int(width), 1), 3), 32, dtype=np.uint8)
    cv2.putText(image, text, (10, 54), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (80, 160, 255), 1, cv2.LINE_AA)
    return image


def _draw_score_bars(canvas: np.ndarray, diagnostics: FrameDiagnostics, x: int, y: int, width: int, row_h: int) -> None:
    """在 score debug 画面绘制 VCD 子分条（V/C/D），便于现场观察是哪一项降分。"""

    items = [
        ("reproj(C)", diagnostics.score_reprojection),
        ("depth(D)", diagnostics.score_depth),
        ("mask(V)", diagnostics.score_mask),
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

    canvas = np.zeros((max(int(height), 1), max(int(width), 1), 3), dtype=np.uint8)
    lines = _fit_banner_lines(_hud_lines(observation, diagnostics), POSE_HUD_LINE_COUNT, max(canvas.shape[1] - 28, 1))
    banner_h = min(_pose_banner_height(), max(canvas.shape[0] - 2, 1))
    panel_area_h = max(canvas.shape[0] - banner_h, 2)
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
    depth_mask = _resize_mask_like(diagnostics.mask, depth_view)
    _draw_mask_contour(depth_view, depth_mask, color=(255, 255, 255), thickness=1)
    pose_view = diagnostics.pose_vis_bgr if diagnostics.pose_vis_bgr is not None else overlay_mask_contour(left, diagnostics.mask, color=(0, 255, 255))
    x, y, w, h = diagnostics.cutie_bbox_xywh
    if w > 0 and h > 0:
        cv2.rectangle(pose_view, (int(x), int(y)), (int(x + w), int(y + h)), (0, 255, 255), 2)

    cell_w = max(canvas.shape[1] // 2, 1)
    right_w = max(canvas.shape[1] - cell_w, 1)
    row_h = max(panel_area_h // 2, 1)
    bottom_h = max(panel_area_h - row_h, 1)
    panels = [
        (stereo, "stereo", 0, banner_h, cell_w, row_h),
        (mask_view, "mask", cell_w, banner_h, right_w, row_h),
        (depth_view, "depth", 0, banner_h + row_h, cell_w, bottom_h),
        (pose_view, "pose", cell_w, banner_h + row_h, right_w, bottom_h),
    ]
    for panel, label, panel_x, panel_y, panel_w, panel_h in panels:
        _paste_labeled_panel(canvas, panel, label, panel_x, panel_y, panel_w, panel_h)

    _draw_text_lines(canvas, lines, x=14, y=26)
    return canvas

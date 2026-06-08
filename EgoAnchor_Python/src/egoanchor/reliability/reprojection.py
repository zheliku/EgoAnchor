"""重投影质量评分。"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from egoanchor.utils import clamp01


@dataclass(frozen=True, slots=True)
class ReprojectionResult:
    """单帧渲染投影与观测图像在可见交集内的颜色相似度结果。"""

    score: float
    """重投影颜色分，范围 0..1；只来自 Cutie mask 与投影 mask 交集区域。"""

    color_similarity: float
    """重叠核心区域的 LAB 颜色相似度。"""

    area_ratio_score: float
    """观测 mask 面积与渲染投影面积的比例分，低值表示遮挡或投影面积明显过大。"""

    mask_iou: float
    """渲染 mask 与观测 mask 的 IoU。"""

    render_visible_ratio: float
    """渲染前景中被观测 mask 覆盖的比例。"""

    observed_visible_ratio: float
    """观测 mask 中被渲染前景解释的比例。"""

    render_area_px: int
    """渲染前景像素数量。"""

    observed_area_px: int
    """观测前景像素数量。"""

    valid: bool
    """本帧重投影信号是否可用于可靠性评分。"""

    status: str = "invalid"
    """重投影信号状态，例如 valid、map_shape_invalid、render_area_tiny。"""

    render_mask: np.ndarray | None = None
    """用于 debug 的渲染 mask。"""

    observed_mask: np.ndarray | None = None
    """用于 debug 的观测 mask。"""

    render_rgb: np.ndarray | None = None
    """用于 debug 的渲染 RGB。"""

    observed_rgb: np.ndarray | None = None
    """用于 debug 的观测 RGB。"""


class ReprojectionChecker:
    """只评估渲染 RGB 与观测 RGB 在可见交集内的颜色相似度。"""

    def __init__(self, min_render_area_px: int = 50) -> None:
        """保存最小渲染面积。"""

        self.min_render_area_px = max(1, int(min_render_area_px))
        """渲染前景过小时判为无效信号的像素阈值。"""

    def score_maps(
        self,
        render_color_rgb: np.ndarray,
        observed_rgb: np.ndarray,
        render_mask: np.ndarray,
        observed_mask: np.ndarray,
    ) -> ReprojectionResult:
        """根据同尺寸渲染/观测 color 和 mask 计算可见交集颜色分。"""

        return self._score_from_maps(
            render_color_rgb,
            observed_rgb,
            render_mask,
            observed_mask,
            min_render_area_px=self.min_render_area_px,
        )

    @staticmethod
    def _score_from_maps(
        render_color_rgb: np.ndarray,
        observed_rgb: np.ndarray,
        render_mask: np.ndarray,
        observed_mask: np.ndarray,
        *,
        min_render_area_px: int,
    ) -> ReprojectionResult:
        """纯数组版本，便于无 GPU 单测；几何量只作为诊断输出。"""

        render = np.asarray(render_mask) > 0
        observed = np.asarray(observed_mask) > 0
        if render.shape != observed.shape:
            return ReprojectionChecker._invalid_result(status="map_shape_invalid")

        try:
            render_rgb = ReprojectionChecker._ensure_rgb_u8(render_color_rgb)
            observed_rgb_u8 = ReprojectionChecker._ensure_rgb_u8(observed_rgb)
        except ValueError:
            return ReprojectionChecker._invalid_result(status="color_shape_invalid")
        if render_rgb.shape[:2] != render.shape or observed_rgb_u8.shape[:2] != render.shape:
            return ReprojectionChecker._invalid_result(status="color_shape_invalid")

        render_area = int(np.count_nonzero(render))
        observed_area = int(np.count_nonzero(observed))
        intersection = render & observed
        intersection_area = int(np.count_nonzero(intersection))
        union_area = int(np.count_nonzero(render | observed))
        mask_iou = float(intersection_area) / float(union_area) if union_area > 0 else 0.0
        render_visible_ratio = float(intersection_area) / float(render_area) if render_area > 0 else 0.0
        observed_visible_ratio = float(intersection_area) / float(observed_area) if observed_area > 0 else 0.0
        area_ratio_score = min(float(observed_area) / float(render_area), 1.0) if render_area > 0 else 0.0
        color_similarity = ReprojectionChecker._color_similarity_lab(render_rgb, observed_rgb_u8, intersection)
        score = clamp01(color_similarity)

        valid = render_area >= int(min_render_area_px) and observed_area > 0
        if valid:
            status = "valid"
        elif render_area < int(min_render_area_px):
            status = "render_area_tiny"
        else:
            status = "observed_empty"

        return ReprojectionResult(
            score=score,
            color_similarity=clamp01(color_similarity),
            area_ratio_score=clamp01(area_ratio_score),
            mask_iou=clamp01(mask_iou),
            render_visible_ratio=clamp01(render_visible_ratio),
            observed_visible_ratio=clamp01(observed_visible_ratio),
            render_area_px=render_area,
            observed_area_px=observed_area,
            valid=bool(valid),
            status=status,
            render_mask=render.copy(),
            observed_mask=observed.copy(),
            render_rgb=render_rgb.copy(),
            observed_rgb=observed_rgb_u8.copy(),
        )

    @staticmethod
    def _color_similarity_lab(render_rgb: np.ndarray, observed_rgb: np.ndarray, intersection: np.ndarray) -> float:
        """在重叠核心区域计算 LAB 颜色相似度，排除 mask 边缘锯齿。"""

        if int(np.count_nonzero(intersection)) <= 0:
            return 0.0
        core_mask = ReprojectionChecker._erode_intersection_core(intersection)
        if int(np.count_nonzero(core_mask)) <= 0:
            core_mask = intersection
        render_lab = cv2.cvtColor(render_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
        observed_lab = cv2.cvtColor(observed_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
        diff = np.linalg.norm(render_lab[core_mask] - observed_lab[core_mask], axis=1)
        if diff.size <= 0:
            return 0.0
        return clamp01(1.0 - float(np.mean(diff)) / 180.0)

    @staticmethod
    def _erode_intersection_core(intersection: np.ndarray) -> np.ndarray:
        """从交集 mask 中取更靠中心的区域，减少边界像素对颜色分的影响。"""

        mask = (np.asarray(intersection) > 0).astype(np.uint8)
        ys, xs = np.nonzero(mask)
        if xs.size < 9 or ys.size < 9:
            return mask > 0
        width = int(xs.max() - xs.min() + 1)
        height = int(ys.max() - ys.min() + 1)
        kernel_size = max(1, int(round(min(width, height) * 0.15)))
        if kernel_size % 2 == 0:
            kernel_size += 1
        if kernel_size <= 1:
            return mask > 0
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
        return cv2.erode(mask, kernel) > 0

    @staticmethod
    def _ensure_rgb_u8(image: np.ndarray) -> np.ndarray:
        """把 renderer/相机图像规范化为 RGB uint8 三通道。"""

        arr = np.asarray(image)
        if arr.ndim == 4:
            arr = arr[0]
        if arr.ndim == 2:
            arr = np.repeat(arr[..., None], 3, axis=2)
        if arr.ndim != 3:
            raise ValueError("重投影颜色图维度不正确，应为 (H,W,C)。")
        arr = arr[..., :3]
        if arr.size <= 0:
            raise ValueError("重投影颜色图为空。")
        if np.issubdtype(arr.dtype, np.floating):
            finite = arr[np.isfinite(arr)]
            if finite.size <= 0:
                raise ValueError("重投影颜色图没有有限像素。")
            if float(np.max(finite)) <= 1.0:
                arr = arr * 255.0
        return np.clip(arr, 0, 255).astype(np.uint8)

    @staticmethod
    def _invalid_result(status: str = "invalid") -> ReprojectionResult:
        """构造无效重投影信号。"""

        return ReprojectionResult(
            score=0.0,
            color_similarity=0.0,
            area_ratio_score=0.0,
            mask_iou=0.0,
            render_visible_ratio=0.0,
            observed_visible_ratio=0.0,
            render_area_px=0,
            observed_area_px=0,
            valid=False,
            status=str(status),
        )


__all__ = ["ReprojectionChecker", "ReprojectionResult"]

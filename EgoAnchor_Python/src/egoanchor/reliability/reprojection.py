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
    """重叠核心区域的 LAB ZNCC 映射分，0.5 表示纯色或零方差信号。"""

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
    """本帧重投影几何信号是否可用（渲染面积足够且有观测前景）。"""

    color_valid: bool = True
    """颜色 ZNCC 是否有可用方差；纯色/无纹理交集为 False，调用方应把颜色项排除而非惩罚。"""

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


@dataclass(frozen=True, slots=True)
class ReprojectionDiffMaps:
    """重投影颜色 ZNCC 的可视化中间结果。"""

    aligned_render_rgb: np.ndarray
    """按观测 LAB 均值/方差重映射后的渲染 RGB，用于直观看零均值对齐结果。"""

    residual_heatmap_bgr: np.ndarray
    """LAB z-score 残差热力图，BGR 格式。"""

    core_mask: np.ndarray
    """参与 ZNCC 计算的交集核心 mask。"""

    score: float
    """与 _color_similarity_lab 相同的 ZNCC 映射分，范围 0..1。"""


class ReprojectionChecker:
    """只评估渲染 RGB 与观测 RGB 在可见交集内的颜色相似度。"""

    def __init__(
        self,
        min_render_area_px: int = 50,
        color_l_weight: float = 0.3,
    ) -> None:
        """保存最小渲染面积与颜色度量参数。"""

        self.min_render_area_px = max(1, int(min_render_area_px))
        """渲染前景过小时判为无效信号的像素阈值。"""

        self.color_l_weight = clamp01(float(color_l_weight))
        """LAB ZNCC 中亮度通道 L 的相对权重。"""

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
            color_l_weight=self.color_l_weight,
        )

    @staticmethod
    def _score_from_maps(
        render_color_rgb: np.ndarray,
        observed_rgb: np.ndarray,
        render_mask: np.ndarray,
        observed_mask: np.ndarray,
        *,
        min_render_area_px: int,
        color_l_weight: float = 0.3,
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

        valid = render_area >= int(min_render_area_px) and observed_area > 0
        if valid:
            status = "valid"
        elif render_area < int(min_render_area_px):
            status = "render_area_tiny"
        else:
            status = "observed_empty"

        # 几何无效时颜色重投影分会被上层丢弃，跳过 LAB 转换与 ZNCC，省掉热路径上的无用计算。
        if valid:
            color_similarity, color_valid = ReprojectionChecker._color_similarity_lab(
                render_rgb,
                observed_rgb_u8,
                intersection,
                l_weight=color_l_weight,
            )
        else:
            color_similarity, color_valid = 0.0, False
        score = clamp01(color_similarity)

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
            color_valid=bool(color_valid),
            status=status,
            render_mask=render.copy(),
            observed_mask=observed.copy(),
            render_rgb=render_rgb.copy(),
            observed_rgb=observed_rgb_u8.copy(),
        )

    @staticmethod
    def _color_similarity_lab(
        render_rgb: np.ndarray,
        observed_rgb: np.ndarray,
        intersection: np.ndarray,
        *,
        l_weight: float = 0.3,
    ) -> tuple[float, bool]:
        """在重叠核心区域计算 LAB 三通道零均值归一化相关分。

        返回 (score, color_valid)。color_valid 为 False 表示核心区域无颜色方差
        （纯色/无纹理物体），此时 score 为中性 0.5，调用方应把颜色项排除而非据此降分。
        空交集是另一回事：pose 投影到错误位置，返回 (0.0, True) 保留惩罚，是坏-pose 信号。
        """

        if int(np.count_nonzero(intersection)) <= 0:
            return 0.0, True
        render_lab = cv2.cvtColor(render_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
        observed_lab = cv2.cvtColor(observed_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
        core_mask = ReprojectionChecker._core_mask(intersection)
        return ReprojectionChecker._lab_zncc_score(render_lab[core_mask], observed_lab[core_mask], l_weight=l_weight)

    @staticmethod
    def color_diff_maps(
        render_rgb: np.ndarray,
        observed_rgb: np.ndarray,
        render_mask: np.ndarray,
        observed_mask: np.ndarray,
        *,
        l_weight: float = 0.3,
    ) -> ReprojectionDiffMaps:
        """生成与 ZNCC 评分同源的对齐投影和 LAB 残差热力图。"""

        render_rgb_u8 = ReprojectionChecker._ensure_rgb_u8(render_rgb)
        observed_rgb_u8 = ReprojectionChecker._ensure_rgb_u8(observed_rgb)
        render = np.asarray(render_mask) > 0
        observed = np.asarray(observed_mask) > 0
        intersection = render & observed
        if render_rgb_u8.shape[:2] != intersection.shape or observed_rgb_u8.shape[:2] != intersection.shape:
            raise ValueError("重投影 debug 图像和 mask 尺寸不一致。")

        render_lab = cv2.cvtColor(render_rgb_u8, cv2.COLOR_RGB2LAB).astype(np.float32)
        observed_lab = cv2.cvtColor(observed_rgb_u8, cv2.COLOR_RGB2LAB).astype(np.float32)
        core_mask = ReprojectionChecker._core_mask(intersection)
        score, _color_valid = ReprojectionChecker._lab_zncc_score(render_lab[core_mask], observed_lab[core_mask], l_weight=l_weight)
        aligned_lab, residual = ReprojectionChecker._lab_diff_visual_maps(render_lab, observed_lab, core_mask, l_weight=l_weight)
        aligned_rgb = cv2.cvtColor(np.clip(aligned_lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB)
        heatmap_input = np.clip(residual * 42.0, 0, 255).astype(np.uint8)
        heatmap = cv2.applyColorMap(heatmap_input, cv2.COLORMAP_JET)
        heatmap[~core_mask] = (0, 0, 0)
        return ReprojectionDiffMaps(
            aligned_render_rgb=aligned_rgb,
            residual_heatmap_bgr=heatmap,
            core_mask=core_mask,
            score=score,
        )

    @staticmethod
    def _lab_zncc_score(render_core_lab: np.ndarray, observed_core_lab: np.ndarray, *, l_weight: float) -> tuple[float, bool]:
        """对 LAB 核心像素做加权 ZNCC，并把 [-1,1] 映射到 [0,1]。

        返回 (score, color_valid)。当任一侧核心区域颜色方差为零（纯色/无纹理）时，
        ZNCC 无定义，返回 (0.5, False)，由调用方决定排除颜色项而非据此降分。
        """

        if render_core_lab.size <= 0 or observed_core_lab.size <= 0:
            return 0.0, True
        weights = np.array([clamp01(l_weight), 1.0, 1.0], dtype=np.float32)
        render_centered = (np.asarray(render_core_lab, dtype=np.float32) - np.mean(render_core_lab, axis=0)) * weights
        observed_centered = (np.asarray(observed_core_lab, dtype=np.float32) - np.mean(observed_core_lab, axis=0)) * weights
        numerator = float(np.sum(render_centered * observed_centered))
        render_energy = float(np.sum(render_centered * render_centered))
        observed_energy = float(np.sum(observed_centered * observed_centered))
        denominator = float(np.sqrt(render_energy * observed_energy))
        if denominator <= 1e-6:
            return 0.5, False
        zncc = numerator / denominator
        return clamp01((zncc + 1.0) * 0.5), True

    @staticmethod
    def _lab_diff_visual_maps(
        render_lab: np.ndarray,
        observed_lab: np.ndarray,
        core_mask: np.ndarray,
        *,
        l_weight: float,
    ) -> tuple[np.ndarray, np.ndarray]:
        """按核心区域统计量生成对齐后的渲染 LAB 和逐像素 z-score 残差。"""

        render_core = render_lab[core_mask]
        observed_core = observed_lab[core_mask]
        if render_core.size <= 0 or observed_core.size <= 0:
            return render_lab.copy(), np.zeros(render_lab.shape[:2], dtype=np.float32)

        render_mean = np.mean(render_core, axis=0)
        observed_mean = np.mean(observed_core, axis=0)
        render_std = np.std(render_core, axis=0)
        observed_std = np.std(observed_core, axis=0)
        safe_render_std = np.where(render_std > 1e-6, render_std, 1.0).astype(np.float32)
        safe_observed_std = np.where(observed_std > 1e-6, observed_std, 1.0).astype(np.float32)
        render_z = (render_lab - render_mean) / safe_render_std
        observed_z = (observed_lab - observed_mean) / safe_observed_std
        aligned_lab = render_z * observed_std + observed_mean
        weights = np.array([clamp01(l_weight), 1.0, 1.0], dtype=np.float32)
        residual = np.linalg.norm((render_z - observed_z) * weights, axis=2)
        residual[~core_mask] = 0.0
        return aligned_lab, residual

    @staticmethod
    def _core_mask(intersection: np.ndarray) -> np.ndarray:
        """取得用于 ZNCC 的交集核心区域，核心为空时退回完整交集。"""

        core_mask = ReprojectionChecker._erode_intersection_core(intersection)
        if int(np.count_nonzero(core_mask)) <= 0:
            return np.asarray(intersection) > 0
        return core_mask

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
            # 约定：浮点 color 要么在 [0,1]，要么已是 [0,255]；不支持其它中间范围。
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
            color_valid=False,
            status=str(status),
        )


__all__ = ["ReprojectionChecker", "ReprojectionDiffMaps", "ReprojectionResult"]

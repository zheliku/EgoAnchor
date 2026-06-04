"""渲染-重投影一致性检测。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

LOGGER = logging.getLogger(__name__)
"""渲染一致性模块日志记录器。"""


@dataclass(frozen=True, slots=True)
class RenderConsistencyResult:
    """单帧渲染-观测一致性结果。"""

    consistency: float
    """综合一致性分，范围 0..1。"""

    mask_iou: float
    """渲染 mask 与观测 mask 的 IoU。"""

    depth_inlier_ratio: float
    """交集区域内深度残差小于阈值的比例。"""

    depth_median_residual_m: float
    """交集有效深度残差中位数，单位米。"""

    render_area_px: int
    """渲染前景像素数量。"""

    valid: bool
    """本帧一致性信号是否足够可靠；false 时 caller 只能当作无信号。"""


class RenderConsistencyChecker:
    """渲染-重投影一致性检测器。

    FoundationPose scorer 是相对排序器，不能直接当作跨帧绝对置信度。本检测器改用
    当前 pose 渲染出的 mesh mask/depth 与真实观测 mask/depth 做几何一致性比较，
    产出可驱动 reliability score 的绝对信号。
    """

    def __init__(
        self,
        iou_weight: float = 0.6,
        depth_weight: float = 0.4,
        depth_inlier_thresh_m: float = 0.02,
        min_render_area_px: int = 50,
        downscale: int = 2,
    ) -> None:
        """保存一致性评分参数。"""

        self.iou_weight = float(iou_weight)
        """综合分中 mask IoU 权重。"""

        self.depth_weight = float(depth_weight)
        """综合分中深度 inlier 权重。"""

        self.depth_inlier_thresh_m = float(depth_inlier_thresh_m)
        """深度残差 inlier 阈值，单位米。"""

        self.min_render_area_px = max(1, int(min_render_area_px))
        """渲染前景太小时判为无效信号的像素阈值。"""

        self.downscale = max(1, int(downscale))
        """一致性检测下采样倍数。"""

    def evaluate(
        self,
        estimator: Any,
        pose_cv_camera: np.ndarray,
        observed_mask: np.ndarray,
        observed_depth_m: np.ndarray,
    ) -> RenderConsistencyResult:
        """渲染当前 pose 并与观测 mask/depth 比较。

        参数中的 estimator 必须公开 `render_depth_mask(...)` facade；本模块不访问
        FoundationPose 第三方对象内部字段，避免 reliability 层和模型实现耦合。
        """

        obs_depth = np.asarray(observed_depth_m, dtype=np.float32)
        obs_mask = np.asarray(observed_mask) > 0
        if obs_depth.ndim != 2 or obs_mask.ndim != 2 or obs_depth.shape != obs_mask.shape:
            return self._invalid_result()

        height, width = obs_depth.shape
        out_h = max(1, height // self.downscale)
        out_w = max(1, width // self.downscale)
        cam_k = self._scaled_camera_matrix(getattr(estimator, "cam_k", None), self.downscale)

        try:
            render_depth, render_mask = estimator.render_depth_mask(
                pose_cv_camera,
                output_size=(out_h, out_w),
                cam_k=cam_k,
            )
        except Exception as exc:
            LOGGER.warning("渲染一致性检测失败，将本帧视为无信号: %s", exc)
            return self._invalid_result()

        obs_mask_small = self._resize_mask(obs_mask, (out_h, out_w))
        obs_depth_small = self._resize_depth(obs_depth, (out_h, out_w))
        return self._score_from_maps(
            np.asarray(render_mask) > 0,
            obs_mask_small,
            np.asarray(render_depth, dtype=np.float32),
            obs_depth_small,
            iou_weight=self.iou_weight,
            depth_weight=self.depth_weight,
            depth_inlier_thresh_m=self.depth_inlier_thresh_m,
            min_render_area_px=self.min_render_area_px,
        )

    @staticmethod
    def _score_from_maps(
        render_mask: np.ndarray,
        observed_mask: np.ndarray,
        render_depth_m: np.ndarray,
        observed_depth_m: np.ndarray,
        *,
        iou_weight: float,
        depth_weight: float,
        depth_inlier_thresh_m: float,
        min_render_area_px: int,
    ) -> RenderConsistencyResult:
        """只根据同尺寸 mask/depth 数组计算一致性分，便于无 GPU 单测。"""

        render = np.asarray(render_mask) > 0
        observed = np.asarray(observed_mask) > 0
        render_depth = np.asarray(render_depth_m, dtype=np.float32)
        observed_depth = np.asarray(observed_depth_m, dtype=np.float32)
        if render.shape != observed.shape or render_depth.shape != render.shape or observed_depth.shape != render.shape:
            return RenderConsistencyChecker._invalid_result()

        render_area = int(np.count_nonzero(render))
        observed_area = int(np.count_nonzero(observed))
        union = render | observed
        union_area = int(np.count_nonzero(union))
        intersection = render & observed
        intersection_area = int(np.count_nonzero(intersection))
        mask_iou = float(intersection_area) / float(union_area) if union_area > 0 else 0.0

        valid_depth = intersection & np.isfinite(render_depth) & np.isfinite(observed_depth) & (render_depth > 0.0) & (observed_depth > 0.0)
        residual = np.abs(render_depth[valid_depth] - observed_depth[valid_depth])
        if residual.size > 0:
            depth_inlier = float(np.mean(residual < float(depth_inlier_thresh_m)))
            depth_median = float(np.median(residual))
        else:
            depth_inlier = 0.0
            depth_median = 0.0

        weight_sum = max(float(iou_weight) + float(depth_weight), 1e-6)
        consistency = RenderConsistencyChecker._clamp01((float(iou_weight) * mask_iou + float(depth_weight) * depth_inlier) / weight_sum)
        valid = render_area >= int(min_render_area_px) and observed_area > 0
        return RenderConsistencyResult(
            consistency=consistency,
            mask_iou=RenderConsistencyChecker._clamp01(mask_iou),
            depth_inlier_ratio=RenderConsistencyChecker._clamp01(depth_inlier),
            depth_median_residual_m=max(0.0, depth_median),
            render_area_px=render_area,
            valid=bool(valid),
        )

    @staticmethod
    def _scaled_camera_matrix(cam_k: Any, downscale: int) -> np.ndarray | None:
        """按下采样倍数缩放 K；缺失 K 时交由 estimator facade 使用默认 K。"""

        if cam_k is None:
            return None
        scaled = np.asarray(cam_k, dtype=np.float64).reshape(3, 3).copy()
        scale = float(max(1, int(downscale)))
        scaled[0, 0] /= scale
        scaled[1, 1] /= scale
        scaled[0, 2] /= scale
        scaled[1, 2] /= scale
        return scaled

    @staticmethod
    def _resize_mask(mask: np.ndarray, output_size: tuple[int, int]) -> np.ndarray:
        """用最近邻缩放二值 mask，避免插值制造半透明边界。"""

        out_h, out_w = output_size
        return cv2.resize((np.asarray(mask) > 0).astype(np.uint8), (out_w, out_h), interpolation=cv2.INTER_NEAREST) > 0

    @staticmethod
    def _resize_depth(depth: np.ndarray, output_size: tuple[int, int]) -> np.ndarray:
        """用最近邻缩放深度，保持与 mask 的像素语义一致。"""

        out_h, out_w = output_size
        return cv2.resize(np.asarray(depth, dtype=np.float32), (out_w, out_h), interpolation=cv2.INTER_NEAREST)

    @staticmethod
    def _invalid_result() -> RenderConsistencyResult:
        """构造无效一致性信号。"""

        return RenderConsistencyResult(
            consistency=0.0,
            mask_iou=0.0,
            depth_inlier_ratio=0.0,
            depth_median_residual_m=0.0,
            render_area_px=0,
            valid=False,
        )

    @staticmethod
    def _clamp01(value: float) -> float:
        """限制数值到 0..1。"""

        return float(max(0.0, min(1.0, value)))


__all__ = ["RenderConsistencyChecker", "RenderConsistencyResult"]

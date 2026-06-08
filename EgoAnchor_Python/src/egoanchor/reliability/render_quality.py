"""一次渲染后拆分重投影与深度质量信号。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from egoanchor.utils import clamp01, get_logger

from .depth_alignment import DepthAlignmentChecker
from .reprojection import ReprojectionChecker

LOGGER = get_logger(__name__, component="RenderQuality")
"""渲染质量模块日志记录器。"""


@dataclass(frozen=True, slots=True)
class RenderQualityResult:
    """单帧渲染质量结果，拆分为重投影分和深度对齐分。"""

    reprojection_score: float
    """重投影颜色分，范围 0..1；协议字段写入 score_reprojection/track_reprojection。"""

    mask_iou: float
    """渲染 mask 与观测 mask 的 IoU。"""

    color_similarity: float
    """重叠核心区域的 LAB 颜色相似度。"""

    area_ratio_score: float
    """观测 Cutie mask 面积 / 渲染投影面积的比例分，低值表示遮挡或投影面积过大。"""

    depth_inlier_ratio: float
    """交集区域内深度残差小于自适应阈值的比例。"""

    depth_alignment_score: float
    """渲染深度与观测深度对齐连续分，范围 0..1。"""

    depth_median_residual_m: float
    """交集区域深度残差中位数，单位米。"""

    render_visible_ratio: float
    """渲染前景中被观测 mask 覆盖的比例。"""

    observed_visible_ratio: float
    """观测 mask 中被渲染前景解释的比例。"""

    render_area_px: int
    """渲染前景像素数量。"""

    reprojection_valid: bool
    """颜色重投影信号是否有效；无效时 caller 不应触发重注册。"""

    status: str = "invalid"
    """综合状态；valid、render_exception、render_area_tiny 等。"""

    render_mask: np.ndarray | None = None
    """用于 debug 的下采样渲染 mask。"""

    observed_mask: np.ndarray | None = None
    """用于 debug 的下采样观测 mask。"""

    render_depth_m: np.ndarray | None = None
    """用于 debug 的下采样渲染 depth。"""

    observed_depth_m: np.ndarray | None = None
    """用于 debug 的下采样观测 depth。"""

    render_rgb: np.ndarray | None = None
    """用于 debug 的下采样渲染 RGB。"""

    observed_rgb: np.ndarray | None = None
    """用于 debug 的下采样观测 RGB。"""


class RenderQualityChecker:
    """协调单次 mesh 渲染，并分发给重投影与深度对齐 checker。"""

    def __init__(
        self,
        depth_distance_ratio: float = 0.02,
        depth_min_inlier_thresh_m: float = 0.005,
        depth_min_coverage: float = 0.10,
        min_render_area_px: int = 50,
        downscale: int = 2,
    ) -> None:
        """保存渲染质量参数并构造两个专责 checker。"""

        self.reprojection = ReprojectionChecker(
            min_render_area_px=min_render_area_px,
        )
        """重投影 checker，只管可见交集内的颜色相似度。"""

        self.depth_alignment = DepthAlignmentChecker(
            distance_ratio=depth_distance_ratio,
            min_inlier_thresh_m=depth_min_inlier_thresh_m,
            min_depth_coverage=depth_min_coverage,
        )
        """深度 checker，只管渲染深度和观测深度残差。"""

        self.min_render_area_px = max(1, int(min_render_area_px))
        """渲染前景过小时判为无效信号的像素阈值。"""

        self.downscale = max(1, int(downscale))
        """渲染质量检测下采样倍数。"""

    def evaluate(
        self,
        estimator: Any,
        pose_cv_camera: np.ndarray,
        observed_rgb: np.ndarray,
        observed_mask: np.ndarray,
        observed_depth_m: np.ndarray,
        *,
        depth_coverage: float,
    ) -> RenderQualityResult:
        """渲染当前 pose，并分别计算重投影与深度对齐质量。"""

        obs_rgb = np.asarray(observed_rgb)
        obs_depth = np.asarray(observed_depth_m, dtype=np.float32)
        obs_mask = np.asarray(observed_mask) > 0
        if obs_rgb.ndim != 3 or obs_depth.ndim != 2 or obs_mask.ndim != 2 or obs_depth.shape != obs_mask.shape:
            return self._invalid_result(status="input_shape_invalid")
        if obs_rgb.shape[:2] != obs_mask.shape:
            return self._invalid_result(status="input_shape_invalid")

        height, width = obs_depth.shape
        out_h = max(1, height // self.downscale)
        out_w = max(1, width // self.downscale)
        cam_k = self._scaled_camera_matrix(getattr(estimator, "cam_k", None), self.downscale)

        try:
            render_color, render_depth, render_mask = estimator.render_color_depth_mask(
                pose_cv_camera,
                output_size=(out_h, out_w),
                cam_k=cam_k,
            )
        except Exception as exc:
            LOGGER.warning("渲染质量检测失败，将本帧视为无信号: %s", exc)
            return self._invalid_result(status="render_exception")

        obs_rgb_small = self._resize_rgb(obs_rgb, (out_h, out_w))
        obs_mask_small = self._resize_mask(obs_mask, (out_h, out_w))
        obs_depth_small = self._resize_depth(obs_depth, (out_h, out_w))
        render_mask_bool = np.asarray(render_mask) > 0
        render_depth_small = np.asarray(render_depth, dtype=np.float32)
        if render_mask_bool.shape != obs_mask_small.shape or render_depth_small.shape != obs_depth_small.shape:
            return self._invalid_result(status="render_shape_invalid")
        reprojection = self.reprojection.score_maps(
            np.asarray(render_color),
            obs_rgb_small,
            render_mask_bool,
            obs_mask_small,
        )
        intersection = render_mask_bool & obs_mask_small
        pose_distance = self._pose_distance_m(pose_cv_camera)
        depth = self.depth_alignment.score_maps(
            render_depth_small,
            obs_depth_small,
            intersection,
            pose_distance_m=pose_distance,
            depth_coverage=depth_coverage,
        )
        status = self._merge_status(reprojection.status, depth.status)
        return RenderQualityResult(
            reprojection_score=clamp01(reprojection.score) if reprojection.valid else -1.0,
            mask_iou=clamp01(reprojection.mask_iou),
            color_similarity=clamp01(reprojection.color_similarity),
            area_ratio_score=clamp01(reprojection.area_ratio_score),
            depth_inlier_ratio=clamp01(depth.inlier_ratio),
            depth_alignment_score=clamp01(depth.score),
            depth_median_residual_m=max(0.0, depth.median_residual_m),
            render_visible_ratio=clamp01(reprojection.render_visible_ratio),
            observed_visible_ratio=clamp01(reprojection.observed_visible_ratio),
            render_area_px=int(reprojection.render_area_px),
            reprojection_valid=bool(reprojection.valid),
            status=status,
            render_mask=reprojection.render_mask,
            observed_mask=reprojection.observed_mask,
            render_depth_m=depth.render_depth_m,
            observed_depth_m=depth.observed_depth_m,
            render_rgb=reprojection.render_rgb,
            observed_rgb=reprojection.observed_rgb,
        )

    @staticmethod
    def _pose_distance_m(pose_cv_camera: np.ndarray) -> float:
        """从 OpenCV camera-space pose 取物体到相机的欧氏距离。"""

        pose = np.asarray(pose_cv_camera, dtype=np.float64).reshape(4, 4)
        return float(np.linalg.norm(pose[:3, 3]))

    @staticmethod
    def _merge_status(reprojection_status: str, depth_status: str) -> str:
        """把重投影状态和深度状态合并成单个协议状态文本。"""

        if reprojection_status != "valid":
            return reprojection_status
        if depth_status == "valid":
            return "valid"
        return f"valid_{depth_status}"

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
    def _resize_rgb(image: np.ndarray, output_size: tuple[int, int]) -> np.ndarray:
        """缩放 RGB 图像，供颜色重投影评分使用。"""

        out_h, out_w = output_size
        return cv2.resize(np.asarray(image)[..., :3], (out_w, out_h), interpolation=cv2.INTER_AREA)

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
    def _invalid_result(status: str = "invalid") -> RenderQualityResult:
        """构造无效渲染质量信号。"""

        return RenderQualityResult(
            reprojection_score=-1.0,
            mask_iou=0.0,
            color_similarity=0.0,
            area_ratio_score=0.0,
            depth_inlier_ratio=0.0,
            depth_alignment_score=0.0,
            depth_median_residual_m=0.0,
            render_visible_ratio=0.0,
            observed_visible_ratio=0.0,
            render_area_px=0,
            reprojection_valid=False,
            status=str(status),
        )


__all__ = ["RenderQualityChecker", "RenderQualityResult"]

"""渲染深度与观测深度对齐评分。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from egoanchor.utils import clamp01


@dataclass(frozen=True, slots=True)
class DepthAlignmentResult:
    """单帧渲染深度与观测深度的对齐结果。"""

    score: float
    """深度对齐分，范围 0..1；覆盖不足时为中性 0.5。"""

    inlier_ratio: float
    """交集区域内深度残差小于自适应阈值的比例。"""

    median_residual_m: float
    """有效交集区域深度残差中位数，单位米。"""

    inlier_thresh_m: float
    """本帧根据物体距离自适应得到的 inlier 阈值，单位米。"""

    depth_coverage: float
    """观测 mask 内有效深度覆盖率。"""

    valid: bool
    """本帧深度对齐是否来自足够覆盖率的有效深度信号。"""

    status: str = "invalid"
    """深度信号状态，例如 valid、depth_coverage_insufficient、no_valid_depth_overlap。"""

    render_depth_m: np.ndarray | None = None
    """用于 debug 的渲染 depth。"""

    observed_depth_m: np.ndarray | None = None
    """用于 debug 的观测 depth。"""


class DepthAlignmentChecker:
    """只评估渲染表面深度与 FFS 观测深度的残差。"""

    def __init__(
        self,
        distance_ratio: float = 0.02,
        min_inlier_thresh_m: float = 0.005,
        min_depth_coverage: float = 0.10,
    ) -> None:
        """保存深度对齐阈值策略。"""

        self.distance_ratio = max(0.0, float(distance_ratio))
        """深度 inlier 阈值随物体距离放大的比例。"""

        self.min_inlier_thresh_m = max(1e-6, float(min_inlier_thresh_m))
        """深度 inlier 阈值下限，单位米。"""

        self.min_depth_coverage = clamp01(float(min_depth_coverage))
        """进入深度对齐评分前要求的 mask 内有效深度覆盖率。"""

    def score_maps(
        self,
        render_depth_m: np.ndarray,
        observed_depth_m: np.ndarray,
        intersection_mask: np.ndarray,
        *,
        pose_distance_m: float,
        depth_coverage: float,
    ) -> DepthAlignmentResult:
        """根据同尺寸 depth 和交集 mask 计算深度对齐分。"""

        return self._score_from_maps(
            render_depth_m,
            observed_depth_m,
            intersection_mask,
            pose_distance_m=pose_distance_m,
            depth_coverage=depth_coverage,
            distance_ratio=self.distance_ratio,
            min_inlier_thresh_m=self.min_inlier_thresh_m,
            min_depth_coverage=self.min_depth_coverage,
        )

    @staticmethod
    def _score_from_maps(
        render_depth_m: np.ndarray,
        observed_depth_m: np.ndarray,
        intersection_mask: np.ndarray,
        *,
        pose_distance_m: float,
        depth_coverage: float,
        distance_ratio: float,
        min_inlier_thresh_m: float,
        min_depth_coverage: float,
    ) -> DepthAlignmentResult:
        """纯数组版本，便于无 GPU 单测。"""

        coverage = clamp01(float(depth_coverage))
        thresh = max(float(min_inlier_thresh_m), max(0.0, float(pose_distance_m)) * max(0.0, float(distance_ratio)))
        render_depth = np.asarray(render_depth_m, dtype=np.float32)
        observed_depth = np.asarray(observed_depth_m, dtype=np.float32)
        intersection = np.asarray(intersection_mask) > 0
        if render_depth.shape != observed_depth.shape or render_depth.shape != intersection.shape:
            return DepthAlignmentChecker._invalid_result(
                status="map_shape_invalid",
                score=0.5,
                depth_coverage=coverage,
                inlier_thresh_m=thresh,
            )
        if coverage < float(min_depth_coverage):
            return DepthAlignmentChecker._invalid_result(
                status="depth_coverage_insufficient",
                score=0.5,
                depth_coverage=coverage,
                inlier_thresh_m=thresh,
                render_depth_m=render_depth,
                observed_depth_m=observed_depth,
            )

        valid_depth = (
            intersection
            & np.isfinite(render_depth)
            & np.isfinite(observed_depth)
            & (render_depth > 0.0)
            & (observed_depth > 0.0)
        )
        residual = np.abs(render_depth[valid_depth] - observed_depth[valid_depth])
        if residual.size <= 0:
            return DepthAlignmentChecker._invalid_result(
                status="no_valid_depth_overlap",
                score=0.0,
                depth_coverage=coverage,
                inlier_thresh_m=thresh,
                render_depth_m=render_depth,
                observed_depth_m=observed_depth,
            )

        inlier_ratio = float(np.mean(residual < thresh))
        median_residual = float(np.median(residual))
        # 残差达 inlier 阈值 3 倍时 median_score 归零。
        median_score = clamp01(1.0 - median_residual / (thresh * 3.0))
        score = clamp01(0.5 * inlier_ratio + 0.5 * median_score)
        return DepthAlignmentResult(
            score=score,
            inlier_ratio=clamp01(inlier_ratio),
            median_residual_m=max(0.0, median_residual),
            inlier_thresh_m=thresh,
            depth_coverage=coverage,
            valid=True,
            status="valid",
            render_depth_m=render_depth.copy(),
            observed_depth_m=observed_depth.copy(),
        )

    @staticmethod
    def _invalid_result(
        *,
        status: str,
        score: float,
        depth_coverage: float,
        inlier_thresh_m: float,
        render_depth_m: np.ndarray | None = None,
        observed_depth_m: np.ndarray | None = None,
    ) -> DepthAlignmentResult:
        """构造无效或中性深度对齐结果。"""

        return DepthAlignmentResult(
            score=clamp01(score),
            inlier_ratio=0.0,
            median_residual_m=0.0,
            inlier_thresh_m=max(0.0, float(inlier_thresh_m)),
            depth_coverage=clamp01(float(depth_coverage)),
            valid=False,
            status=str(status),
            render_depth_m=None if render_depth_m is None else np.asarray(render_depth_m, dtype=np.float32).copy(),
            observed_depth_m=None if observed_depth_m is None else np.asarray(observed_depth_m, dtype=np.float32).copy(),
        )


__all__ = ["DepthAlignmentChecker", "DepthAlignmentResult"]

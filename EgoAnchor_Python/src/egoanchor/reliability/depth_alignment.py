"""渲染深度与观测深度对齐评分。

实现绝对-结构联合深度一致性评估：
- D_abs：绝对深度残差评估（逐像素残差统计）
- D_struct：相对深度结构一致性（归一化深度ZNCC）
- D = (1-α)·D_abs + α·D_struct，α根据场景复杂度自适应启用
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
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

    absolute_score: float = 0.0
    """绝对深度残差分数 D_abs，范围 0..1。"""

    structural_score: float = 0.0
    """深度结构一致性分数（归一化深度ZNCC），范围 0..1。"""

    structural_weight: float = 0.0
    """结构分数在最终评分中的权重 α。"""

    valid: bool = False
    """本帧深度对齐是否来自足够覆盖率的有效深度信号。"""

    status: str = "invalid"
    """深度信号状态，例如 valid、depth_coverage_insufficient、no_valid_depth_overlap。"""

    render_depth_m: np.ndarray | None = None
    """用于 debug 的渲染 depth。"""

    observed_depth_m: np.ndarray | None = None
    """用于 debug 的观测 depth。"""


class DepthAlignmentChecker:
    """绝对-结构联合深度对齐评估。"""

    def __init__(
        self,
        distance_ratio: float = 0.02,
        min_inlier_thresh_m: float = 0.005,
        min_depth_coverage: float = 0.10,
        residual_scale: float = 2.5,
        enable_structural: bool = True,
        structural_max_weight: float = 0.35,
        structural_iqr_thresh: float = 0.02,
        core_erode_kernel: int = 3,
    ) -> None:
        """保存深度对齐评估策略。

        Args:
            distance_ratio: 深度 inlier 阈值随物体距离放大的比例
            min_inlier_thresh_m: 深度 inlier 阈值下限，单位米
            min_depth_coverage: 进入深度对齐评分前要求的 mask 内有效深度覆盖率
            residual_scale: 归一化残差中位数的容忍倍数（越大越宽容）
            enable_structural: 是否启用深度结构一致性评估
            structural_max_weight: 结构分数的最大权重 α_max
            structural_iqr_thresh: 启用结构评估的深度IQR阈值，单位米
            core_erode_kernel: 核心区域腐蚀核大小，用于排除边缘噪声
        """

        self.distance_ratio = max(0.0, float(distance_ratio))
        self.min_inlier_thresh_m = max(1e-6, float(min_inlier_thresh_m))
        self.min_depth_coverage = clamp01(float(min_depth_coverage))
        self.residual_scale = max(1.0, float(residual_scale))
        self.enable_structural = bool(enable_structural)
        self.structural_max_weight = clamp01(float(structural_max_weight))
        self.structural_iqr_thresh = max(0.0, float(structural_iqr_thresh))
        self.core_erode_kernel = max(0, int(core_erode_kernel))

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
            residual_scale=self.residual_scale,
            enable_structural=self.enable_structural,
            structural_max_weight=self.structural_max_weight,
            structural_iqr_thresh=self.structural_iqr_thresh,
            core_erode_kernel=self.core_erode_kernel,
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
        residual_scale: float,
        enable_structural: bool,
        structural_max_weight: float,
        structural_iqr_thresh: float,
        core_erode_kernel: int,
    ) -> DepthAlignmentResult:
        """纯数组版本，便于无 GPU 单测。

        实现绝对-结构联合评估：
        D = (1-α)·D_abs + α·D_struct

        其中：
        D_abs = λ·ρ_inlier + (1-λ)·S_med
            ρ_inlier = (1/|Ω|) Σ 𝟙[e(p) < τ(p)]
            S_med = 1 - median(min(e(p)/(scale·τ(p)), 1))
            τ(p) = max(τ_min, ρ_z·D_rnd(p))
            scale = residual_scale（更宽容的残差容忍度）

        D_struct = (1 + ZNCC(norm(Z_r), norm(Z_o))) / 2
            norm(Z) = (Z - median(Z)) / IQR(Z)  # 归一化深度

        α = α_max · min(IQR(Z_r) / thresh, 1.0)  # 场景复杂度自适应
        """

        coverage = clamp01(float(depth_coverage))
        global_thresh = max(float(min_inlier_thresh_m), max(0.0, float(pose_distance_m)) * max(0.0, float(distance_ratio)))

        render_depth = np.asarray(render_depth_m, dtype=np.float32)
        observed_depth = np.asarray(observed_depth_m, dtype=np.float32)
        intersection = np.asarray(intersection_mask) > 0

        # 验证输入
        if render_depth.shape != observed_depth.shape or render_depth.shape != intersection.shape:
            return DepthAlignmentChecker._invalid_result(
                status="map_shape_invalid",
                score=0.5,
                depth_coverage=coverage,
                inlier_thresh_m=global_thresh,
            )
        if coverage < float(min_depth_coverage):
            return DepthAlignmentChecker._invalid_result(
                status="depth_coverage_insufficient",
                score=0.5,
                depth_coverage=coverage,
                inlier_thresh_m=global_thresh,
                render_depth_m=render_depth,
                observed_depth_m=observed_depth,
            )

        # Step 1: 提取核心区域（排除边缘噪声）
        if core_erode_kernel > 0:
            kernel = np.ones((core_erode_kernel, core_erode_kernel), dtype=np.uint8)
            core_mask = cv2.erode(intersection.astype(np.uint8), kernel, iterations=1) > 0
        else:
            core_mask = intersection

        valid_depth = (
            core_mask
            & np.isfinite(render_depth)
            & np.isfinite(observed_depth)
            & (render_depth > 0.0)
            & (observed_depth > 0.0)
        )

        if valid_depth.sum() <= 0:
            return DepthAlignmentChecker._invalid_result(
                status="no_valid_depth_overlap",
                score=0.0,
                depth_coverage=coverage,
                inlier_thresh_m=global_thresh,
                render_depth_m=render_depth,
                observed_depth_m=observed_depth,
            )

        # 提取核心区域的深度值
        render_valid = render_depth[valid_depth]
        observed_valid = observed_depth[valid_depth]

        # Step 2: 计算绝对深度残差分数 D_abs
        residual = np.abs(render_valid - observed_valid)
        pixel_thresh = np.maximum(float(min_inlier_thresh_m), render_valid * float(distance_ratio))

        # 内点比例
        inlier_mask = residual < pixel_thresh
        inlier_ratio = float(np.mean(inlier_mask))

        # 归一化残差中位数（使用更宽容的scale）
        normalized_residual = residual / (pixel_thresh * float(residual_scale))
        normalized_residual_clamped = np.minimum(normalized_residual, 1.0)
        median_normalized_residual = float(np.median(normalized_residual_clamped))
        S_med = clamp01(1.0 - median_normalized_residual)

        # 绝对分数
        lambda_weight = 0.6
        D_abs = clamp01(lambda_weight * inlier_ratio + (1.0 - lambda_weight) * S_med)

        # Step 3: 计算深度结构一致性分数 D_struct（如果启用）
        D_struct = 0.0
        alpha = 0.0

        if enable_structural:
            # 计算深度场景复杂度（IQR）
            render_q25, render_median, render_q75 = np.percentile(render_valid, [25, 50, 75])
            render_iqr = render_q75 - render_q25

            # 只有当深度起伏足够大时才启用结构评估
            if render_iqr >= float(structural_iqr_thresh) and len(render_valid) >= 50:
                # 归一化深度：减去中位数，除以IQR
                if render_iqr > 1e-6:
                    render_norm = (render_valid - render_median) / render_iqr
                else:
                    render_norm = render_valid - render_median

                obs_q25, obs_median, obs_q75 = np.percentile(observed_valid, [25, 50, 75])
                obs_iqr = obs_q75 - obs_q25
                if obs_iqr > 1e-6:
                    obs_norm = (observed_valid - obs_median) / obs_iqr
                else:
                    obs_norm = observed_valid - obs_median

                # 计算归一化深度的零均值互相关（ZNCC）
                render_zmean = render_norm - np.mean(render_norm)
                obs_zmean = obs_norm - np.mean(obs_norm)

                render_std = np.std(render_zmean)
                obs_std = np.std(obs_zmean)

                if render_std > 1e-6 and obs_std > 1e-6:
                    zncc = float(np.mean(render_zmean * obs_zmean) / (render_std * obs_std))
                    zncc = np.clip(zncc, -1.0, 1.0)
                    D_struct = (1.0 + zncc) / 2.0  # 映射到 [0, 1]

                    # 阈值为零表示只要结构信号有效就直接采用最大权重；显式分支避免配置边界除以零。
                    iqr_threshold = float(structural_iqr_thresh)
                    complexity_scale = 1.0 if iqr_threshold <= 1e-6 else min(render_iqr / iqr_threshold, 1.0)
                    alpha = float(structural_max_weight) * complexity_scale
                    alpha = clamp01(alpha)

        # Step 4: 融合绝对和结构分数
        final_score = clamp01((1.0 - alpha) * D_abs + alpha * D_struct)

        # 诊断信息
        median_residual = float(np.median(residual))

        return DepthAlignmentResult(
            score=final_score,
            inlier_ratio=clamp01(inlier_ratio),
            median_residual_m=max(0.0, median_residual),
            inlier_thresh_m=global_thresh,
            depth_coverage=coverage,
            absolute_score=clamp01(D_abs),
            structural_score=clamp01(D_struct),
            structural_weight=alpha,
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
            absolute_score=0.0,
            structural_score=0.0,
            structural_weight=0.0,
            valid=False,
            status=str(status),
            render_depth_m=None if render_depth_m is None else np.asarray(render_depth_m, dtype=np.float32).copy(),
            observed_depth_m=None if observed_depth_m is None else np.asarray(observed_depth_m, dtype=np.float32).copy(),
        )


__all__ = ["DepthAlignmentChecker", "DepthAlignmentResult"]

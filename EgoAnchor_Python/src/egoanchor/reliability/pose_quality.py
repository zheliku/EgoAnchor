"""PoseObservation VCD 可靠性评分。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from egoanchor.utils import clamp, clamp01

if TYPE_CHECKING:
    from egoanchor.perception import PoseObservation

MIN_DEPTH_COVERAGE = 0.10
"""进入深度对齐评分前要求的 mask 内有效深度覆盖率。"""


@dataclass(frozen=True, slots=True)
class PoseScoreConfig:
    """Pose quality 合成参数，控制 VCD 几何核（C/D）权重。"""

    geo_floor: float = 0.05
    """几何核单维最低值；避免有效低分在几何平均里变成硬零。"""

    reproj_weight: float = 0.2
    """颜色投影分（C）在几何核里的相对权重。"""

    depth_weight: float = 0.8
    """深度对齐分（D）在几何核里的相对权重。"""

    def __post_init__(self) -> None:
        """归一化配置值，避免 TOML 临时调参造成非法对数或负权重。"""

        object.__setattr__(self, "geo_floor", clamp(float(self.geo_floor), 1e-6, 1.0))
        reproj_weight = max(0.0, float(self.reproj_weight))
        depth_weight = max(0.0, float(self.depth_weight))
        if reproj_weight + depth_weight <= 0.0:
            reproj_weight = 0.5
            depth_weight = 0.5
        object.__setattr__(self, "reproj_weight", reproj_weight)
        object.__setattr__(self, "depth_weight", depth_weight)


@dataclass(frozen=True, slots=True)
class PoseQualityBreakdown:
    """VCD 评分分解：V × C^α × D^β。"""

    final_score: float
    """最终可靠性分 R = V × C^α × D^β，范围 0..1。"""

    reprojection_score: float
    """颜色投影子分 C（Color projection）；协议字段写入 score_reprojection。"""

    depth_score: float
    """深度对齐子分 D（Depth alignment）；渲染深度与观测深度在可见区域内的对齐分。"""

    mask_score: float
    """可见面积子分 V（Visibility）。"""

    geometry_core_score: float
    """有效颜色与深度证据构成的几何核 G_CD，范围 0..1。"""

    flags: tuple[str, ...]
    """解释最终分数的 flags。"""


def score_observation_breakdown(
    observation: PoseObservation,
    config: PoseScoreConfig | None = None,
) -> PoseQualityBreakdown:
    """VCD 纯即时评分：R = V × C^α × D^β。

    V = mask 可见面积占比（Visibility），
    C = 颜色投影分（Color projection，α=0.2），
    D = 深度对齐分（Depth alignment，β=0.8）。
    所有历史信号（confidence/phase/reject）已移除，本函数只输出即时几何质量。
    """

    score_config = config or PoseScoreConfig()
    flags: list[str] = []
    if not observation.has_pose:
        if observation.failure_reason:
            flags.append(observation.failure_reason)
        if observation.depth_valid_in_mask <= 0.0:
            flags.append("no_valid_depth_in_mask")
        if observation.mask_area_ratio <= 0.0:
            flags.append("no_mask")
        return PoseQualityBreakdown(
            final_score=0.0,
            reprojection_score=0.0,
            depth_score=0.0,
            mask_score=0.0,
            geometry_core_score=0.0,
            flags=tuple(flags),
        )

    v_score = _mask_factor(observation, flags)
    reprojection_score, reprojection_valid = _reprojection_score(observation, flags)
    depth_score, depth_valid = _depth_score(observation, flags)
    if not (reprojection_valid or depth_valid):
        flags.append("quality_pending")
    # VCD：C^α × D^β 加权几何均值（仅可见区域），V 直接乘因子
    g_score = _geometry_core(
        reprojection_score=reprojection_score,
        reprojection_valid=reprojection_valid,
        depth_score=depth_score,
        depth_valid=depth_valid,
        config=score_config,
    )
    final_score = clamp01(g_score * v_score)
    return PoseQualityBreakdown(
        final_score=final_score,
        reprojection_score=clamp01(reprojection_score),
        depth_score=clamp01(depth_score),
        mask_score=clamp01(v_score),
        geometry_core_score=clamp01(g_score),
        flags=tuple(flags),
    )


def _reprojection_score(observation: PoseObservation, flags: list[str]) -> tuple[float, bool]:
    """颜色投影分 C（Color projection）映射为几何核子分。

    color_reprojection<0 表示本帧没有可用颜色信号（未启用、渲染退化或纯色/无纹理物体）。
    这些情况一律把 C 排除出几何核（返回 valid=False），而不是惩罚：纯色物体的低 C 分
    会冤枉正确 pose，而真正的坏 pose 已由深度对齐（D）和可见面积（V）负责拦截。
    """

    reprojection = float(observation.color_reprojection)
    if reprojection < 0.0:
        flags.append("no_reprojection_signal")
        return 1.0, False
    score = clamp01(reprojection)
    if score < 0.5:
        flags.append("reprojection_low")
    return score, True


def _depth_score(observation: PoseObservation, flags: list[str]) -> tuple[float, bool]:
    """深度对齐分 D（Depth alignment）映射为几何核子分。"""

    depth_coverage = clamp01(float(observation.depth_valid_in_mask))
    if depth_coverage < MIN_DEPTH_COVERAGE:
        flags.append("depth_coverage_insufficient")
        return 0.5, False

    alignment = clamp01(float(observation.render_quality_depth_alignment))
    if _has_render_depth_signal(observation):
        if alignment < 0.5:
            flags.append("depth_alignment_low")
        return alignment, True

    if observation.render_quality_evaluated:
        flags.append("depth_alignment_missing_expected")
    else:
        flags.append("no_depth_alignment_signal")
    return 0.5, False


def _geometry_core(
    *,
    reprojection_score: float,
    reprojection_valid: bool,
    depth_score: float,
    depth_valid: bool,
    config: PoseScoreConfig,
) -> float:
    """对有效几何证据取加权几何平均（C^α × D^β）；两路都无信号时保持当前 pose 信任。"""

    weighted_log_sum = 0.0
    weight_sum = 0.0
    if reprojection_valid and config.reproj_weight > 0.0:
        value = max(clamp01(float(reprojection_score)), config.geo_floor)
        weighted_log_sum += config.reproj_weight * math.log(value)
        weight_sum += config.reproj_weight
    if depth_valid and config.depth_weight > 0.0:
        value = max(clamp01(float(depth_score)), config.geo_floor)
        weighted_log_sum += config.depth_weight * math.log(value)
        weight_sum += config.depth_weight
    if weight_sum <= 0.0:
        return 1.0
    return clamp01(math.exp(weighted_log_sum / weight_sum))


def _has_render_depth_signal(observation: PoseObservation) -> bool:
    """判断本帧是否已经拿到渲染深度对齐结果，包括明确的低分结果。"""

    status = str(observation.render_quality_status or "")
    return status == "valid" or observation.render_quality_depth_inlier > 0.0 or observation.render_quality_depth_residual_m > 0.0


def _mask_factor(observation: PoseObservation, flags: list[str]) -> float:
    """计算 V = |M_obs intersection M_rnd| / |M_rnd|。"""

    if _has_projection_area_signal(observation):
        score = clamp01(float(observation.render_quality_render_visible_ratio))
        if score < 0.35:
            flags.append("mask_visible_area_low")
        elif score < 0.65:
            flags.append("mask_visible_area_mid")
        return score

    ratio = clamp01(float(observation.mask_area_ratio))
    if ratio < 0.002:
        flags.append("mask_too_small")
        return 0.3 + 0.2 * (ratio / 0.002)
    if ratio < 0.01:
        return 0.5 + 0.5 * ((ratio - 0.002) / (0.01 - 0.002))
    if ratio <= 0.4:
        return 1.0
    if ratio <= 0.65:
        flags.append("mask_too_large")
        return 1.0 - 0.45 * ((ratio - 0.4) / (0.65 - 0.4))
    flags.append("mask_too_large")
    return max(0.3, 0.55 - 0.25 * ((ratio - 0.65) / (0.8 - 0.65)))


def _has_projection_area_signal(observation: PoseObservation) -> bool:
    """判断本帧是否有可用于计算可见比例的渲染投影。"""

    status = str(observation.render_quality_status or "")
    return observation.render_quality_render_area_px > 0 and (observation.color_reprojection >= 0.0 or status.startswith("valid"))

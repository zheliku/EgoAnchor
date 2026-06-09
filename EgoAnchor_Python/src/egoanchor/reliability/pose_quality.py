"""PoseObservation 可靠性评分。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from egoanchor.utils import clamp, clamp01

if TYPE_CHECKING:
    from egoanchor.perception import PoseObservation

BASE_SOFT_TRANSLATION_M = 0.03
"""30fps 基准下平移超过该值开始轻微降分，单位米。"""

HARD_TRANSLATION_M = 0.6
"""平移跳变硬上限，单位米；接近该值时 jump_score 逼近 0。"""

BASE_SOFT_ROTATION_DEG = 10.0
"""30fps 基准下旋转超过该值开始轻微降分，单位度。"""

HARD_ROTATION_DEG = 100.0
"""旋转跳变硬上限，单位度；接近该值时 jump_score 逼近 0。"""

EXPECTED_FRAME_DT_S = 1.0 / 30.0
"""jump_score 软阈值缩放的基准帧间隔。"""

MIN_DEPTH_COVERAGE = 0.10
"""进入深度对齐评分前要求的 mask 内有效深度覆盖率。"""

WARMUP_FRAMES = 10
"""连续多少个高质量 pose 后 confidence 才到满值。"""

GOOD_SCORE_THRESH = 0.6
"""Quality 分不低于该阈值时认为本帧有助于积累连续置信。"""


@dataclass(frozen=True, slots=True)
class PoseScoreConfig:
    """Pose quality 合成参数，控制几何合取核和非几何调制幅度。"""

    geo_floor: float = 0.05
    """几何核单维最低值；避免有效低分在几何平均里变成硬零。"""

    reproj_weight: float = 0.5
    """重投影颜色分在几何核里的相对权重。"""

    depth_weight: float = 0.5
    """深度对齐分在几何核里的相对权重。"""

    mask_floor: float = 0.5
    """mask 调制因子的下限；遮挡或可见面积少时只温和降权。"""

    jump_floor: float = 0.6
    """jump 调制因子的下限；快速运动时只温和降权。"""

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
        object.__setattr__(self, "mask_floor", clamp01(float(self.mask_floor)))
        object.__setattr__(self, "jump_floor", clamp01(float(self.jump_floor)))


class ConfidenceAccumulator:
    """连续高质量 pose 的置信积累器。"""

    def __init__(self, warmup_frames: int = WARMUP_FRAMES, good_score_thresh: float = GOOD_SCORE_THRESH) -> None:
        """保存 warmup 参数并初始化计数器。"""

        self.warmup_frames = max(1, int(warmup_frames))
        """累计到满 confidence 需要的连续高质量帧数。"""

        self.good_score_thresh = clamp01(float(good_score_thresh))
        """判定单帧 quality 足够好的阈值。"""

        self.consecutive_good = 0
        """当前连续高质量帧计数。"""

    def update(self, quality_score: float, *, evidence: bool = True) -> float:
        """更新连续帧计数，并返回 0.5..1.0 的 confidence ramp。

        evidence=False 表示本帧没有重投影或深度几何证据，计数原地保持。
        """

        if not evidence:
            ramp = float(self.consecutive_good) / float(self.warmup_frames)
            return clamp01(0.5 + 0.5 * ramp)
        if clamp01(float(quality_score)) >= self.good_score_thresh:
            self.consecutive_good = min(self.consecutive_good + 1, self.warmup_frames)
        else:
            self.consecutive_good = max(0, self.consecutive_good - 2)
        ramp = float(self.consecutive_good) / float(self.warmup_frames)
        return clamp01(0.5 + 0.5 * ramp)

    def reset(self) -> None:
        """清空连续高质量帧计数。"""

        self.consecutive_good = 0


@dataclass(frozen=True, slots=True)
class PoseQualityBreakdown:
    """Pose reliability 评分分解，便于 HUD/日志逐项诊断。"""

    final_score: float
    """最终可靠性分，范围 0..1。"""

    phase_score: float
    """Gate 层 phase 子分。"""

    reprojection_score: float
    """Quality 层颜色重投影子分；协议字段写入 score_reprojection。"""

    depth_score: float
    """Quality 层渲染深度与观测深度对齐子分。"""

    jump_score: float
    """Quality 层相邻 pose 跳变子分。"""

    mask_score: float
    """Quality 层 mask 可见面积子分。"""

    reject_score: float
    """Gate 层近期 track reject 子分。"""

    confidence_score: float
    """连续高质量 pose warmup 置信分。"""

    gate_score: float
    """Gate 层总分，用于诊断 phase/reject 是否压低上限。"""

    quality_score: float
    """Quality 层总分，由几何合取核和 mask/jump 有界调制相乘得到。"""

    flags: tuple[str, ...]
    """解释最终分数的 flags。"""


def score_observation_breakdown(
    observation: PoseObservation,
    confidence_accumulator: ConfidenceAccumulator | None = None,
    config: PoseScoreConfig | None = None,
) -> PoseQualityBreakdown:
    """按 Gate × Quality × Confidence 生成完整评分分解。"""

    score_config = config or PoseScoreConfig()
    flags: list[str] = []
    if not observation.has_pose:
        if confidence_accumulator is not None:
            confidence_accumulator.reset()
        if observation.failure_reason:
            flags.append(observation.failure_reason)
        if observation.depth_valid_in_mask <= 0.0:
            flags.append("no_valid_depth_in_mask")
        if observation.mask_area_ratio <= 0.0:
            flags.append("no_mask")
        return PoseQualityBreakdown(
            final_score=0.0,
            phase_score=0.0,
            reprojection_score=0.0,
            depth_score=0.0,
            jump_score=0.0,
            mask_score=0.0,
            reject_score=0.0,
            confidence_score=0.0,
            gate_score=0.0,
            quality_score=0.0,
            flags=tuple(flags),
        )

    phase_score = _phase_score(observation, flags)
    mask_score = _mask_factor(observation, flags)
    reject_score = _track_reject_factor(observation, flags)
    gate_score = clamp01(phase_score * reject_score)

    reprojection_score, reprojection_valid = _reprojection_score(observation, flags)
    depth_score, depth_valid = _depth_score(observation, flags)
    has_evidence = reprojection_valid or depth_valid
    if not has_evidence:
        flags.append("quality_pending")
    jump_score = _jump_score(observation, flags)
    core_score = _geometry_core(
        reprojection_score=reprojection_score,
        reprojection_valid=reprojection_valid,
        depth_score=depth_score,
        depth_valid=depth_valid,
        config=score_config,
    )
    modulation_score = _bounded_modulator(mask_score, score_config.mask_floor) * _bounded_modulator(
        jump_score,
        score_config.jump_floor,
    )
    quality_score = clamp01(core_score * modulation_score)

    confidence_score = 1.0
    if confidence_accumulator is not None:
        confidence_score = confidence_accumulator.update(quality_score, evidence=has_evidence)

    final_score = clamp01(gate_score * quality_score * confidence_score)
    return PoseQualityBreakdown(
        final_score=final_score,
        phase_score=clamp01(phase_score),
        reprojection_score=clamp01(reprojection_score),
        depth_score=clamp01(depth_score),
        jump_score=clamp01(jump_score),
        mask_score=clamp01(mask_score),
        reject_score=clamp01(reject_score),
        confidence_score=clamp01(confidence_score),
        gate_score=gate_score,
        quality_score=quality_score,
        flags=tuple(flags),
    )


def _phase_score(observation: PoseObservation, flags: list[str]) -> float:
    """把 pipeline phase 映射为 Gate 层子分。"""

    if observation.phase in {"TRACK", "REGISTER", "RE_REGISTER"}:
        return 1.0
    flags.append(f"phase_{observation.phase.lower()}")
    return 0.7


def _reprojection_score(observation: PoseObservation, flags: list[str]) -> tuple[float, bool]:
    """把重投影质量信号映射为 Quality 层子分。

    track_reprojection<0 表示本帧没有可用颜色信号（未启用、渲染退化或纯色/无纹理物体）。
    这些情况一律把颜色项排除出几何核（返回 valid=False），而不是惩罚：纯色物体的低分
    会冤枉正确 pose，而真正的坏 pose 已由深度对齐和 mask 面积子分负责拦截。
    """

    reprojection = float(observation.track_reprojection)
    if reprojection < 0.0:
        flags.append("no_reprojection_signal")
        return 1.0, False
    score = clamp01(reprojection)
    if score < 0.5:
        flags.append("reprojection_low")
    return score, True


def _depth_score(observation: PoseObservation, flags: list[str] | None) -> tuple[float, bool]:
    """把深度对齐质量映射为 Quality 层子分。"""

    depth_coverage = clamp01(float(observation.depth_valid_in_mask))
    if depth_coverage < MIN_DEPTH_COVERAGE:
        _append_flag(flags, "depth_coverage_insufficient")
        return 0.5, False

    alignment = clamp01(float(observation.render_quality_depth_alignment))
    if _has_render_depth_signal(observation):
        if alignment < 0.5:
            _append_flag(flags, "depth_alignment_low")
        return alignment, True

    if observation.render_quality_expected:
        _append_flag(flags, "depth_alignment_missing_expected")
    else:
        _append_flag(flags, "no_depth_alignment_signal")
    return 0.5, False


def _geometry_core(
    *,
    reprojection_score: float,
    reprojection_valid: bool,
    depth_score: float,
    depth_valid: bool,
    config: PoseScoreConfig,
) -> float:
    """对有效几何证据取加权几何平均；两路都无信号时保持当前 pose 信任。"""

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


def _bounded_modulator(score: float, floor: float) -> float:
    """把非几何子分映射到 [floor, 1]，只作为温和调制项。"""

    lower = clamp01(float(floor))
    return clamp01(lower + (1.0 - lower) * clamp01(float(score)))


def _has_render_depth_signal(observation: PoseObservation) -> bool:
    """判断本帧是否已经拿到渲染深度对齐结果，包括明确的低分结果。"""

    status = str(observation.render_quality_status or "")
    return status.startswith("valid") or observation.render_quality_depth_inlier > 0.0 or observation.render_quality_depth_residual_m > 0.0


def _jump_score(observation: PoseObservation, flags: list[str]) -> float:
    """按帧间隔自适应软阈值，把相邻 pose 增量映射为连续 jump 子分。"""

    dt = max(float(observation.frame_dt_s), 1e-3) if observation.frame_dt_s > 0.0 else EXPECTED_FRAME_DT_S
    dt_scale = clamp(dt / EXPECTED_FRAME_DT_S, 0.5, 8.0)
    soft_t = BASE_SOFT_TRANSLATION_M * dt_scale
    soft_r = BASE_SOFT_ROTATION_DEG * dt_scale
    t_score = _soft_limit_score(abs(float(observation.last_translation_delta_m)), soft_t, HARD_TRANSLATION_M)
    r_score = _soft_limit_score(abs(float(observation.last_rotation_delta_deg)), soft_r, HARD_ROTATION_DEG)
    score = clamp01(min(t_score, r_score))
    if score < 0.5:
        flags.append("near_jump_limit")
    return score


def _mask_factor(observation: PoseObservation, flags: list[str]) -> float:
    """把 mask 可见面积映射为连续 Quality 层子分。"""

    if _has_projection_area_signal(observation):
        score = clamp01(float(observation.render_quality_area_ratio_score))
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
    """判断本帧投影面积是否可用于 mask_score。"""

    status = str(observation.render_quality_status or "")
    return observation.render_quality_render_area_px > 0 and (observation.track_reprojection >= 0.0 or status.startswith("valid"))


def _track_reject_factor(observation: PoseObservation, flags: list[str]) -> float:
    """保留近期 track reject 的 Gate 层子分。"""

    if observation.track_reject_count > 0:
        flags.append("recent_track_reject")
        return max(0.25, 1.0 - min(observation.track_reject_count, 5) * 0.12)
    return 1.0


def _soft_limit_score(value: float, soft_limit: float, hard_limit: float) -> float:
    """软阈值内满分，超过软阈值后线性下降到硬阈值。"""

    soft = max(0.0, float(soft_limit))
    hard = max(soft + 1e-6, float(hard_limit))
    if value <= soft:
        return 1.0
    return clamp01(1.0 - (float(value) - soft) / (hard - soft))


def _append_flag(flags: list[str] | None, flag: str) -> None:
    """仅在 caller 需要 flags 时追加诊断文本。"""

    if flags is not None:
        flags.append(flag)

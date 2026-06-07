"""轻量 pose observation 可靠性评分。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from egoanchor.utils import clamp01

if TYPE_CHECKING:
    from egoanchor.perception import PoseObservation

JUMP_TRANSLATION_THRESHOLD_M = 0.6
"""接近该平移跳变门限时降低可靠性，单位米；与默认 FoundationPose track jump 配置一致。"""

JUMP_ROTATION_THRESHOLD_DEG = 100.0
"""接近该旋转跳变门限时降低可靠性，单位度；与默认 FoundationPose track jump 配置一致。"""


@dataclass(frozen=True, slots=True)
class PoseQualityBreakdown:
    """Pose reliability 评分分解，便于 HUD/日志逐项诊断。"""

    final_score: float
    """最终可靠性分，范围 0..1。"""

    phase_score: float
    """pipeline phase 子分。"""

    consistency_score: float
    """渲染一致性子分。"""

    depth_score: float
    """mask/depth 有效率子分。"""

    jump_score: float
    """相邻 pose 跳变子分。"""

    mask_score: float
    """mask 面积子分。"""

    reject_score: float
    """近期 track reject 子分。"""

    flags: tuple[str, ...]
    """解释最终分数的 flags。"""


def score_observation_breakdown(observation: PoseObservation) -> PoseQualityBreakdown:
    """根据一致性、depth、跳变幅度、mask 和 phase 生成完整评分分解。"""

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
            phase_score=0.0,
            consistency_score=0.0,
            depth_score=0.0,
            jump_score=0.0,
            mask_score=0.0,
            reject_score=0.0,
            flags=tuple(flags),
        )

    phase_weight = 1.0
    if observation.phase not in {"TRACK", "REGISTER", "RE_REGISTER"}:
        phase_weight = 0.7
        flags.append(f"phase_{observation.phase.lower()}")

    consistency_score = _consistency_score(observation, flags)
    depth_score = score_depth_quality(observation)
    _append_depth_flags(observation, flags)
    jump_score = _jump_score(observation, flags)
    mask_factor = _mask_factor(observation, flags)
    reject_factor = _track_reject_factor(observation, flags)
    score = phase_weight * consistency_score * depth_score * jump_score * mask_factor * reject_factor
    return PoseQualityBreakdown(
        final_score=clamp01(score),
        phase_score=clamp01(phase_weight),
        consistency_score=clamp01(consistency_score),
        depth_score=clamp01(depth_score),
        jump_score=clamp01(jump_score),
        mask_score=clamp01(mask_factor),
        reject_score=clamp01(reject_factor),
        flags=tuple(flags),
    )


def score_depth_quality(observation: PoseObservation) -> float:
    """把 mask 内有效深度比例映射为可单独展示的 0..1 深度质量子分。"""

    valid_in_mask = float(observation.depth_valid_in_mask)
    ramp = clamp01((valid_in_mask - 0.05) / 0.30)
    score = 0.3 + ramp * 0.7
    if observation.depth_valid_ratio < 0.05:
        score *= 0.65
    return clamp01(score)


def _consistency_score(observation: PoseObservation, flags: list[str]) -> float:
    """把渲染一致性转为主可靠性子分。"""

    consistency = float(observation.track_consistency)
    if consistency < 0.0:
        if observation.consistency_expected:
            flags.append("consistency_missing_expected")
            return 0.30
        flags.append("no_consistency_signal")
        return 1.0
    score = clamp01(consistency)
    if score < 0.5:
        flags.append("consistency_low")
    return score


def _append_depth_flags(observation: PoseObservation, flags: list[str]) -> None:
    """根据 depth 诊断追加解释性 flags。"""

    if observation.depth_valid_in_mask < 0.08:
        flags.append("depth_in_mask_low")
    elif observation.depth_valid_in_mask < 0.2:
        flags.append("depth_in_mask_mid")

    if observation.depth_valid_ratio < 0.05:
        flags.append("depth_ratio_low")


def _jump_score(observation: PoseObservation, flags: list[str]) -> float:
    """把相邻 pose 增量映射为接近跳变门限的惩罚。"""

    translation_ratio = abs(float(observation.last_translation_delta_m)) / max(JUMP_TRANSLATION_THRESHOLD_M, 1e-6)
    rotation_ratio = abs(float(observation.last_rotation_delta_deg)) / max(JUMP_ROTATION_THRESHOLD_DEG, 1e-6)
    score = clamp01(1.0 - max(translation_ratio, rotation_ratio))
    if score < 0.5:
        flags.append("near_jump_limit")
    return score


def _mask_factor(observation: PoseObservation, flags: list[str]) -> float:
    """保留 mask 面积异常的乘性因子。"""

    if observation.mask_area_ratio < 0.002:
        flags.append("mask_too_small")
        return 0.5
    elif observation.mask_area_ratio > 0.65:
        flags.append("mask_too_large")
        return 0.55
    return 1.0


def _track_reject_factor(observation: PoseObservation, flags: list[str]) -> float:
    """保留近期 track reject 的乘性因子。"""

    if observation.track_reject_count > 0:
        flags.append("recent_track_reject")
        return max(0.25, 1.0 - min(observation.track_reject_count, 5) * 0.12)
    return 1.0

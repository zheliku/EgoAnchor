"""轻量 pose observation 可靠性评分。

当前只用于 Python debug HUD，不把它宣称为最终 adaptive controller。后续接入
NATS/status 时，可继续把 flags 作为诊断信息上报。
"""

from __future__ import annotations

from egoanchor.perception import PoseObservation


def score_observation(observation: PoseObservation) -> tuple[float, tuple[str, ...]]:
    """根据 depth、mask、phase 和 has_pose 生成 0..1 可靠性评分。"""

    flags: list[str] = []
    if not observation.has_pose:
        if observation.failure_reason:
            flags.append(observation.failure_reason)
        if observation.depth_valid_in_mask <= 0.0:
            flags.append("no_valid_depth_in_mask")
        if observation.mask_area_ratio <= 0.0:
            flags.append("no_mask")
        return 0.0, tuple(flags)

    score = 1.0
    if observation.phase in {"TRACK", "REGISTER", "RE_REGISTER"}:
        score *= 1.0
    else:
        score *= 0.7
        flags.append(f"phase_{observation.phase.lower()}")

    if observation.depth_valid_in_mask < 0.08:
        score *= 0.35
        flags.append("depth_in_mask_low")
    elif observation.depth_valid_in_mask < 0.2:
        score *= 0.65
        flags.append("depth_in_mask_mid")

    if observation.depth_valid_ratio < 0.05:
        score *= 0.65
        flags.append("depth_ratio_low")

    if observation.mask_area_ratio < 0.002:
        score *= 0.5
        flags.append("mask_too_small")
    elif observation.mask_area_ratio > 0.65:
        score *= 0.55
        flags.append("mask_too_large")

    if observation.track_reject_count > 0:
        score *= max(0.25, 1.0 - min(observation.track_reject_count, 5) * 0.12)
        flags.append("recent_track_reject")

    return float(max(0.0, min(1.0, score))), tuple(flags)

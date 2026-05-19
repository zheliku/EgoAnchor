"""v2 pose quality 轻量规则。"""

from __future__ import annotations

from egoanchor.perception import PoseObservation


def score_observation(observation: PoseObservation) -> float:
    """把 PoseObservation 转换为 0..1 可信度分数。

    当前仍是轻量规则，不宣称是最终论文 controller：
    - 无 pose 直接 0；
    - 有 pose 时综合 mask 内有效深度、全局有效深度、mask 面积；
    - track/re-register 比 register 稍可信，reject/wait 类 phase 会降低分数。
    后续再加入 mask area、jump reject、phase、innovation 等论文需要的诊断项。
    """

    if not observation.has_pose:
        return 0.0
    depth_score = max(0.0, min(1.0, float(observation.depth_valid_in_mask or observation.depth_valid_ratio)))
    global_depth_score = max(0.0, min(1.0, float(observation.depth_valid_ratio)))
    mask_area = max(0.0, min(1.0, float(observation.mask_area_ratio)))
    # 太小的 mask 说明检测不稳定；超过 3% 后不再额外加分。
    mask_score = max(0.0, min(1.0, mask_area / 0.03))

    phase = observation.phase.upper()
    phase_bonus = 1.0
    if phase == "REGISTER":
        phase_bonus = 0.85
    elif phase == "RE_REGISTER":
        phase_bonus = 0.8
    elif "REJECT" in phase or "WAIT" in phase:
        phase_bonus = 0.35

    score = (0.55 * depth_score + 0.25 * global_depth_score + 0.20 * mask_score) * phase_bonus
    return max(0.0, min(1.0, score))

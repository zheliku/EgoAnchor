"""RQ2 平移/旋转双任务分析的稳定契约。"""

from __future__ import annotations

from dataclasses import dataclass


RQ2_CONDITIONS: tuple[str, str] = ("translation", "rotation")
"""正式 RQ2 接受的两类物体运动。"""

REQUIRED_VARIANTS: tuple[str, str] = ("Full", "ZOH")
"""每个渲染时刻同步记录的两个系统配置。"""

ACTIVE_GAP_FILL_MS = 200.0
"""活动段允许桥接的短暂低速间隙。"""

ACTIVE_MIN_RUN_MS = 300.0
"""活动段保留的最短连续运动时长。"""

ACTIVE_TRANSLATION_MIN_M_S = 0.02
"""平移试次的绝对最低运动阈值。"""

ACTIVE_ROTATION_MIN_DEG_S = 10.0
"""旋转试次的绝对最低运动阈值。"""

ACTIVE_TARGET_RATIO = 0.20
"""活动阈值相对名义目标速度的比例。"""

DISPLAY_HOLD_TRANSLATION_EPS_M = 1e-6
"""相邻显示位置变化不超过该值时视为零阶保持。"""

DISPLAY_HOLD_ROTATION_EPS_DEG = 1e-4
"""相邻显示旋转变化不超过该值时视为零阶保持。"""

@dataclass(frozen=True)
class RQ2Config:
    """一次 RQ2 分析使用的冻结参数。"""

    max_translation_speed_m_s: float = 0.8
    """纳入中低速平移分析的最大参考线速度。"""

    max_rotation_speed_deg_s: float = 180.0
    """纳入中低速旋转分析的最大参考角速度。"""

    min_analysis_duration_s: float = 8.0
    """一个试次通过质量审计所需的最短有效运动时长。"""

    min_reference_coverage: float = 0.95
    """活动段中新鲜平台参考位姿的最低覆盖率。"""

    zoom_frame_count: int = 120
    """论文 XYZ-t 时间线使用的固定渲染帧数。"""


__all__ = [
    "ACTIVE_GAP_FILL_MS",
    "ACTIVE_MIN_RUN_MS",
    "ACTIVE_ROTATION_MIN_DEG_S",
    "ACTIVE_TARGET_RATIO",
    "ACTIVE_TRANSLATION_MIN_M_S",
    "DISPLAY_HOLD_ROTATION_EPS_DEG",
    "DISPLAY_HOLD_TRANSLATION_EPS_M",
    "REQUIRED_VARIANTS",
    "RQ2_CONDITIONS",
    "RQ2Config",
]

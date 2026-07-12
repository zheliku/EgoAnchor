"""RQ2 动态追踪分析的稳定契约。"""

from __future__ import annotations

from dataclasses import dataclass


RQ2_CONDITIONS: tuple[str, ...] = ("slow_translation", "fast_motion", "rotation")
"""RQ2 正式分析接受的三类动态场景。"""

REQUIRED_VARIANTS: tuple[str, str] = ("Full", "Raw-ZOH")
"""正式 RQ2 同帧记录的两个系统配置。"""

PRE_IMAGE_FIT_WINDOW_MS = 400.0
"""局部运动拟合只使用图像时刻之前固定 400 ms 的参考轨迹。"""

PRE_IMAGE_MIN_SAMPLES = 4
"""固定窗口内稳健拟合所需的最少参考 pose 数。"""

ACTIVE_GAP_FILL_MS = 200.0
"""active-motion 标记允许桥接的短暂低速间隙。"""

ACTIVE_MIN_RUN_MS = 300.0
"""active-motion 标记保留的最短连续运动段。"""

ACTIVE_TRANSLATION_MIN_M_S = 0.02
"""平移 trial 的绝对最低运动阈值。"""

ACTIVE_ROTATION_MIN_DEG_S = 10.0
"""旋转 trial 的绝对最低运动阈值。"""

ACTIVE_TARGET_RATIO = 0.20
"""active-motion 阈值相对名义目标速度的比例。"""

MODEL_MAX_SPEED_CV = 0.50
"""时延关联纳入样本允许的局部速度变异系数上限。"""

MODEL_MIN_AXIS_CONSISTENCY = 0.80
"""时延关联纳入样本要求的局部运动轴一致性下限。"""

LAG_GAP_FACTOR = 2.5
"""连续段阈值相对有效样本中位间隔的倍数。"""

LAG_GAP_MIN_MS = 100.0
"""连续段缺口阈值的最小值。"""

LAG_GAP_ABSOLUTE_CAP_MS = 500.0
"""连续段缺口阈值的绝对上限。"""

LAG_MIN_SIGNAL_STD = 1e-5
"""速度信号低于该标准差时视为缺少动态激励。"""

LAG_MIN_PEAK_CORRELATION = 0.50
"""峰值归一化相关低于该值时不报告 lag。"""

LAG_MIN_PROMINENCE = 0.05
"""最佳相关峰相对次峰的最小突出度。"""

LAG_MIN_SIGNAL_SAMPLES = 16
"""lag 估计所需的最少速度样本数。"""

DISPLAY_HOLD_TRANSLATION_EPS_M = 1e-6
"""相邻显示位置变化不超过该阈值时视为保持。"""

DISPLAY_HOLD_ROTATION_EPS_DEG = 1e-4
"""相邻显示旋转变化不超过该阈值时视为保持。"""

BOOTSTRAP_SEED = 20260711
"""RQ2 分层 bootstrap 的固定随机种子。"""

BOOTSTRAP_ITERATIONS = 1000
"""RQ2 默认 bootstrap 重采样次数。"""

LINEAR_SPEED_BINS_M_S: tuple[float, ...] = (
    0.0,
    0.05,
    0.10,
    0.20,
    0.40,
    0.80,
    1.20,
    float("inf"),
)
"""经验运行包络的线速度分箱边界。"""

ANGULAR_SPEED_BINS_DEG_S: tuple[float, ...] = (
    0.0,
    15.0,
    30.0,
    60.0,
    90.0,
    120.0,
    180.0,
    float("inf"),
)
"""经验运行包络的角速度分箱边界。"""


@dataclass(frozen=True)
class RQ2Config:
    """一次 RQ2 分析使用的冻结统计配置。"""

    translation_tolerance_m: float = 0.05
    """次级容限内有效率允许的最大平移误差。"""

    rotation_tolerance_deg: float = 10.0
    """次级容限内有效率允许的最大旋转误差。"""

    min_active_duration_s: float = 8.0
    """正式 trial 通过 active-motion 时长检查所需的最短秒数。"""

    min_trials_per_condition: int = 8
    """每个录制会话、每类运动所需的最少合格 trial 数。"""

    min_sessions: int = 3
    """正式 RQ2 联合分析所需的最少独立录制会话数。"""

    max_lag_ms: float = 500.0
    """轨迹互相关搜索的最大绝对滞后。"""

    bootstrap_iterations: int = BOOTSTRAP_ITERATIONS
    """分层 bootstrap 的重采样次数。"""


SOURCE_COLUMNS = [
    "session_id",
    "condition",
    "rq2_trial_id",
    "label",
    "source_frame_id",
    "active_motion",
    "image_mono_ms",
    "unity_pose_handle_mono_ms",
    "first_render_mono_ms",
    "policy_output_target_mono_ms",
    "observation_age_ms",
    "smoothing_delay_ms",
    "rq2_target_linear_speed_m_s",
    "rq2_target_angular_speed_deg_s",
    "aligned_raw_pos",
    "aligned_raw_rot",
    "gt_image_pos",
    "gt_image_rot",
    "raw_translation_error_image_m",
    "raw_rotation_error_image_deg",
]
"""每个 source frame 首次出现的感知诊断字段。"""


MOTION_COLUMNS = SOURCE_COLUMNS + [
    "handle_delay_ms",
    "render_delay_ms",
    "gt_handle_pos",
    "gt_handle_rot",
    "gt_render_pos",
    "gt_render_rot",
    "raw_translation_error_handle_m",
    "raw_rotation_error_handle_deg",
    "raw_translation_error_render_m",
    "raw_rotation_error_render_deg",
    "pre_image_linear_velocity_m_s",
    "pre_image_angular_velocity_rad_s",
    "pre_image_rotation_axis_world",
    "pre_image_linear_speed_m_s",
    "pre_image_angular_speed_rad_s",
    "pre_image_angular_speed_deg_s",
    "pre_image_linear_speed_cv",
    "pre_image_angular_speed_cv",
    "pre_image_linear_axis_consistency",
    "pre_image_angular_axis_consistency",
    "translation_model_eligible",
    "rotation_model_eligible",
    "reference_translation_motion_handle_m",
    "reference_translation_motion_render_m",
    "reference_rotation_motion_handle_rad",
    "reference_rotation_motion_render_rad",
    "reference_rotation_motion_handle_deg",
    "reference_rotation_motion_render_deg",
    "raw_translation_lag_error_capture_m",
    "raw_translation_lag_error_handle_m",
    "raw_translation_lag_error_render_m",
    "raw_rotation_lag_error_capture_rad",
    "raw_rotation_lag_error_handle_rad",
    "raw_rotation_lag_error_render_rad",
    "raw_rotation_lag_error_capture_deg",
    "raw_rotation_lag_error_handle_deg",
    "raw_rotation_lag_error_render_deg",
    "expected_translation_handle_m",
    "expected_translation_render_m",
    "expected_rotation_handle_rad",
    "expected_rotation_render_rad",
    "expected_rotation_handle_deg",
    "expected_rotation_render_deg",
]
"""source-frame 时延关联与暴露量字段。"""


__all__ = [
    "ACTIVE_GAP_FILL_MS",
    "ACTIVE_MIN_RUN_MS",
    "ACTIVE_ROTATION_MIN_DEG_S",
    "ACTIVE_TARGET_RATIO",
    "ACTIVE_TRANSLATION_MIN_M_S",
    "ANGULAR_SPEED_BINS_DEG_S",
    "BOOTSTRAP_ITERATIONS",
    "BOOTSTRAP_SEED",
    "DISPLAY_HOLD_ROTATION_EPS_DEG",
    "DISPLAY_HOLD_TRANSLATION_EPS_M",
    "LAG_GAP_ABSOLUTE_CAP_MS",
    "LAG_GAP_FACTOR",
    "LAG_GAP_MIN_MS",
    "LAG_MIN_PEAK_CORRELATION",
    "LAG_MIN_PROMINENCE",
    "LAG_MIN_SIGNAL_SAMPLES",
    "LAG_MIN_SIGNAL_STD",
    "LINEAR_SPEED_BINS_M_S",
    "MODEL_MAX_SPEED_CV",
    "MODEL_MIN_AXIS_CONSISTENCY",
    "MOTION_COLUMNS",
    "PRE_IMAGE_FIT_WINDOW_MS",
    "PRE_IMAGE_MIN_SAMPLES",
    "REQUIRED_VARIANTS",
    "RQ2_CONDITIONS",
    "RQ2Config",
    "SOURCE_COLUMNS",
]

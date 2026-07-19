"""实验一/二公共指标的公式、单位、方向和适用场景契约。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


SCENARIO_ORDER = (
    "static_head_motion",
    "start_stop_6dof",
    "continuous_translation",
    "continuous_rotation",
    "occlusion_recovery",
)
"""五个正式物理场景的固定报告顺序。"""

METRIC_DIRECTIONS = ("lower_is_better", "higher_is_better", "descriptive")
"""指标方向枚举；descriptive 表示不参与优劣排序。"""


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    """描述一个可追溯到 event/segment 的科学指标。"""

    key: str
    """稳定机器指标键。"""

    label: str
    """论文和表格使用的读者可读标签。"""

    formula: str
    """公式或计算定义。"""

    unit: str
    """结果单位。"""

    direction: str
    """指标方向。"""

    scenarios: tuple[str, ...]
    """允许使用该指标的场景集合。"""

    aggregation: str
    """从 frame 到 event/segment 再到 session 的汇总层级。"""

    tex_suffix: str
    """用于 LaTeX 控制序列的纯字母后缀。"""

    source_columns: tuple[str, ...]
    """直接参与计算的 Stage 2 列。"""

    primary: bool = False
    """是否是对应场景正文主指标。"""

    def __post_init__(self) -> None:
        """校验方向、场景和 TeX 后缀的静态约束。"""

        if self.direction not in METRIC_DIRECTIONS:
            raise ValueError(f"未知指标方向：{self.direction}")
        if not self.scenarios or not set(self.scenarios).issubset(SCENARIO_ORDER):
            raise ValueError(f"指标场景不在冻结列表中：{self.key}")
        if not self.tex_suffix.isascii() or not self.tex_suffix.isalpha():
            raise ValueError(f"TeX 后缀必须只含字母：{self.tex_suffix}")

    def to_dict(self) -> dict[str, Any]:
        """返回可序列化的指标目录项。"""

        return asdict(self) | {
            "scenarios": list(self.scenarios),
            "source_columns": list(self.source_columns),
        }


_STATIC = (SCENARIO_ORDER[0],)
_START_STOP = (SCENARIO_ORDER[1],)
_TRANSLATION = (SCENARIO_ORDER[2],)
_ROTATION = (SCENARIO_ORDER[3],)
_OCCLUSION = (SCENARIO_ORDER[4],)


_EVENT_WINDOW_COLUMNS = (
    "events.event",
    "events.event_id",
    "events.mono_ms",
    "event_payload.event_role",
)
"""event/segment 切窗使用的物理工作簿列。"""

_RENDER_TIME_COLUMNS = ("unity_render.render_tick_id", "unity_render.render_mono_ms")
"""render 时间和相邻 tick 检查使用的物理列。"""

_DISPLAY_VALID_COLUMNS = (
    "unity_render.has_display_pose",
    "unity_render.reference_pose_valid",
)
"""显示误差合法性使用的物理列；HELD reference 仍保持有效。"""

_DISPLAY_POSITION_COLUMNS = tuple(f"unity_render.display_pos_{axis}_m" for axis in "xyz")
"""display 世界位置三轴物理列。"""

_REFERENCE_POSITION_COLUMNS = tuple(f"unity_render.reference_pos_{axis}_m" for axis in "xyz")
"""同 tick 平台参考世界位置三轴物理列。"""

_DISPLAY_ROTATION_COLUMNS = tuple(f"unity_render.display_rot_{axis}" for axis in "xyzw")
"""display xyzw 四元数物理列。"""

_REFERENCE_ROTATION_COLUMNS = tuple(f"unity_render.reference_rot_{axis}" for axis in "xyzw")
"""同 tick 平台参考 xyzw 四元数物理列。"""

_POSITION_ERROR_COLUMNS = (
    *_EVENT_WINDOW_COLUMNS,
    *_RENDER_TIME_COLUMNS,
    *_DISPLAY_VALID_COLUMNS,
    *_DISPLAY_POSITION_COLUMNS,
    *_REFERENCE_POSITION_COLUMNS,
)
"""平移显示误差指标共享的物理来源列。"""

_ROTATION_ERROR_COLUMNS = (
    *_EVENT_WINDOW_COLUMNS,
    *_RENDER_TIME_COLUMNS,
    *_DISPLAY_VALID_COLUMNS,
    *_DISPLAY_ROTATION_COLUMNS,
    *_REFERENCE_ROTATION_COLUMNS,
)
"""旋转显示误差指标共享的物理来源列。"""

_MOTION_COLUMNS = (
    "unity_render.reference_linear_speed_m_s",
    "unity_render.reference_angular_speed_deg_s",
)
"""平台参考运动起止检测使用的物理列。"""

_VCD_RISK_COLUMNS = (
    "unity_admission.candidate_id",
    "unity_admission.frame_id",
    "unity_admission.has_aligned_raw",
    "unity_admission.aligned_raw_pos_x_m",
    "unity_admission.aligned_raw_pos_y_m",
    "unity_admission.aligned_raw_pos_z_m",
    "unity_admission.vcd_score",
    "unity_reference.frame_id",
    "unity_reference.reference_pose_valid",
    "unity_reference.reference_pos_x_m",
    "unity_reference.reference_pos_y_m",
    "unity_reference.reference_pos_z_m",
)
"""VCD candidate risk 与同 frame 平台参考联接使用的物理列。"""

_CAPTURE_ALIGNMENT_RAW_COLUMNS = (
    "unity_admission.candidate_id",
    "unity_admission.variant_id",
    "unity_admission.frame_id",
    "unity_admission.source_capture_mono_ms",
    "unity_admission.uses_capture_time_alignment",
    "unity_admission.has_aligned_raw",
    "unity_admission.aligned_raw_pos_x_m",
    "unity_admission.aligned_raw_pos_y_m",
    "unity_admission.aligned_raw_pos_z_m",
    "unity_admission.aligned_raw_rot_x",
    "unity_admission.aligned_raw_rot_y",
    "unity_admission.aligned_raw_rot_z",
    "unity_admission.aligned_raw_rot_w",
    "unity_admission.has_arrival_time_raw",
    "unity_admission.arrival_time_raw_pos_x_m",
    "unity_admission.arrival_time_raw_pos_y_m",
    "unity_admission.arrival_time_raw_pos_z_m",
    "unity_admission.arrival_time_raw_rot_x",
    "unity_admission.arrival_time_raw_rot_y",
    "unity_admission.arrival_time_raw_rot_z",
    "unity_admission.arrival_time_raw_rot_w",
    "unity_reference.frame_id",
    "unity_reference.reference_pose_valid",
    "unity_reference.reference_pos_x_m",
    "unity_reference.reference_pos_y_m",
    "unity_reference.reference_pos_z_m",
    "unity_reference.reference_rot_x",
    "unity_reference.reference_rot_y",
    "unity_reference.reference_rot_z",
    "unity_reference.reference_rot_w",
)
"""capture-time/arrival-time raw pose 与同 frame 参考的组件近端来源列。"""


METRIC_DEFINITIONS = (
    MetricDefinition("translation_event_pninetyfive_mm", "平移误差 event-P95", "每个静止头动 event 内对有效 display-reference 平移误差取 linear P95", "mm", "lower_is_better", _STATIC, "render -> event -> session median IQR", "TranslationEventPNinetyFiveMm", _POSITION_ERROR_COLUMNS, True),
    MetricDefinition("centered_translation_pninetyfive_mm", "中心化平移波动 P95", "每个静止头动 event 内先从 display-reference 误差向量减去该 event 的三轴中位偏置，再对模长取 linear P95", "mm", "lower_is_better", _STATIC, "render -> event -> session median IQR", "CenteredTranslationPNinetyFiveMm", _POSITION_ERROR_COLUMNS, True),
    MetricDefinition("capture_alignment_raw_translation_pninetyfive_mm", "采集时刻对齐 raw 平移 P95", "每个静止头动 event 内对 admission raw pose 与同 frame 平台参考的平移误差取 linear P95；按 variant 的 CaptureTime/ArrivalTime raw 语义选择输入", "mm", "lower_is_better", _STATIC, "admission raw -> event -> session median IQR", "CaptureAlignmentRawTranslationPNinetyFiveMm", _CAPTURE_ALIGNMENT_RAW_COLUMNS),
    MetricDefinition("capture_alignment_raw_rotation_pninetyfive_deg", "采集时刻对齐 raw 旋转 P95", "每个静止头动 event 内对 admission raw pose 与同 frame 平台参考的最短弧旋转误差取 linear P95，作为采集时刻对齐的旋转护栏", "deg", "lower_is_better", _STATIC, "admission raw -> event -> session median IQR", "CaptureAlignmentRawRotationPNinetyFiveDeg", _CAPTURE_ALIGNMENT_RAW_COLUMNS),
    MetricDefinition("position_hp_rms_mm", "位置 HP-RMS", "三轴参考相对误差按连续片段重采样，二阶 1 Hz Butterworth 零相位高通后计算向量 RMS", "mm", "lower_is_better", _STATIC, "render -> event -> session median IQR", "PositionHpRmsMm", _POSITION_ERROR_COLUMNS, True),
    MetricDefinition("rotation_event_pninetyfive_deg", "旋转误差 event-P95", "每个静止头动 event 内对四元数最短弧误差取 linear P95", "deg", "lower_is_better", _STATIC, "render -> event -> session median IQR", "RotationEventPNinetyFiveDeg", _ROTATION_ERROR_COLUMNS),
    MetricDefinition("absolute_translation_median_mm", "绝对平移误差中位数", "每个静止头动 event 内有效 display-reference 平移误差中位数", "mm", "lower_is_better", _STATIC, "render -> event -> session median IQR", "AbsoluteTranslationMedianMm", _POSITION_ERROR_COLUMNS),
    MetricDefinition("position_drift_mm", "位置漂移", "参考相对误差向量最后 1 秒均值与最初 1 秒均值之间的欧氏距离", "mm", "lower_is_better", _STATIC, "render -> event -> session median IQR", "PositionDriftMm", _POSITION_ERROR_COLUMNS),
    MetricDefinition("visible_response_ms", "可见响应时间", "平台参考实际运动开始到 display 相对运动前基线持续响应 100 ms 的首样本", "ms", "lower_is_better", _START_STOP, "render -> transition event -> session median IQR", "VisibleResponseMs", (*_EVENT_WINDOW_COLUMNS, *_RENDER_TIME_COLUMNS, *_MOTION_COLUMNS, "unity_render.has_display_pose", *_DISPLAY_POSITION_COLUMNS, *_DISPLAY_ROTATION_COLUMNS), True),
    MetricDefinition("settling_time_ms", "沉降时间", "平台参考实际停止到平移误差不高于 20 mm 并持续 250 ms 的首样本", "ms", "lower_is_better", _START_STOP, "render -> transition event -> session median IQR", "SettlingTimeMs", (*_POSITION_ERROR_COLUMNS, *_MOTION_COLUMNS), True),
    MetricDefinition("post_stop_position_jitter_rms_mm", "停止后位置 jitter RMS", "参考实际停止后跳过 1000 ms，在随后固定 3000 ms 公共窗口内将三轴 display-reference 误差按轴减去中位数，再计算向量 RMS", "mm", "lower_is_better", _START_STOP, "render -> transition event -> session median IQR", "PostStopPositionJitterRmsMm", (*_POSITION_ERROR_COLUMNS, *_MOTION_COLUMNS), True),
    MetricDefinition("motion_hold_ratio", "运动窗近零保持比例", "参考实际运动窗口内连续有效 render pair 的位置增量不高于 0.001 mm 且旋转增量不高于 0.001 deg 的比例", "proportion", "lower_is_better", _START_STOP, "render pair -> transition event -> session median IQR", "MotionHoldRatio", (*_EVENT_WINDOW_COLUMNS, *_RENDER_TIME_COLUMNS, *_MOTION_COLUMNS, "unity_render.has_display_pose", *_DISPLAY_POSITION_COLUMNS, *_DISPLAY_ROTATION_COLUMNS)),
    MetricDefinition("motion_translation_pninetyfive_mm", "运动窗平移 P95", "每个参考实际运动窗口内有效 display-reference 平移误差的 linear P95", "mm", "lower_is_better", _START_STOP, "render -> transition event -> session median IQR", "MotionTranslationPNinetyFiveMm", (*_POSITION_ERROR_COLUMNS, *_MOTION_COLUMNS), True),
    MetricDefinition("start_stop_rotation_pninetyfive_deg", "运动窗旋转 P95", "每个参考实际运动窗口内有效 display-reference 最短弧旋转误差的 linear P95", "deg", "lower_is_better", _START_STOP, "render -> transition event -> session median IQR", "StartStopRotationPNinetyFiveDeg", (*_ROTATION_ERROR_COLUMNS, *_MOTION_COLUMNS)),
    MetricDefinition("motion_translation_peak_mm", "运动窗平移峰值误差", "每个参考实际运动窗口内有效 display-reference 平移误差的最大值", "mm", "lower_is_better", _START_STOP, "render -> transition event -> session median IQR", "MotionTranslationPeakMm", (*_POSITION_ERROR_COLUMNS, *_MOTION_COLUMNS)),
    MetricDefinition("unlock_time_ms", "StaticLock 解锁时间", "仅对完整 EgoAnchor 诊断；参考实际运动开始到 latest_static_locked 首次由 true 变为 false 的时间", "ms", "lower_is_better", _START_STOP, "render state transition -> transition event -> session median IQR", "UnlockTimeMs", (*_EVENT_WINDOW_COLUMNS, *_RENDER_TIME_COLUMNS, *_MOTION_COLUMNS, "unity_render.latest_static_locked")),
    MetricDefinition("relock_time_ms", "StaticLock 重锁时间", "仅对完整 EgoAnchor 诊断；参考实际停止到 latest_static_locked 首次由 false 变为 true 的时间", "ms", "lower_is_better", _START_STOP, "render state transition -> transition event -> session median IQR", "RelockTimeMs", (*_EVENT_WINDOW_COLUMNS, *_RENDER_TIME_COLUMNS, *_MOTION_COLUMNS, "unity_render.latest_static_locked")),
    MetricDefinition("effective_translation_lag_ms", "有效平移时延", "在统一 0--500 ms 网格最小化 display(t) 与 reference(t-lag) 平移 RMSE，数值并列取较小 lag", "ms", "lower_is_better", _TRANSLATION, "render -> marker segment -> session median IQR", "EffectiveTranslationLagMs", _POSITION_ERROR_COLUMNS, True),
    MetricDefinition("translation_lag_residual_mm", "平移 lag 补偿残差", "有效平移时延最优候选下 display 与 reference(t-lag) 的平移 RMSE", "mm", "lower_is_better", _TRANSLATION, "render -> marker segment -> session median IQR", "TranslationLagResidualMm", _POSITION_ERROR_COLUMNS),
    MetricDefinition("translation_lag_pninetyfive_residual_mm", "平移 lag 补偿 P95", "按 RMSE 选择有效平移时延后，在同一重叠样本上对 display 与 reference(t-lag) 平移残差取 linear P95", "mm", "lower_is_better", _TRANSLATION, "render -> marker segment -> session median IQR", "TranslationLagPNinetyFiveResidualMm", _POSITION_ERROR_COLUMNS, True),
    MetricDefinition("translation_event_pninetyfive_mm_continuous", "持续平移 event-P95", "每个 marker 平移 segment 内有效 display-reference 平移误差的 linear P95", "mm", "lower_is_better", _TRANSLATION, "render -> marker segment -> session median IQR", "ContinuousTranslationPNinetyFiveMm", _POSITION_ERROR_COLUMNS, True),
    MetricDefinition("effective_angular_lag_ms", "有效角时延", "在统一 0--500 ms 网格以 Slerp 最小化 display(t) 与 reference(t-lag) 角 RMSE，数值并列取较小 lag", "ms", "lower_is_better", _ROTATION, "render -> marker segment -> session median IQR", "EffectiveAngularLagMs", _ROTATION_ERROR_COLUMNS, True),
    MetricDefinition("angular_lag_residual_deg", "角 lag 补偿残差", "有效角时延最优候选下 display 与 reference(t-lag) 的最短弧角 RMSE", "deg", "lower_is_better", _ROTATION, "render -> marker segment -> session median IQR", "AngularLagResidualDeg", _ROTATION_ERROR_COLUMNS),
    MetricDefinition("angular_lag_pninetyfive_residual_deg", "角 lag 补偿 P95", "按 RMSE 选择有效角时延后，在同一重叠样本上对 display 与 reference(t-lag) 最短弧角残差取 linear P95", "deg", "lower_is_better", _ROTATION, "render -> marker segment -> session median IQR", "AngularLagPNinetyFiveResidualDeg", _ROTATION_ERROR_COLUMNS, True),
    MetricDefinition("rotation_event_pninetyfive_deg_continuous", "持续旋转 event-P95", "每个 marker 旋转 segment 内有效四元数最短弧误差的 linear P95", "deg", "lower_is_better", _ROTATION, "render -> marker segment -> session median IQR", "ContinuousRotationPNinetyFiveDeg", _ROTATION_ERROR_COLUMNS, True),
    MetricDefinition("occlusion_translation_pninetyfive_mm", "遮挡窗平移 P95", "每个 occlusion_started 到 target_visible 窗口内有效 display-reference 平移误差的 linear P95", "mm", "lower_is_better", _OCCLUSION, "render -> occlusion event -> session median IQR", "OcclusionTranslationPNinetyFiveMm", _POSITION_ERROR_COLUMNS, True),
    MetricDefinition("occlusion_catastrophic_failure_rate", "遮挡灾难性失败率", "每个遮挡 event 的平移 P95 超过 analysis_params.toml 固定阈值时记为 1，否则记为 0；跨 event 取比例", "proportion", "lower_is_better", _OCCLUSION, "occlusion event indicator -> session proportion", "OcclusionCatastrophicFailureRate", _POSITION_ERROR_COLUMNS),
    MetricDefinition("occlusion_rotation_pninetyfive_deg", "遮挡窗旋转 P95", "每个 occlusion_started 到 target_visible 窗口内有效 display-reference 最短弧旋转误差的 linear P95", "deg", "lower_is_better", _OCCLUSION, "render -> occlusion event -> session median IQR", "OcclusionRotationPNinetyFiveDeg", _ROTATION_ERROR_COLUMNS),
    MetricDefinition("occlusion_output_coverage", "遮挡窗输出覆盖率", "每个 occlusion_started 到 target_visible 窗口内 has_output_pose 为真的 render tick 比例", "proportion", "higher_is_better", _OCCLUSION, "render -> occlusion event -> session median IQR", "OcclusionOutputCoverage", (*_EVENT_WINDOW_COLUMNS, *_RENDER_TIME_COLUMNS, "unity_render.has_output_pose")),
    MetricDefinition("reappearance_translation_pninetyfive_mm", "重新可见平移 P95", "target_visible 后固定 1000 ms 公共窗口内有效 display-reference 平移误差的 linear P95", "mm", "lower_is_better", _OCCLUSION, "render -> occlusion event -> session median IQR", "ReappearanceTranslationPNinetyFiveMm", _POSITION_ERROR_COLUMNS),
    MetricDefinition("occlusion_error_update_count", "遮挡期错误更新数", "采集时间位于遮挡窗口且 admission_decision 为 accepted 的唯一 candidate 数量", "count", "lower_is_better", _OCCLUSION, "admitted candidate -> occlusion event -> session median IQR", "OcclusionErrorUpdateCount", (*_EVENT_WINDOW_COLUMNS, "unity_admission.candidate_id", "unity_admission.source_capture_mono_ms", "unity_admission.admission_decision")),
    MetricDefinition("fresh_output_time_ms", "重新可见后的新鲜输出时间", "target_visible 到首个 has_output_pose 且 source_capture_mono_ms 不早于 marker 的 render tick", "ms", "lower_is_better", _OCCLUSION, "render -> occlusion event -> session median IQR", "FreshOutputTimeMs", (*_EVENT_WINDOW_COLUMNS, *_RENDER_TIME_COLUMNS, "unity_render.has_output_pose", "unity_render.has_source_capture_timing", "unity_render.source_capture_mono_ms")),
    MetricDefinition("durable_recovery_time_ms", "持久恢复时间", "target_visible 到首个遮挡后新鲜 output 支持且误差不高于 20 mm 持续 250 ms 的窗口首样本", "ms", "lower_is_better", _OCCLUSION, "render -> occlusion event -> session median IQR", "DurableRecoveryTimeMs", (*_POSITION_ERROR_COLUMNS, "unity_render.has_source_capture_timing", "unity_render.source_capture_mono_ms", "unity_render.has_output_pose"), True),
    MetricDefinition("durable_recovery_success", "持久恢复成功率", "存在 durable recovery 的遮挡事件数除以闭合遮挡事件总数", "proportion", "higher_is_better", _OCCLUSION, "occlusion event -> session proportion", "DurableRecoverySuccess", (*_POSITION_ERROR_COLUMNS, "unity_render.has_source_capture_timing", "unity_render.source_capture_mono_ms", "unity_render.has_output_pose"), True),
    MetricDefinition("jump_pninetyfive_mm", "平移跳变 P95", "每个 event 内相邻有效 render tick 的 display 平移跳变 linear P95，不跨大间隙", "mm", "lower_is_better", SCENARIO_ORDER, "render pair -> event -> session median IQR", "JumpPNinetyFiveMm", (*_EVENT_WINDOW_COLUMNS, *_RENDER_TIME_COLUMNS, "unity_render.has_display_pose", *_DISPLAY_POSITION_COLUMNS)),
    MetricDefinition("jump_pninetynine_mm", "平移跳变 P99", "每个 event 内相邻有效 render tick 的 display 平移跳变 linear P99，不跨大间隙", "mm", "lower_is_better", SCENARIO_ORDER, "render pair -> event -> session median IQR", "JumpPNinetyNineMm", (*_EVENT_WINDOW_COLUMNS, *_RENDER_TIME_COLUMNS, "unity_render.has_display_pose", *_DISPLAY_POSITION_COLUMNS)),
    MetricDefinition("jump_pninetyfive_deg", "旋转跳变 P95", "每个 event 内相邻有效 render tick 的 display 四元数最短弧跳变 linear P95，不跨大间隙", "deg", "lower_is_better", SCENARIO_ORDER, "render pair -> event -> session median IQR", "JumpPNinetyFiveDeg", (*_EVENT_WINDOW_COLUMNS, *_RENDER_TIME_COLUMNS, "unity_render.has_display_pose", *_DISPLAY_ROTATION_COLUMNS)),
    MetricDefinition("jump_pninetynine_deg", "旋转跳变 P99", "每个 event 内相邻有效 render tick 的 display 四元数最短弧跳变 linear P99，不跨大间隙", "deg", "lower_is_better", SCENARIO_ORDER, "render pair -> event -> session median IQR", "JumpPNinetyNineDeg", (*_EVENT_WINDOW_COLUMNS, *_RENDER_TIME_COLUMNS, "unity_render.has_display_pose", *_DISPLAY_ROTATION_COLUMNS)),
    MetricDefinition("display_coverage", "显示覆盖率", "event 内 has_display_pose 为真的 render tick 数除以全部 render tick 数", "proportion", "higher_is_better", SCENARIO_ORDER, "render -> event -> session median IQR", "DisplayCoverage", (*_EVENT_WINDOW_COLUMNS, *_RENDER_TIME_COLUMNS, "unity_render.has_display_pose")),
    MetricDefinition("output_coverage", "输出覆盖率", "event 内 has_output_pose 为真的 render tick 数除以全部 render tick 数", "proportion", "higher_is_better", SCENARIO_ORDER, "render -> event -> session median IQR", "OutputCoverage", (*_EVENT_WINDOW_COLUMNS, *_RENDER_TIME_COLUMNS, "unity_render.has_output_pose")),
    MetricDefinition("candidate_arrival_median_ms", "候选到达时延中位数", "同一 candidate 的 unity_pose_handle_mono_ms 减 source_capture_mono_ms，仅使用 Unity 单调时钟", "ms", "descriptive", SCENARIO_ORDER, "candidate -> event -> session median IQR", "CandidateArrivalMedianMs", ("unity_admission.candidate_id", "unity_admission.source_capture_mono_ms", "unity_admission.unity_pose_handle_mono_ms")),
    MetricDefinition("python_processing_median_ms", "Python 处理时延中位数", "server_publish_mono_ms 减 server_receive_mono_ms，仅使用 Python 单调时钟", "ms", "descriptive", SCENARIO_ORDER, "candidate -> event -> session median IQR", "PythonProcessingMedianMs", ("python_candidates.candidate_id", "python_candidates.server_receive_mono_ms", "python_candidates.server_publish_mono_ms", "unity_admission.candidate_id", "unity_admission.event_id")),
    MetricDefinition("vcd_mean_risk_aurc_mm", "VCD mean-risk AURC", "完整 EgoAnchor 候选按 VCD 分数 tie group 降序纳入，以 capture-time aligned raw 同帧平台参考平移误差的累计算术平均构成曲线，并从 coverage 0 使用右连续经验阶梯积分", "mm", "lower_is_better", _OCCLUSION, "eligible received candidate score groups -> scenario right-step AURC", "VcdMeanRiskAurcMm", _VCD_RISK_COLUMNS),
)
"""五场景主指标、guardrail、时延和 VCD 诊断指标目录。"""


def _validate_metric_definitions() -> None:
    """拒绝会造成 CSV 主键或 TeX 控制序列冲突的重复指标。"""

    keys = [metric.key for metric in METRIC_DEFINITIONS]
    suffixes = [metric.tex_suffix for metric in METRIC_DEFINITIONS]
    if len(keys) != len(set(keys)):
        raise ValueError("指标目录包含重复 metric key")
    if len(suffixes) != len(set(suffixes)):
        raise ValueError("指标目录包含重复 TeX 后缀")


_validate_metric_definitions()


def metric_catalog() -> list[dict[str, Any]]:
    """返回所有指标的普通字典目录。"""

    return [metric.to_dict() for metric in METRIC_DEFINITIONS]


def get_metric_definition(key: str) -> MetricDefinition:
    """按稳定指标键查找定义，未知键立即报错。"""

    for metric in METRIC_DEFINITIONS:
        if metric.key == key:
            return metric
    raise KeyError(f"未知指标键：{key}")


__all__ = [
    "METRIC_DEFINITIONS",
    "METRIC_DIRECTIONS",
    "SCENARIO_ORDER",
    "MetricDefinition",
    "get_metric_definition",
    "metric_catalog",
]

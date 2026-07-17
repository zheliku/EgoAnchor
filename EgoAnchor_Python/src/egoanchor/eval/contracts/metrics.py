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
        if not self.tex_suffix.isalpha() or not self.tex_suffix[0].isalpha():
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


METRIC_DEFINITIONS = (
    MetricDefinition("translation_event_pninetyfive_mm", "平移误差 event-P95", "Q_0.95(||p_display-p_reference||)", "mm", "lower_is_better", _STATIC, "frame -> event -> median IQR", "TranslationEventPNinetyFiveMm", ("display_pos", "reference_pos"), True),
    MetricDefinition("position_hp_rms_mm", "位置 HP-RMS", "RMS(high_pass(display_pos-reference_pos))", "mm", "lower_is_better", _STATIC, "frame -> event -> median IQR", "PositionHpRmsMm", ("display_pos", "reference_pos"), True),
    MetricDefinition("rotation_event_pninetyfive_deg", "旋转误差 event-P95", "Q_0.95(rotation_error)", "deg", "lower_is_better", _STATIC, "frame -> event -> median IQR", "RotationEventPNinetyFiveDeg", ("display_rot", "reference_rot")),
    MetricDefinition("absolute_translation_median_mm", "绝对平移误差中位数", "median(||p_display-p_reference||)", "mm", "lower_is_better", _STATIC, "frame -> event -> median IQR", "AbsoluteTranslationMedianMm", ("display_pos", "reference_pos")),
    MetricDefinition("position_drift_mm", "位置漂移", "||mean(last)-mean(first)||", "mm", "lower_is_better", _STATIC, "event -> median IQR", "PositionDriftMm", ("display_pos",)),
    MetricDefinition("visible_response_ms", "可见响应时间", "first_visible_output - transition_started", "ms", "lower_is_better", _START_STOP, "event -> median IQR", "VisibleResponseMs", ("has_display_pose",), True),
    MetricDefinition("settling_time_ms", "沉降时间", "first durable settled sample - transition_started", "ms", "lower_is_better", _START_STOP, "event -> median IQR", "SettlingTimeMs", ("display_pos", "reference_pos"), True),
    MetricDefinition("motion_translation_pninetyfive_mm", "运动窗平移 P95", "Q_0.95(||p_display-p_reference||)", "mm", "lower_is_better", _START_STOP, "frame -> event -> median IQR", "MotionTranslationPNinetyFiveMm", ("display_pos", "reference_pos"), True),
    MetricDefinition("effective_translation_lag_ms", "有效平移时延", "argmin lagged residual", "ms", "lower_is_better", _TRANSLATION, "event -> median IQR", "EffectiveTranslationLagMs", ("display_pos", "reference_pos"), True),
    MetricDefinition("translation_event_pninetyfive_mm_continuous", "持续平移 event-P95", "Q_0.95(||p_display-p_reference||)", "mm", "lower_is_better", _TRANSLATION, "frame -> event -> median IQR", "ContinuousTranslationPNinetyFiveMm", ("display_pos", "reference_pos"), True),
    MetricDefinition("effective_angular_lag_ms", "有效角时延", "argmin lagged angular residual", "ms", "lower_is_better", _ROTATION, "event -> median IQR", "EffectiveAngularLagMs", ("display_rot", "reference_rot"), True),
    MetricDefinition("rotation_event_pninetyfive_deg_continuous", "持续旋转 event-P95", "Q_0.95(rotation_error)", "deg", "lower_is_better", _ROTATION, "frame -> event -> median IQR", "ContinuousRotationPNinetyFiveDeg", ("display_rot", "reference_rot"), True),
    MetricDefinition("occlusion_translation_pninetyfive_mm", "遮挡窗平移 P95", "Q_0.95(||p_display-p_reference||)", "mm", "lower_is_better", _OCCLUSION, "frame -> event -> median IQR", "OcclusionTranslationPNinetyFiveMm", ("display_pos", "reference_pos"), True),
    MetricDefinition("durable_recovery_time_ms", "持久恢复时间", "first durable target_visible - occlusion_started", "ms", "lower_is_better", _OCCLUSION, "event -> median IQR", "DurableRecoveryTimeMs", ("has_display_pose",), True),
    MetricDefinition("durable_recovery_success", "持久恢复成功率", "durable recovery events / occlusion events", "proportion", "higher_is_better", _OCCLUSION, "event -> proportion", "DurableRecoverySuccess", ("has_display_pose",), True),
    MetricDefinition("jump_pninetyfive_mm", "平移跳变 P95", "Q_0.95(||p_t-p_{t-1}||)", "mm", "lower_is_better", SCENARIO_ORDER, "frame -> event -> median IQR", "JumpPNinetyFiveMm", ("display_pos",)),
    MetricDefinition("jump_pninetyfive_deg", "旋转跳变 P95", "Q_0.95(rotation_delta)", "deg", "lower_is_better", SCENARIO_ORDER, "frame -> event -> median IQR", "JumpPNinetyFiveDeg", ("display_rot",)),
    MetricDefinition("display_coverage", "显示覆盖率", "count(has_display_pose) / count(render)", "proportion", "higher_is_better", SCENARIO_ORDER, "frame -> event -> median IQR", "DisplayCoverage", ("has_display_pose",)),
    MetricDefinition("output_coverage", "输出覆盖率", "count(has_output_pose) / count(render)", "proportion", "higher_is_better", SCENARIO_ORDER, "frame -> event -> median IQR", "OutputCoverage", ("has_output_pose",)),
    MetricDefinition("vcd_aurc_mm", "VCD AURC", "area(coverage, mean risk)", "mm", "lower_is_better", _OCCLUSION, "candidate -> scenario", "VcdAurcMm", ("vcd_score", "risk_mm")),
)
"""五场景主指标、guardrail 指标和 VCD 诊断指标目录。"""


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

"""固定的实验一命名、矩阵与输出契约。"""

EXPERIMENT_ID = "exp1_system_characterization"
"""schema-v2 中实验一的稳定标识。"""

VARIANTS = ("Arrival-Hold", "Capture-Hold", "One-Euro Anchor", "EgoAnchor")
"""实验一的四个系统配置，顺序同时固定配对基线和图表颜色。"""

SCENARIOS = (
    "static_head_motion",
    "start_stop_6dof",
    "continuous_translation",
    "continuous_rotation",
    "occlusion_recovery",
)
"""实验一正式采集必须覆盖的五类场景。"""

OUTPUT_TABLES = (
    "exp1_session_qc.csv",
    "exp1_trial_qc.csv",
    "exp1_trial_metrics.csv",
    "exp1_paired_trial_metrics.csv",
    "exp1_condition_summary.csv",
    "exp1_static_quality.csv",
    "exp1_transition_response.csv",
    "exp1_occlusion_recovery.csv",
    "exp1_latency_summary.csv",
    "exp1_vcd_diagnostics.csv",
)
"""实验一分析入口必须写出的十张稳定 CSV。"""

OUTPUT_FIGURES = (
    "exp1_static_timeline.pdf",
    "exp1_motion_timeline.pdf",
    "exp1_occlusion_recovery.pdf",
    "exp1_system_summary.pdf",
)
"""实验一绘图层必须写出的四个 PDF。"""

DEFAULT_MIN_REFERENCE_COVERAGE = 0.95
"""每个 trial/event 的平台参考有效覆盖率下限。"""

__all__ = [
    "DEFAULT_MIN_REFERENCE_COVERAGE",
    "EXPERIMENT_ID",
    "OUTPUT_FIGURES",
    "OUTPUT_TABLES",
    "SCENARIOS",
    "VARIANTS",
]

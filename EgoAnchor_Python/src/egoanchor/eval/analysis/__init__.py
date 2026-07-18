"""Stage 2 只读取 Stage 1 XLSX 的公共指标分析入口。"""

from .latency import (
    ClockDomain,
    MonotonicTimestamp,
    candidate_arrival_ms,
    elapsed_ms,
    python_processing_ms,
)
from .metrics import (
    JumpQuantiles,
    LagEstimate,
    SummaryStats,
    durable_recovery_time_ms,
    estimate_angular_lag,
    estimate_translation_lag,
    event_quantiles,
    median_iqr,
    pose_jump_quantiles,
    position_drift_mm,
    position_hp_rms_mm,
    settling_time_ms,
    visible_response_ms,
)
from .params import (
    AnalysisParameters,
    DEFAULT_ANALYSIS_PARAMS_PATH,
    analysis_parameters_sha256,
    load_analysis_parameters,
)
from .pose import normalize_quaternion, rotation_error_deg, translation_error_mm
from .windows import (
    EventMarker,
    EventWindow,
    MotionInterval,
    OcclusionWindow,
    build_event_windows,
    detect_reference_motion,
    pair_occlusion_windows,
    parse_event_markers,
)


__all__ = [
    "AnalysisParameters",
    "ClockDomain",
    "DEFAULT_ANALYSIS_PARAMS_PATH",
    "EventMarker",
    "EventWindow",
    "JumpQuantiles",
    "LagEstimate",
    "MonotonicTimestamp",
    "MotionInterval",
    "OcclusionWindow",
    "SummaryStats",
    "build_event_windows",
    "candidate_arrival_ms",
    "analysis_parameters_sha256",
    "detect_reference_motion",
    "durable_recovery_time_ms",
    "elapsed_ms",
    "estimate_angular_lag",
    "estimate_translation_lag",
    "event_quantiles",
    "load_analysis_parameters",
    "median_iqr",
    "normalize_quaternion",
    "pair_occlusion_windows",
    "parse_event_markers",
    "pose_jump_quantiles",
    "position_drift_mm",
    "position_hp_rms_mm",
    "python_processing_ms",
    "rotation_error_deg",
    "settling_time_ms",
    "translation_error_mm",
    "visible_response_ms",
]

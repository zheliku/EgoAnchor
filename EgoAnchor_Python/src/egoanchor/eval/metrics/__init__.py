"""EgoAnchor schema-v2 离线评估指标包级入口。"""

from .anchor_error import compute_anchor_error, summarize_anchor_error, summarize_pose_offset
from .common import (
    METRIC_GROUP_COLUMNS,
    angle_deg,
    highpass,
    is_pose_value,
    is_pose_vector,
    iter_metric_groups,
    mat_to_pos_quat,
    normalize_quat,
    pose_error,
    pos_quat_to_mat,
    project_point,
    quat_to_euler_deg,
    relative_rotation_quat,
    require_columns,
    slerp_lerp_resample,
    wrap_angle_360_deg,
)
from .diagnostics import ReliabilityDiagnosticsResult, compute_reliability_diagnostics
from .jitter import compute_static_metrics
from .latency import LatencyMetricsResult, compute_latency
from .pipeline import MetricsResult, compute_all_metrics
from .recovery import compute_occlusion_metrics, compute_transition_metrics

__all__ = [
    "LatencyMetricsResult",
    "METRIC_GROUP_COLUMNS",
    "MetricsResult",
    "ReliabilityDiagnosticsResult",
    "angle_deg",
    "compute_all_metrics",
    "compute_anchor_error",
    "compute_latency",
    "compute_occlusion_metrics",
    "compute_reliability_diagnostics",
    "compute_static_metrics",
    "compute_transition_metrics",
    "highpass",
    "is_pose_value",
    "is_pose_vector",
    "iter_metric_groups",
    "mat_to_pos_quat",
    "normalize_quat",
    "pose_error",
    "pos_quat_to_mat",
    "project_point",
    "quat_to_euler_deg",
    "relative_rotation_quat",
    "require_columns",
    "slerp_lerp_resample",
    "summarize_anchor_error",
    "summarize_pose_offset",
    "wrap_angle_360_deg",
]

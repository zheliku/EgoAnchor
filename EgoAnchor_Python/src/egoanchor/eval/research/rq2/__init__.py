"""RQ2 动态追踪分析的包级公共入口。"""

from .contract import REQUIRED_VARIANTS, RQ2_CONDITIONS, RQ2Config
from .model import compute_model_summary
from .paired import compute_paired_summary
from .pipeline import compute_operating_envelope, compute_trial_summary, run_rq2_analysis
from .qc import compute_design_audit, compute_session_audit, compute_trial_audit
from .smoothness import SMOOTHNESS_COLUMNS, compute_smoothness_summary
from .source import build_source_observations, compute_motion_delay
from .trajectory import annotate_active_motion

__all__ = [
    "REQUIRED_VARIANTS",
    "RQ2_CONDITIONS",
    "RQ2Config",
    "SMOOTHNESS_COLUMNS",
    "annotate_active_motion",
    "build_source_observations",
    "compute_model_summary",
    "compute_motion_delay",
    "compute_operating_envelope",
    "compute_smoothness_summary",
    "compute_paired_summary",
    "compute_design_audit",
    "compute_session_audit",
    "compute_trial_audit",
    "compute_trial_summary",
    "run_rq2_analysis",
]

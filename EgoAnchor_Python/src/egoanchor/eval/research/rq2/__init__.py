"""RQ2 动态锚定分析的包级公共入口。"""

from .contract import REQUIRED_VARIANTS, RQ2_CONDITIONS, RQ2Config
from .pipeline import compute_condition_summary, compute_trial_summary, run_rq2_analysis
from .plot import write_rq2_timelines
from .qc import compute_session_audit, compute_trial_audit
from .response import compute_response_summary
from .trajectory import annotate_active_motion, world_rotation_vectors_from_reference

__all__ = [
    "REQUIRED_VARIANTS",
    "RQ2_CONDITIONS",
    "RQ2Config",
    "annotate_active_motion",
    "compute_condition_summary",
    "compute_response_summary",
    "compute_session_audit",
    "compute_trial_audit",
    "compute_trial_summary",
    "run_rq2_analysis",
    "world_rotation_vectors_from_reference",
    "write_rq2_timelines",
]

"""RQ2 动态追踪分析入口。"""

from .core import (
    RQ2_CONDITIONS,
    build_source_observations,
    compute_model_summary,
    compute_motion_delay,
    compute_trial_summary,
    run_rq2_analysis,
)

__all__ = [
    "RQ2_CONDITIONS",
    "build_source_observations",
    "compute_model_summary",
    "compute_motion_delay",
    "compute_trial_summary",
    "run_rq2_analysis",
]

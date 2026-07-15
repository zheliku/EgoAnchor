"""实验一：端到端系统表征分析包级入口。"""

from .analysis import Exp1Result, run_exp1_system_characterization
from .contract import (
    DEFAULT_MIN_REFERENCE_COVERAGE,
    EXPERIMENT_ID,
    OUTPUT_FIGURES,
    OUTPUT_TABLES,
    SCENARIOS,
    VARIANTS,
)
from .figures import write_exp1_figures
from .latex import write_exp1_latex
from .metrics import (
    PAIR_COLUMNS,
    TRIAL_VALUE_COLUMNS,
    build_condition_summary,
    build_paired_trial_metrics,
    build_trial_metrics,
    compute_exp1_tables,
)
from .qc import Exp1QcReport, TRIAL_COLUMNS, build_trial_qc, require_exp1_qc, run_exp1_qc

__all__ = [
    "DEFAULT_MIN_REFERENCE_COVERAGE",
    "EXPERIMENT_ID",
    "OUTPUT_FIGURES",
    "OUTPUT_TABLES",
    "SCENARIOS",
    "VARIANTS",
    "Exp1QcReport",
    "Exp1Result",
    "PAIR_COLUMNS",
    "TRIAL_COLUMNS",
    "TRIAL_VALUE_COLUMNS",
    "build_condition_summary",
    "build_paired_trial_metrics",
    "build_trial_metrics",
    "build_trial_qc",
    "compute_exp1_tables",
    "require_exp1_qc",
    "run_exp1_qc",
    "run_exp1_system_characterization",
    "write_exp1_figures",
    "write_exp1_latex",
]

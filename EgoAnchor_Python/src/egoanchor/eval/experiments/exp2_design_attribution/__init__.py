"""实验二：设计归因与 VCD 风险覆盖分析。"""

from .analysis import Exp2Result, run_exp2_design_attribution
from .contract import (
    ABLATION_COMPONENT,
    ABLATION_METRIC_PREFIX,
    ABLATION_SCENARIO,
    ABLATION_VARIANTS,
    BASELINE_VARIANT,
    COMPONENT_KEYS,
    EXPERIMENT_ID,
    REQUIRED_VARIANTS,
    SOURCE_EXPERIMENT_ID,
    SOURCE_SCENARIOS,
    VariantContract,
    variant_contracts,
)
from .metrics import (
    PAIR_KEYS,
    aggregate_component_deltas,
    compute_exp2_paired_deltas,
    compute_paired_deltas,
)
from .figures import write_exp2_figures
from .latex import write_exp2_latex, write_exp2_tables
from .qc import Exp2QcReport, build_trial_qc, run_exp2_qc
from .risk_coverage import VcdRiskCoverageResult, compute_vcd_risk_coverage

__all__ = [
    "ABLATION_COMPONENT",
    "ABLATION_METRIC_PREFIX",
    "ABLATION_SCENARIO",
    "ABLATION_VARIANTS",
    "BASELINE_VARIANT",
    "COMPONENT_KEYS",
    "EXPERIMENT_ID",
    "PAIR_KEYS",
    "REQUIRED_VARIANTS",
    "SOURCE_EXPERIMENT_ID",
    "SOURCE_SCENARIOS",
    "VariantContract",
    "Exp2QcReport",
    "Exp2Result",
    "VcdRiskCoverageResult",
    "aggregate_component_deltas",
    "build_trial_qc",
    "compute_exp2_paired_deltas",
    "compute_paired_deltas",
    "compute_vcd_risk_coverage",
    "run_exp2_design_attribution",
    "run_exp2_qc",
    "variant_contracts",
    "write_exp2_figures",
    "write_exp2_latex",
    "write_exp2_tables",
]

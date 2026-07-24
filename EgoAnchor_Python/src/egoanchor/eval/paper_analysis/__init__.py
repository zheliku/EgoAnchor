"""实验一/二论文分析入口。"""

from .cache import cache_key, cache_path, load_task_results, write_task_results
from .figures import (
    build_dual_metric_panel,
    build_vcd_risk_coverage_panel,
    publish_figures,
    summarize_risk_coverage,
)
from .metrics import (
    HERMITE_INTERPOLATION_VARIANT,
    LINEAR_SLERP_VARIANT,
    SMOOTHED_EXTRAPOLATION_VARIANT,
    METHODS,
    PaperResults,
    PerformanceSamples,
    TaskResults,
    TEMPORAL_STRATEGY_VARIANTS,
    analyze_workbooks,
    analyze_task_workbook,
    eligible_trials,
    paired_metric_matrix,
    merge_task_results,
    risk_coverage_curve,
)
from .paper import (
    build_exp1_dynamic_table,
    build_exp1_static_table,
    build_exp2_attribution_table,
    write_analysis_artifacts,
)
from .pipeline import build_analysis
from .settings import PaperSettings, load_settings, settings_sha256
from .xlsx import iter_rows, workbook_sha256


__all__ = [
    "PaperResults",
    "PerformanceSamples",
    "TaskResults",
    "PaperSettings",
    "HERMITE_INTERPOLATION_VARIANT",
    "LINEAR_SLERP_VARIANT",
    "SMOOTHED_EXTRAPOLATION_VARIANT",
    "METHODS",
    "TEMPORAL_STRATEGY_VARIANTS",
    "analyze_workbooks",
    "analyze_task_workbook",
    "eligible_trials",
    "build_dual_metric_panel",
    "build_exp1_dynamic_table",
    "build_exp1_static_table",
    "build_exp2_attribution_table",
    "build_vcd_risk_coverage_panel",
    "build_analysis",
    "cache_key",
    "cache_path",
    "iter_rows",
    "load_settings",
    "load_task_results",
    "merge_task_results",
    "paired_metric_matrix",
    "risk_coverage_curve",
    "publish_figures",
    "settings_sha256",
    "summarize_risk_coverage",
    "workbook_sha256",
    "write_task_results",
    "write_analysis_artifacts",
]

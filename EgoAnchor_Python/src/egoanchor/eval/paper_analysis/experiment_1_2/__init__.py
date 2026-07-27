"""实验一端到端表征与实验二系统设计归因的共享分析入口。"""

from .cache import cache_key, cache_path, load_task_results, write_task_results
from .figures import (
    build_dual_metric_panel,
    build_temporal_strategy_panel,
    build_vcd_risk_coverage_panel,
    publish_figures,
    summarize_risk_coverage,
)
from .metrics import (
    HERMITE_INTERPOLATION_VARIANT,
    LINEAR_SLERP_VARIANT,
    METHODS,
    SMOOTHED_EXTRAPOLATION_VARIANT,
    TEMPORAL_STRATEGY_VARIANTS,
    PaperResults,
    PerformanceSamples,
    TaskResults,
    analyze_task_workbook,
    analyze_workbooks,
    eligible_trials,
    merge_task_results,
    paired_metric_matrix,
    risk_coverage_curve,
    rotation_lag_metrics,
    translation_lag_metrics,
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
    "HERMITE_INTERPOLATION_VARIANT",
    "LINEAR_SLERP_VARIANT",
    "METHODS",
    "PaperResults",
    "PaperSettings",
    "PerformanceSamples",
    "SMOOTHED_EXTRAPOLATION_VARIANT",
    "TEMPORAL_STRATEGY_VARIANTS",
    "TaskResults",
    "analyze_task_workbook",
    "analyze_workbooks",
    "build_analysis",
    "build_dual_metric_panel",
    "build_exp1_dynamic_table",
    "build_exp1_static_table",
    "build_exp2_attribution_table",
    "build_temporal_strategy_panel",
    "build_vcd_risk_coverage_panel",
    "cache_key",
    "cache_path",
    "eligible_trials",
    "iter_rows",
    "load_settings",
    "load_task_results",
    "merge_task_results",
    "paired_metric_matrix",
    "publish_figures",
    "risk_coverage_curve",
    "rotation_lag_metrics",
    "settings_sha256",
    "summarize_risk_coverage",
    "translation_lag_metrics",
    "workbook_sha256",
    "write_analysis_artifacts",
    "write_task_results",
]

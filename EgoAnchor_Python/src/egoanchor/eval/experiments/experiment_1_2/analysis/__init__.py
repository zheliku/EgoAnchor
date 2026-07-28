"""实验一/二论文统计、图表与工作簿读取的包级入口。"""

from .cache import (
    cache_key,
    cache_path,
    implementation_sha256,
    load_task_results,
    write_task_results,
)
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
from .xlsx import iter_rows, workbook_sha256


__all__ = [
    "HERMITE_INTERPOLATION_VARIANT",
    "LINEAR_SLERP_VARIANT",
    "METHODS",
    "PaperResults",
    "PerformanceSamples",
    "SMOOTHED_EXTRAPOLATION_VARIANT",
    "TEMPORAL_STRATEGY_VARIANTS",
    "TaskResults",
    "analyze_task_workbook",
    "analyze_workbooks",
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
    "implementation_sha256",
    "load_task_results",
    "merge_task_results",
    "paired_metric_matrix",
    "publish_figures",
    "risk_coverage_curve",
    "rotation_lag_metrics",
    "summarize_risk_coverage",
    "translation_lag_metrics",
    "workbook_sha256",
    "write_analysis_artifacts",
    "write_task_results",
]

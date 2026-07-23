"""实验一/二论文分析入口。"""

from .figures import (
    build_point_panel,
    build_translation_panel,
    build_vcd_risk_coverage_panel,
    publish_figures,
    summarize_risk_coverage,
)
from .metrics import (
    HERMITE_INTERPOLATION_VARIANT,
    SMOOTHED_EXTRAPOLATION_VARIANT,
    METHODS,
    PaperResults,
    TEMPORAL_STRATEGY_VARIANTS,
    analyze_workbooks,
    eligible_trials,
    paired_metric_matrix,
    risk_coverage_curve,
)
from .paper import write_paper
from .pipeline import build_paper
from .settings import PaperSettings, load_settings, settings_sha256
from .xlsx import iter_rows, workbook_sha256


__all__ = [
    "PaperResults",
    "PaperSettings",
    "HERMITE_INTERPOLATION_VARIANT",
    "SMOOTHED_EXTRAPOLATION_VARIANT",
    "METHODS",
    "TEMPORAL_STRATEGY_VARIANTS",
    "analyze_workbooks",
    "eligible_trials",
    "build_point_panel",
    "build_translation_panel",
    "build_vcd_risk_coverage_panel",
    "build_paper",
    "iter_rows",
    "load_settings",
    "paired_metric_matrix",
    "risk_coverage_curve",
    "publish_figures",
    "settings_sha256",
    "summarize_risk_coverage",
    "workbook_sha256",
    "write_paper",
]

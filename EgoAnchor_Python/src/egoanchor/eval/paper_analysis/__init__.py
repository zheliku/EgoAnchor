"""实验一/二论文分析入口。"""

from .figures import build_point_panel, build_translation_panel, publish_figures
from .metrics import (
    CAUSAL_PREDICTION_VARIANT,
    METHODS,
    PaperResults,
    TEMPORAL_STRATEGY_VARIANTS,
    analyze_workbooks,
    paired_metric_matrix,
)
from .paper import write_paper
from .pipeline import build_paper
from .settings import PaperSettings, load_settings, settings_sha256
from .xlsx import iter_rows, workbook_sha256


__all__ = [
    "PaperResults",
    "PaperSettings",
    "CAUSAL_PREDICTION_VARIANT",
    "METHODS",
    "TEMPORAL_STRATEGY_VARIANTS",
    "analyze_workbooks",
    "build_point_panel",
    "build_translation_panel",
    "build_paper",
    "iter_rows",
    "load_settings",
    "paired_metric_matrix",
    "publish_figures",
    "settings_sha256",
    "workbook_sha256",
    "write_paper",
]

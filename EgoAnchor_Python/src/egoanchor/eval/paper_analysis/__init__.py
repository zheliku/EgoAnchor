"""实验一/二论文分析入口。"""

from .figures import build_point_panel, build_translation_panel, publish_figures
from .metrics import (
    HERMITE_VARIANT,
    METHODS,
    PaperResults,
    analyze_workbooks,
    paired_metric_matrix,
)
from .paper import write_paper
from .pipeline import build_paper
from .settings import PaperSettings, load_settings
from .xlsx import iter_rows, workbook_sha256


__all__ = [
    "PaperResults",
    "PaperSettings",
    "HERMITE_VARIANT",
    "METHODS",
    "analyze_workbooks",
    "build_point_panel",
    "build_translation_panel",
    "build_paper",
    "iter_rows",
    "load_settings",
    "paired_metric_matrix",
    "publish_figures",
    "workbook_sha256",
    "write_paper",
]

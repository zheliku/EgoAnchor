"""GPT 网页版 corrected-newdata-v4 分析与论文复刻入口。"""

from .figures import build_point_panel, build_translation_panel, publish_figures
from .metrics import (
    HERMITE_VARIANT,
    METHODS,
    GptV4Results,
    analyze_workbooks,
    paired_metric_matrix,
)
from .paper import write_paper
from .pipeline import build_paper
from .settings import GptV4Settings, load_settings
from .temporal_replay import (
    HERMITE,
    PREDICT_TO_NOW,
    TemporalReplaySettings,
    publish_temporal_replay_figure,
    run_temporal_replay,
    temporal_replay_summary,
)
from .xlsx import iter_rows, workbook_sha256


__all__ = [
    "GptV4Results",
    "GptV4Settings",
    "HERMITE",
    "HERMITE_VARIANT",
    "METHODS",
    "PREDICT_TO_NOW",
    "TemporalReplaySettings",
    "analyze_workbooks",
    "build_point_panel",
    "build_translation_panel",
    "build_paper",
    "iter_rows",
    "load_settings",
    "paired_metric_matrix",
    "publish_figures",
    "publish_temporal_replay_figure",
    "run_temporal_replay",
    "temporal_replay_summary",
    "workbook_sha256",
    "write_paper",
]

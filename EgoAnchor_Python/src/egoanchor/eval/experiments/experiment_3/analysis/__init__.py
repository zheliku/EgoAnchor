"""实验三读取、计分、统计、结果工作簿与论文图的包级入口。"""

from .artifacts import EXP3_ARTIFACTS
from .contracts import (
    BLOCK_ITEMS,
    BLOCK_RECORD_COLUMNS,
    EGOANCHOR,
    EXCLUSION_REASONS,
    MAIN_FAMILY,
    MINIMUM_PARTICIPANTS,
    METHOD_RECORD_COLUMNS,
    METHODS,
    OBJECT_LABELS,
    OBJECTS,
    OUTCOME_LABELS,
    PARTICIPANT_CATEGORIES,
    PRIMARY_OUTCOMES,
    REVERSED_TIA_ITEMS,
    SCALE_FAMILY,
    SCALE_OUTCOMES,
    WORKBOOK_CONTRACT_ID,
    WORKBOOK_SOURCE_CATEGORY,
    AnalysisTables,
    Exp3Data,
    ScoreData,
    TARGET_PARTICIPANTS,
    aq_scale_items,
    published_scale_items,
    required_block_items,
)
from .figures import publish_figures
from .inference import holm_adjust, paired_result, signed_rank_test
from .paper import write_subjective_table
from .pipeline import build_analysis, validate_complete_pair_counts
from .reader import describe_workbook, read_workbook, validate_for_analysis
from .scoring import derive_scores
from .settings import AnalysisSettings, SettingsSnapshot, load_settings, load_settings_snapshot
from .source_gate import SourceGateStatus
from .summaries import analyze_scores
from .workbook import (
    CHOICES_SHEET,
    INFO_SHEET,
    OBJECT_RESULTS_SHEET,
    RELIABILITY_SHEET,
    RESULTS_SHEET,
    SAMPLE_QC_SHEET,
    write_results_workbook,
)


__all__ = [
    "AnalysisSettings",
    "AnalysisTables",
    "BLOCK_ITEMS",
    "BLOCK_RECORD_COLUMNS",
    "CHOICES_SHEET",
    "EGOANCHOR",
    "EXP3_ARTIFACTS",
    "EXCLUSION_REASONS",
    "Exp3Data",
    "INFO_SHEET",
    "MAIN_FAMILY",
    "MINIMUM_PARTICIPANTS",
    "METHODS",
    "METHOD_RECORD_COLUMNS",
    "OBJECT_LABELS",
    "OBJECTS",
    "OBJECT_RESULTS_SHEET",
    "OUTCOME_LABELS",
    "PARTICIPANT_CATEGORIES",
    "PRIMARY_OUTCOMES",
    "RELIABILITY_SHEET",
    "RESULTS_SHEET",
    "REVERSED_TIA_ITEMS",
    "SCALE_FAMILY",
    "SCALE_OUTCOMES",
    "SAMPLE_QC_SHEET",
    "ScoreData",
    "SettingsSnapshot",
    "SourceGateStatus",
    "TARGET_PARTICIPANTS",
    "WORKBOOK_CONTRACT_ID",
    "WORKBOOK_SOURCE_CATEGORY",
    "analyze_scores",
    "aq_scale_items",
    "build_analysis",
    "derive_scores",
    "describe_workbook",
    "holm_adjust",
    "load_settings",
    "load_settings_snapshot",
    "paired_result",
    "publish_figures",
    "published_scale_items",
    "read_workbook",
    "required_block_items",
    "signed_rank_test",
    "validate_complete_pair_counts",
    "validate_for_analysis",
    "write_results_workbook",
    "write_subjective_table",
]

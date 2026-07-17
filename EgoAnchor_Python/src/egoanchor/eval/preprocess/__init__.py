"""Stage 1 原始 schema-v2 日志解析与硬 QC 的包级入口。"""

from .qc import (
    FORMAL_VARIANTS,
    QcIssue,
    StageOneQcReport,
    aggregate_config_hash,
    run_task_qc,
    variant_config_hash,
)
from .reader import (
    EXPECTED_EVENTS,
    JSON_DOCUMENT_FILES,
    JSONL_TABLE_FILES,
    REQUIRED_FILE_NAMES,
    ROW_TYPES,
    NormalizedValue,
    SourceFileInfo,
    SourceRow,
    TaskDataset,
    flatten_json,
    iter_jsonl,
    read_json_document,
    read_task,
    source_file_info,
)

__all__ = [
    "EXPECTED_EVENTS",
    "JSON_DOCUMENT_FILES",
    "FORMAL_VARIANTS",
    "JSONL_TABLE_FILES",
    "REQUIRED_FILE_NAMES",
    "ROW_TYPES",
    "NormalizedValue",
    "QcIssue",
    "SourceFileInfo",
    "SourceRow",
    "StageOneQcReport",
    "TaskDataset",
    "aggregate_config_hash",
    "flatten_json",
    "iter_jsonl",
    "read_json_document",
    "read_task",
    "run_task_qc",
    "source_file_info",
    "variant_config_hash",
]

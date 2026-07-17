"""EgoAnchor formal evaluation schema-v2 数据行、写入器和固定路径。"""

from .paths import EvalV2Paths
from .rows import (
    EventRow,
    LEGACY_FIELD_PREFIXES,
    ManifestV2,
    PythonCandidateRow,
    SCHEMA_VERSION,
    SchemaV2Error,
    UnityAdmissionRow,
    UnityReferenceRow,
    UnityRenderRow,
    validate_schema_mapping,
)
from .writers import JsonlTableWriter

__all__ = [
    "EvalV2Paths",
    "EventRow",
    "JsonlTableWriter",
    "LEGACY_FIELD_PREFIXES",
    "ManifestV2",
    "PythonCandidateRow",
    "SCHEMA_VERSION",
    "SchemaV2Error",
    "UnityAdmissionRow",
    "UnityReferenceRow",
    "UnityRenderRow",
    "validate_schema_mapping",
]

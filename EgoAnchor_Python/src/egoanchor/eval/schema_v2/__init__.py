"""EgoAnchor formal evaluation schema v2 package."""

from .paths import EvalV2Paths
from .qc import SchemaQcReport, run_schema_qc
from .readers import (
    EvalSessionV2,
    join_candidate_admission,
    join_render_reference,
    load_session_v2,
    select_trials,
)
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
    "EvalSessionV2",
    "EvalV2Paths",
    "EventRow",
    "JsonlTableWriter",
    "LEGACY_FIELD_PREFIXES",
    "ManifestV2",
    "PythonCandidateRow",
    "SCHEMA_VERSION",
    "SchemaQcReport",
    "SchemaV2Error",
    "UnityAdmissionRow",
    "UnityReferenceRow",
    "UnityRenderRow",
    "load_session_v2",
    "join_candidate_admission",
    "join_render_reference",
    "run_schema_qc",
    "select_trials",
    "validate_schema_mapping",
]

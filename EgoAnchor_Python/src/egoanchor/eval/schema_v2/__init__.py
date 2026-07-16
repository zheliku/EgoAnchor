"""EgoAnchor formal evaluation schema v2 package."""

from .paths import EvalV2Paths
from .qc import FORMAL_VARIANTS, SchemaQcReport, aggregate_config_hash, run_schema_qc
from .readers import (
    EvalSessionV2,
    accepted_trial_keys,
    accepted_trial_table,
    join_candidate_admission,
    join_render_reference,
    load_session_v2,
    merge_event_fragments,
    select_completed_trials,
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
    "accepted_trial_keys",
    "accepted_trial_table",
    "EvalV2Paths",
    "EventRow",
    "FORMAL_VARIANTS",
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
    "aggregate_config_hash",
    "load_session_v2",
    "merge_event_fragments",
    "join_candidate_admission",
    "join_render_reference",
    "run_schema_qc",
    "select_completed_trials",
    "select_trials",
    "validate_schema_mapping",
]

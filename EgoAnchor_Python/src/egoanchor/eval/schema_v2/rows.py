"""schema-v2 行对象与公共校验。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar, Mapping


SCHEMA_VERSION = 2
"""当前唯一支持的评估 schema 版本。"""

LEGACY_FIELD_PREFIXES = ("rq1_", "rq2_")
"""禁止重新进入正式 schema 的旧实验字段前缀。"""


class SchemaV2Error(ValueError):
    """schema-v2 文件、字段或跨表约束不满足时抛出的错误。"""


@dataclass(frozen=True, kw_only=True)
class ManifestV2:
    """跨端最终汇总的 schema-v2 session 清单。"""

    schema_version: int = SCHEMA_VERSION
    session_id: str = ""
    object_id: str = ""
    run_kind: str = "formal"
    experiment_ids: list[str] = field(default_factory=list)
    operator_id: str = ""
    created_unix_ms: float = 0.0
    unity_run_mode: str = ""
    python_host: str = ""
    unity_version: str = ""
    python_version: str = ""
    egoanchor_git_commit: str = ""
    protocol_version: str = ""
    config_hash: str = ""
    frozen_parameter_set_id: str = ""
    object_model_id: str = ""
    variant_definitions: list[dict[str, Any]] = field(default_factory=list)
    completed_tasks: list[dict[str, Any]] = field(default_factory=list)
    trial_plan: list[dict[str, Any]] = field(default_factory=list)
    log_files: dict[str, str] = field(default_factory=dict)
    log_writer_stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为可直接写入 JSON 的字典并执行公共校验。"""

        row = asdict(self)
        validate_schema_mapping(row)
        return row


@dataclass(frozen=True, kw_only=True)
class _SchemaRow:
    """所有 JSONL 行共享的版本、事件和 session 字段。"""

    EVENT: ClassVar[str] = ""

    schema_version: int = SCHEMA_VERSION
    event: str = ""
    session_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        """转换为字典，并校验版本、事件和旧字段。"""

        row = asdict(self)
        row["event"] = self.event or self.EVENT
        validate_schema_mapping(row, expected_event=self.EVENT)
        return row


@dataclass(frozen=True, kw_only=True)
class PythonCandidateRow(_SchemaRow):
    """Python 输出的一条 camera-space pose candidate 或失败 candidate。"""

    EVENT: ClassVar[str] = "python_candidate"

    frame_id: int = 0
    candidate_id: str = ""
    server_receive_mono_ms: float = 0.0
    server_publish_mono_ms: float = 0.0
    has_pose: bool = False
    pose_matrix_cv_camera: list[float] | None = None
    pose_tx_m: float | None = None
    pose_ty_m: float | None = None
    pose_tz_m: float | None = None
    pose_qx: float | None = None
    pose_qy: float | None = None
    pose_qz: float | None = None
    pose_qw: float | None = None
    pose_source: str = ""
    phase: str = ""
    stage: int = 0
    failure_reason: str = ""
    reliability_flags: list[str] = field(default_factory=list)
    vcd_score: float | None = None
    visibility_score: float | None = None
    geometry_core_score: float | None = None
    color_projection_score: float | None = None
    depth_alignment_score: float | None = None
    depth_abs_score: float | None = None
    depth_struct_score: float | None = None
    depth_alpha: float | None = None
    render_diagnostics: dict[str, Any] = field(default_factory=dict)
    total_ms: float = 0.0
    yolo_ms: float = 0.0
    depth_ms: float = 0.0
    cutie_ms: float = 0.0
    pose_ms: float = 0.0


@dataclass(frozen=True, kw_only=True)
class UnityReferenceRow(_SchemaRow):
    """Unity 图像发送链路的一帧采集时刻平台参考。"""

    EVENT: ClassVar[str] = "unity_reference"

    frame_id: int = 0
    capture_mono_ms: float = 0.0
    capture_unix_ms: float = 0.0
    capture_unity_frame: int = 0
    sender_mono_ms: float = 0.0
    sender_unity_frame: int = 0
    image_time_basis: str = "camera_pose_history_proxy"
    image_time_offset_frames: int = 0
    publish_attempt_mono_ms: float = 0.0
    publish_succeeded: bool = False
    head_pos: list[float] | None = None
    head_rot: list[float] | None = None
    cam_valid: bool = False
    camera_reference: str = ""
    cam_pos: list[float] | None = None
    cam_rot: list[float] | None = None
    reference_pose_valid: bool = False
    reference_pose_source: str = ""
    reference_pose_fresh: bool = False
    reference_pose_keep_alive: bool = False
    reference_pose_fresh_age_ms: float | None = None
    reference_pos: list[float] | None = None
    reference_rot: list[float] | None = None


@dataclass(frozen=True, kw_only=True)
class UnityAdmissionRow(_SchemaRow):
    """一条 candidate 在一个 runtime variant 中的接纳结果。"""

    EVENT: ClassVar[str] = "unity_admission"

    candidate_id: str = ""
    frame_id: int = 0
    variant_id: str = ""
    variant_label: str = ""
    experiment_id: str = ""
    scenario_id: str = ""
    trial_id: str = ""
    event_id: str = ""
    condition_id: str = ""
    unity_pose_handle_mono_ms: float | None = None
    unity_frame: int = 0
    world_alignment_mode: str = ""
    uses_capture_time_alignment: bool = False
    source_capture_mono_ms: float | None = None
    source_capture_unity_frame: int = -1
    has_aligned_raw: bool = False
    aligned_raw_pos: list[float] | None = None
    aligned_raw_rot: list[float] | None = None
    has_arrival_time_raw: bool = False
    arrival_time_raw_pos: list[float] | None = None
    arrival_time_raw_rot: list[float] | None = None
    arrival_time_raw_mono_ms: float | None = None
    uses_vcd_admission: bool = False
    vcd_score: float | None = None
    quality_gate: str = ""
    admission_decision: str = ""
    policy_action: str = ""
    policy_reason: str = ""
    anchor_state: str = ""
    motion_model: str = ""
    smoothing_strategy: str = ""
    uses_temporal_synthesis: bool = False
    uses_static_lock: bool = False
    config_hash: str = ""


@dataclass(frozen=True, kw_only=True)
class UnityRenderRow(_SchemaRow):
    """一个 render tick 中一个 runtime variant 的实际输出与显示状态。"""

    EVENT: ClassVar[str] = "unity_render"

    render_tick_id: int = 0
    render_mono_ms: float = 0.0
    render_unix_ms: float = 0.0
    render_unity_frame: int = 0
    variant_id: str = ""
    variant_label: str = ""
    experiment_id: str = ""
    scenario_id: str = ""
    trial_id: str = ""
    event_id: str = ""
    condition_id: str = ""
    head_pos: list[float] | None = None
    head_rot: list[float] | None = None
    reference_pose_valid: bool = False
    reference_pose_source: str = ""
    reference_pose_fresh: bool = False
    reference_pose_keep_alive: bool = False
    reference_pose_fresh_age_ms: float | None = None
    reference_pos: list[float] | None = None
    reference_rot: list[float] | None = None
    reference_linear_speed_m_s: float = 0.0
    reference_angular_speed_deg_s: float = 0.0
    source_frame_id: int = 0
    has_output_pose: bool = False
    output_pos: list[float] | None = None
    output_rot: list[float] | None = None
    has_display_pose: bool = False
    display_pos: list[float] | None = None
    display_rot: list[float] | None = None
    anchor_state: str = ""
    policy_action: str = ""
    policy_reason: str = ""
    observation_age_ms: float | None = None
    policy_output_target_mono_ms: float | None = None
    smoothing_delay_ms: float | None = None
    latest_static_locked: bool = False
    latest_accepted_score: float | None = None
    quality_gate: str = ""
    motion_model: str = ""
    smoothing_strategy: str = ""
    config_hash: str = ""


@dataclass(frozen=True, kw_only=True)
class EventRow(_SchemaRow):
    """session、runtime 或人工事件标记。"""

    event_type: str = ""
    source: str = ""
    created_unix_ms: float = 0.0
    mono_ms: float = 0.0
    unity_frame: int = -1
    severity: str = "info"
    experiment_id: str = ""
    scenario_id: str = ""
    trial_id: str = ""
    event_id: str = ""
    variant_id: str = ""
    message: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


def validate_schema_mapping(row: Mapping[str, Any], *, expected_event: str | None = None) -> None:
    """校验版本、事件类型，并递归拒绝旧 RQ 字段。"""

    version = row.get("schema_version")
    if version != SCHEMA_VERSION:
        raise SchemaV2Error(f"schema_version must be {SCHEMA_VERSION}, got {version!r}")
    if expected_event and row.get("event") != expected_event:
        raise SchemaV2Error(f"event must be {expected_event!r}, got {row.get('event')!r}")
    legacy_fields = sorted(_find_legacy_fields(row))
    if legacy_fields:
        raise SchemaV2Error(f"schema-v2 forbids legacy fields: {', '.join(legacy_fields)}")


def _find_legacy_fields(value: Any, *, prefix: str = "") -> set[str]:
    """递归收集 mapping/list 中的旧字段路径。"""

    found: set[str] = set()
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key)
            path = f"{prefix}.{key}" if prefix else key
            if key.lower().startswith(LEGACY_FIELD_PREFIXES):
                found.add(path)
            found.update(_find_legacy_fields(item, prefix=path))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found.update(_find_legacy_fields(item, prefix=f"{prefix}[{index}]"))
    return found


__all__ = [
    "EventRow",
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

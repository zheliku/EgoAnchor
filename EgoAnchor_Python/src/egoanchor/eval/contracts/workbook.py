"""Stage 1 workbook 与 Stage 2 CSV 的结构化数据契约。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Iterable


DATA_TYPES = ("text", "int", "float", "bool", "datetime", "json")
"""契约允许的逻辑数据类型；写 XLSX 时由 writer 映射到具体单元格类型。"""


@dataclass(frozen=True, slots=True)
class ColumnContract:
    """描述一个 sheet 或 CSV 表的列语义。"""

    name: str
    """稳定机器列名。"""

    dtype: str
    """逻辑数据类型。"""

    unit: str = ""
    """物理单位；无量纲时为空字符串。"""

    nullable: bool = True
    """是否允许空值。"""

    source_path: str = ""
    """原始 JSON path 或上一阶段字段来源。"""

    description: str = ""
    """中文字段说明。"""

    def __post_init__(self) -> None:
        """校验列名、类型和单位字段的基本契约。"""

        if self.dtype not in DATA_TYPES:
            raise ValueError(f"不支持的契约数据类型：{self.dtype}")
        if not self.name or self.name.strip() != self.name:
            raise ValueError("列名必须是非空且不含首尾空格的稳定标识符")

    def to_dict(self) -> dict[str, Any]:
        """返回可序列化的列记录。"""

        return asdict(self)


@dataclass(frozen=True, slots=True)
class ForeignKeyContract:
    """描述一个跨 sheet 或跨 CSV 表的稳定外键。"""

    columns: tuple[str, ...]
    """当前表参与连接的列。"""

    ref_sheet: str
    """被引用的 sheet 或 CSV 表名。"""

    ref_columns: tuple[str, ...]
    """被引用表的主键列。"""

    def __post_init__(self) -> None:
        """确保外键两侧列数一致。"""

        if not self.columns or len(self.columns) != len(self.ref_columns):
            raise ValueError("外键列与被引用列必须非空且长度一致")

    def to_dict(self) -> dict[str, Any]:
        """返回可序列化的外键记录。"""

        return asdict(self)


@dataclass(frozen=True, slots=True)
class SheetContract:
    """描述一个完整 XLSX sheet 的粒度、字段和键约束。"""

    name: str
    """稳定 sheet 名称。"""

    grain: str
    """一行代表的事实粒度。"""

    primary_key: tuple[str, ...]
    """唯一主键列顺序。"""

    columns: tuple[ColumnContract, ...]
    """全部列定义，顺序即 workbook 写出顺序。"""

    foreign_keys: tuple[ForeignKeyContract, ...] = ()
    """当前 sheet 的外键定义。"""

    def __post_init__(self) -> None:
        """校验主键存在且列名没有重复。"""

        names = self.column_names()
        if not self.name or not self.grain or not self.primary_key:
            raise ValueError("sheet 名称、粒度和主键不能为空")
        if len(names) != len(set(names)):
            raise ValueError(f"sheet 列名重复：{self.name}")
        missing = set(self.primary_key) - set(names)
        if missing:
            raise ValueError(f"sheet 主键列不存在：{self.name}: {sorted(missing)}")
        for foreign_key in self.foreign_keys:
            missing_foreign_key = set(foreign_key.columns) - set(names)
            if missing_foreign_key:
                raise ValueError(
                    f"sheet 外键列不存在：{self.name}: {sorted(missing_foreign_key)}"
                )

    def column_names(self) -> tuple[str, ...]:
        """返回当前 sheet 的稳定列名顺序。"""

        return tuple(column.name for column in self.columns)

    def to_dict(self) -> dict[str, Any]:
        """返回可序列化的 sheet 契约。"""

        return {
            "name": self.name,
            "grain": self.grain,
            "primary_key": list(self.primary_key),
            "columns": [column.to_dict() for column in self.columns],
            "foreign_keys": [foreign_key.to_dict() for foreign_key in self.foreign_keys],
        }


@dataclass(frozen=True, slots=True)
class CsvTableContract:
    """描述 Stage 2 发布的一个 CSV 长表或窄表。"""

    name: str
    """稳定输出文件的逻辑名称，不含扩展名。"""

    grain: str
    """一行代表的统计粒度。"""

    primary_key: tuple[str, ...]
    """结果表稳定主键。"""

    columns: tuple[ColumnContract, ...]
    """结果表列定义。"""

    def column_names(self) -> tuple[str, ...]:
        """返回 CSV 列名顺序。"""

        return tuple(column.name for column in self.columns)

    def to_dict(self) -> dict[str, Any]:
        """返回可序列化的 CSV 契约。"""

        return {
            "name": self.name,
            "grain": self.grain,
            "primary_key": list(self.primary_key),
            "columns": [column.to_dict() for column in self.columns],
        }


def _column(name: str, dtype: str = "text", **kwargs: Any) -> ColumnContract:
    """用简短参数构造列定义，集中校验逻辑数据类型。"""

    kwargs.setdefault("source_path", name)
    kwargs.setdefault("description", f"{name} 的稳定字段。")
    return ColumnContract(name=name, dtype=dtype, **kwargs)


def _source_columns() -> tuple[ColumnContract, ...]:
    """返回所有事实表共享的来源追踪列。"""

    return (
        _column("source_file", source_path="source_file"),
        _column("source_line", "int", source_path="source_line"),
        _column("source_row_sha256", source_path="source_row_sha256"),
    )


def _vector_columns(
    output_prefix: str,
    source_path: str,
    suffixes: tuple[str, ...],
    *,
    unit: str = "",
) -> tuple[ColumnContract, ...]:
    """把定长向量声明为独立标量列，禁止写入 JSON 数组单元格。"""

    return tuple(
        _column(
            f"{output_prefix}_{suffix}",
            "float",
            unit=unit,
            source_path=f"{source_path}[{index}]",
            description=f"{source_path} 的 {suffix} 分量。",
        )
        for index, suffix in enumerate(suffixes)
    )


def _sheet(
    name: str,
    grain: str,
    primary_key: tuple[str, ...],
    columns: Iterable[ColumnContract],
    foreign_keys: tuple[ForeignKeyContract, ...] = (),
) -> SheetContract:
    """构造并返回一个 sheet 契约。"""

    primary_key_set = set(primary_key)
    normalized_columns = tuple(
        replace(column, nullable=False) if column.name in primary_key_set else column
        for column in columns
    )
    return SheetContract(name, grain, primary_key, normalized_columns, foreign_keys)


_SESSION_FK = ForeignKeyContract(("session_id",), "manifest", ("session_id",))
"""所有 session 事实表共享的 manifest 外键。"""

_CANDIDATE_FK = ForeignKeyContract(
    ("session_id", "candidate_id"),
    "python_candidates",
    ("session_id", "candidate_id"),
)
"""candidate 子表与 admission 使用的候选外键。"""

_VARIANT_FK = ForeignKeyContract(
    ("session_id", "variant_id"),
    "variants",
    ("session_id", "variant_id"),
)
"""admission 和 render 使用的 runtime variant 外键。"""

_EVENT_FK = ForeignKeyContract(("event_row_id",), "events", ("event_row_id",))
"""事件 payload 和完成 trial 使用的合并事件外键。"""

_SOURCE_ID_COLUMNS = (
    _column("schema_version", "int"),
    _column("event"),
    _column("session_id", source_path="session_id"),
)
"""schema-v2 事实表共享的版本、事件和 session 列。"""

_CONTEXT_COLUMNS = (
    _column("experiment_id"),
    _column("scenario_id"),
    _column("trial_id"),
    _column("event_id"),
    _column("condition_id"),
    _column("variant_id"),
)
"""Unity admission/render 共享的分析上下文列。"""

_NORMALIZED_VALUE_COLUMNS = (
    _column("json_path"),
    _column("value_type"),
    _column("value_json"),
    _column("value_storage"),
    _column("value_sha256"),
)
"""规范化 JSON 值和超长值引用使用的公共列。"""

_EVENT_COLUMNS = (
    _column("event_row_id"),
    _column("schema_version", "int"),
    _column("event"),
    _column("event_type"),
    _column("session_id"),
    _column("source"),
    _column("created_unix_ms", "float", unit="ms"),
    _column("mono_ms", "float", unit="ms"),
    _column("unity_frame", "int"),
    _column("severity"),
    _column("experiment_id"),
    _column("scenario_id"),
    _column("trial_id"),
    _column("event_id"),
    _column("variant_id"),
    _column("message"),
) + _source_columns()
"""三个事件事实表共享的完整标量列。"""


SHEET_CONTRACTS = (
    _sheet("README", "document", ("section",), (_column("section"), _column("content"))),
    _sheet(
        "provenance",
        "workbook",
        ("workbook_id",),
        (
            _column("workbook_id"),
            _column("session_id"),
            _column("source_directory"),
            _column("schema_version", "int"),
            _column("workbook_contract_version", "int"),
            _column("config_hash"),
            _column("code_version"),
            _column("generated_at_utc", "datetime"),
            _column("input_sha256"),
            _column("source_set_sha256"),
        ),
        (_SESSION_FK,),
    ),
    _sheet(
        "source_files",
        "source file",
        ("relative_path",),
        (
            _column("relative_path"),
            _column("source_kind"),
            _column("exists", "bool"),
            _column("byte_count", "int"),
            _column("row_count", "int"),
            _column("sha256"),
        ),
    ),
    _sheet(
        "manifest",
        "session",
        ("session_id",),
        (
            _column("session_id"),
            _column("schema_version", "int"),
            _column("object_id"),
            _column("run_kind"),
            _column("protocol_version"),
            _column("config_hash"),
            _column("frozen_parameter_set_id"),
            _column("object_model_id"),
            _column("source_file"),
            _column("source_row_sha256"),
        ),
    ),
    _sheet(
        "metadata_kv",
        "document plus JSON path",
        ("document", "json_path"),
        (
            _column("document"),
            _column("session_id"),
        )
        + _NORMALIZED_VALUE_COLUMNS
        + _source_columns(),
        (_SESSION_FK,),
    ),
    _sheet(
        "variants",
        "session plus variant",
        ("session_id", "variant_id"),
        (
            _column("session_id"),
            _column("variant_id"),
            _column("variant_label"),
            _column("world_alignment_mode"),
            _column("config_hash"),
            _column("uses_capture_time_alignment", "bool"),
            _column("uses_vcd_admission", "bool"),
            _column("uses_temporal_synthesis", "bool"),
            _column("uses_static_lock", "bool"),
            _column("uses_low_score_reacquire", "bool"),
            _column("uses_server_reacquire", "bool"),
            _column("quality_gate"),
            _column("motion_model"),
            _column("smoothing_strategy"),
            _column("source_file"),
            _column("source_row_sha256"),
        ),
        (_SESSION_FK,),
    ),
    _sheet(
        "trial_plan",
        "session plus task",
        ("session_id", "task_number"),
        (
            _column("session_id"),
            _column("task_number", "int"),
            _column("experiment_id"),
            _column("scenario_id"),
            _column("condition_id"),
            _column("task_label"),
            _column("task_description"),
            _column("source_file"),
            _column("source_row_sha256"),
        ),
        (_SESSION_FK,),
    ),
    _sheet(
        "completed_trials",
        "completed trial",
        ("session_id", "experiment_id", "scenario_id", "trial_id"),
        (
            _column("session_id"),
            _column("experiment_id"),
            _column("scenario_id"),
            _column("trial_id"),
            _column("event_id"),
            _column("condition_id"),
            _column("event_row_id"),
        )
        + _source_columns(),
        (_SESSION_FK, _EVENT_FK),
    ),
    _sheet(
        "writer_stats",
        "session plus file",
        ("session_id", "file_name"),
        (
            _column("session_id"),
            _column("file_name"),
            _column("writer_state"),
            _column("rows_written", "int"),
            _column("dropped_rows", "int"),
            _column("log_write_failures", "int"),
            _column("stats_pending", "bool"),
            _column("stats_source"),
            _column("source_file"),
            _column("source_row_sha256"),
        ),
        (_SESSION_FK,),
    ),
    _sheet(
        "python_candidates",
        "session plus candidate",
        ("session_id", "candidate_id"),
        _SOURCE_ID_COLUMNS
        + (
            _column("frame_id", "int"),
            _column("candidate_id"),
            _column("server_receive_mono_ms", "float", unit="ms"),
            _column("server_publish_mono_ms", "float", unit="ms"),
            _column("has_pose", "bool"),
            _column("pose_tx_m", "float", unit="m"),
            _column("pose_ty_m", "float", unit="m"),
            _column("pose_tz_m", "float", unit="m"),
            _column("pose_qx", "float"),
            _column("pose_qy", "float"),
            _column("pose_qz", "float"),
            _column("pose_qw", "float"),
        )
        + tuple(
            _column(
                f"pose_matrix_{row}{column}",
                "float",
                source_path=f"pose_matrix_cv_camera[{row * 4 + column}]",
                description=f"camera-space pose 矩阵第 {row + 1} 行第 {column + 1} 列。",
            )
            for row in range(4)
            for column in range(4)
        )
        + (
            _column("pose_source"),
            _column("phase"),
            _column("stage", "int"),
            _column("failure_reason"),
            _column("vcd_score", "float"),
            _column("visibility_score", "float"),
            _column("geometry_core_score", "float"),
            _column("color_projection_score", "float"),
            _column("depth_alignment_score", "float"),
            _column("depth_abs_score", "float"),
            _column("depth_struct_score", "float"),
            _column("depth_alpha", "float"),
            _column("total_ms", "float", unit="ms"),
            _column("yolo_ms", "float", unit="ms"),
            _column("depth_ms", "float", unit="ms"),
            _column("cutie_ms", "float", unit="ms"),
            _column("pose_ms", "float", unit="ms"),
        )
        + _source_columns(),
        (_SESSION_FK,),
    ),
    _sheet(
        "candidate_flags",
        "candidate plus flag",
        ("session_id", "candidate_id", "flag_index"),
        (
            _column("session_id"),
            _column("candidate_id"),
            _column("flag_index", "int"),
            _column("flag"),
        )
        + _source_columns(),
        (_CANDIDATE_FK,),
    ),
    _sheet(
        "candidate_diag",
        "candidate plus JSON path",
        ("session_id", "candidate_id", "json_path"),
        (
            _column("session_id"),
            _column("candidate_id"),
        )
        + _NORMALIZED_VALUE_COLUMNS
        + _source_columns(),
        (_CANDIDATE_FK,),
    ),
    _sheet(
        "unity_reference",
        "session plus frame",
        ("session_id", "frame_id"),
        _SOURCE_ID_COLUMNS
        + (
            _column("frame_id", "int"),
            _column("capture_mono_ms", "float", unit="ms"),
            _column("capture_unix_ms", "float", unit="ms"),
            _column("capture_unity_frame", "int"),
            _column("capture_local"),
            _column("capture_utc"),
            _column("sender_mono_ms", "float", unit="ms"),
            _column("sender_unity_frame", "int"),
            _column("image_time_basis"),
            _column("image_time_offset_frames", "int"),
            _column("publish_attempt_mono_ms", "float", unit="ms"),
            _column("publish_succeeded", "bool"),
        )
        + _vector_columns("head_pos", "head_pos", ("x_m", "y_m", "z_m"), unit="m")
        + _vector_columns("head_rot", "head_rot", ("x", "y", "z", "w"))
        + _vector_columns("head_euler_deg", "head_euler_deg", ("x", "y", "z"), unit="deg")
        + (
            _column("cam_valid", "bool"),
            _column("camera_reference"),
        )
        + _vector_columns("cam_pos", "cam_pos", ("x_m", "y_m", "z_m"), unit="m")
        + _vector_columns("cam_rot", "cam_rot", ("x", "y", "z", "w"))
        + _vector_columns("cam_euler_deg", "cam_euler_deg", ("x", "y", "z"), unit="deg")
        + (
            _column("reference_pose_valid", "bool"),
            _column("reference_pose_source"),
            _column("reference_pose_fresh", "bool"),
            _column("reference_pose_keep_alive", "bool"),
            _column("reference_pose_fresh_age_ms", "float", unit="ms"),
            _column("reference_sample_mono_ms", "float", unit="ms"),
        )
        + _vector_columns("reference_pos", "reference_pos", ("x_m", "y_m", "z_m"), unit="m")
        + _vector_columns("reference_rot", "reference_rot", ("x", "y", "z", "w"))
        + _vector_columns(
            "reference_euler_deg",
            "reference_euler_deg",
            ("x", "y", "z"),
            unit="deg",
        )
        + _source_columns(),
        (_SESSION_FK,),
    ),
    _sheet(
        "unity_admission",
        "session plus candidate plus variant",
        ("session_id", "candidate_id", "variant_id"),
        _SOURCE_ID_COLUMNS
        + _CONTEXT_COLUMNS
        + (
            _column("candidate_id"),
            _column("frame_id", "int"),
            _column("variant_label"),
            _column("unity_pose_handle_mono_ms", "float", unit="ms"),
            _column("unity_frame", "int"),
            _column("world_alignment_mode"),
            _column("uses_capture_time_alignment", "bool"),
            _column("source_capture_mono_ms", "float", unit="ms"),
            _column("source_capture_unity_frame", "int"),
            _column("has_aligned_raw", "bool"),
        )
        + _vector_columns("aligned_raw_pos", "aligned_raw_pos", ("x_m", "y_m", "z_m"), unit="m")
        + _vector_columns("aligned_raw_rot", "aligned_raw_rot", ("x", "y", "z", "w"))
        + _vector_columns(
            "aligned_raw_euler_deg",
            "aligned_raw_euler_deg",
            ("x", "y", "z"),
            unit="deg",
        )
        + (
            _column("has_arrival_time_raw", "bool"),
        )
        + _vector_columns(
            "arrival_time_raw_pos",
            "arrival_time_raw_pos",
            ("x_m", "y_m", "z_m"),
            unit="m",
        )
        + _vector_columns("arrival_time_raw_rot", "arrival_time_raw_rot", ("x", "y", "z", "w"))
        + _vector_columns(
            "arrival_time_raw_euler_deg",
            "arrival_time_raw_euler_deg",
            ("x", "y", "z"),
            unit="deg",
        )
        + (
            _column("arrival_time_raw_mono_ms", "float", unit="ms"),
            _column("uses_vcd_admission", "bool"),
            _column("vcd_score", "float"),
            _column("quality_gate"),
            _column("admission_decision"),
            _column("policy_action"),
            _column("policy_reason"),
            _column("anchor_state"),
            _column("motion_model"),
            _column("smoothing_strategy"),
            _column("uses_temporal_synthesis", "bool"),
            _column("uses_static_lock", "bool"),
            _column("config_hash"),
        )
        + _source_columns(),
        (_SESSION_FK, _CANDIDATE_FK, _VARIANT_FK),
    ),
    _sheet(
        "unity_render",
        "session plus render tick plus variant",
        ("session_id", "render_tick_id", "variant_id"),
        _SOURCE_ID_COLUMNS
        + _CONTEXT_COLUMNS
        + (
            _column("render_tick_id", "int"),
            _column("render_mono_ms", "float", unit="ms"),
            _column("render_unix_ms", "float", unit="ms"),
            _column("render_unity_frame", "int"),
            _column("render_local"),
            _column("render_utc"),
            _column("variant_label"),
            _column("strategy_label"),
        )
        + _vector_columns("head_pos", "head_pos", ("x_m", "y_m", "z_m"), unit="m")
        + _vector_columns("head_rot", "head_rot", ("x", "y", "z", "w"))
        + _vector_columns("head_euler_deg", "head_euler_deg", ("x", "y", "z"), unit="deg")
        + (
            _column("reference_pose_valid", "bool"),
            _column("reference_pose_source"),
            _column("reference_pose_fresh", "bool"),
            _column("reference_pose_keep_alive", "bool"),
            _column("reference_pose_fresh_age_ms", "float", unit="ms"),
        )
        + _vector_columns("reference_pos", "reference_pos", ("x_m", "y_m", "z_m"), unit="m")
        + _vector_columns("reference_rot", "reference_rot", ("x", "y", "z", "w"))
        + _vector_columns(
            "reference_euler_deg",
            "reference_euler_deg",
            ("x", "y", "z"),
            unit="deg",
        )
        + (
            _column("reference_linear_speed_m_s", "float", unit="m/s"),
            _column("reference_angular_speed_deg_s", "float", unit="deg/s"),
            _column("source_frame_id", "int"),
            _column("has_source_capture_timing", "bool"),
            _column("source_capture_mono_ms", "float", unit="ms"),
            _column("source_capture_unity_frame", "int"),
            _column("unity_pose_handle_mono_ms", "float", unit="ms"),
            _column("has_output_pose", "bool"),
        )
        + _vector_columns("output_pos", "output_pos", ("x_m", "y_m", "z_m"), unit="m")
        + _vector_columns("output_rot", "output_rot", ("x", "y", "z", "w"))
        + _vector_columns("output_euler_deg", "output_euler_deg", ("x", "y", "z"), unit="deg")
        + (
            _column("has_display_pose", "bool"),
        )
        + _vector_columns("display_pos", "display_pos", ("x_m", "y_m", "z_m"), unit="m")
        + _vector_columns("display_rot", "display_rot", ("x", "y", "z", "w"))
        + _vector_columns("display_euler_deg", "display_euler_deg", ("x", "y", "z"), unit="deg")
        + (
            _column("anchor_state"),
            _column("anchor_pose_source"),
            _column("motion_state"),
            _column("policy_action"),
            _column("policy_reason"),
            _column("observation_age_ms", "float", unit="ms"),
            _column("policy_output_target_mono_ms", "float", unit="ms"),
            _column("predict_ahead_ms", "float", unit="ms"),
            _column("smoothing_delay_ms", "float", unit="ms"),
            _column("latest_static_locked", "bool"),
            _column("latest_accepted_score", "float"),
            _column("latest_phase"),
            _column("latest_failure"),
            _column("latest_residual_meters", "float", unit="m"),
            _column("latest_residual_degrees", "float", unit="deg"),
            _column("quality_gate"),
            _column("motion_model"),
            _column("smoothing_strategy"),
            _column("config_hash"),
        )
        + _source_columns(),
        (_SESSION_FK, _VARIANT_FK),
    ),
    _sheet(
        "python_events",
        "Python event source row",
        ("event_row_id",),
        _EVENT_COLUMNS,
        (_SESSION_FK,),
    ),
    _sheet(
        "unity_events",
        "Unity event source row",
        ("event_row_id",),
        _EVENT_COLUMNS,
        (_SESSION_FK,),
    ),
    _sheet(
        "events",
        "merged event source row",
        ("event_row_id",),
        _EVENT_COLUMNS,
        (_SESSION_FK,),
    ),
    _sheet(
        "event_payload",
        "merged event row plus JSON path",
        ("event_row_id", "json_path"),
        (
            _column("event_row_id"),
        )
        + _NORMALIZED_VALUE_COLUMNS
        + (
            _column("event_role"),
        )
        + _source_columns(),
        (_EVENT_FK,),
    ),
    _sheet(
        "row_kv",
        "unmapped JSONL row plus JSON path",
        ("source_file", "source_line", "json_path"),
        (
            _column("session_id"),
        )
        + _NORMALIZED_VALUE_COLUMNS
        + _source_columns(),
        (_SESSION_FK,),
    ),
    _sheet(
        "large_values",
        "normalized value chunk",
        ("source_table", "source_file", "source_line", "json_path", "chunk_index"),
        (
            _column("source_table"),
            _column("source_file"),
            _column("source_line", "int"),
            _column("json_path"),
            _column("chunk_index", "int"),
            _column("value_sha256"),
            _column("char_count", "int"),
            _column("byte_count", "int"),
            _column("chunk_text"),
        ),
    ),
    _sheet(
        "qc_checks",
        "QC check",
        ("check_id",),
        (
            _column("check_id"),
            _column("status"),
            _column("severity"),
            _column("observed"),
            _column("expected"),
            _column("details"),
            _column("source_file"),
            _column("source_line", "int"),
        ),
    ),
    _sheet(
        "data_dictionary",
        "sheet plus column",
        ("sheet", "column"),
        (
            _column("sheet"),
            _column("column"),
            _column("dtype"),
            _column("unit"),
            _column("nullable", "bool"),
            _column("source_json_path"),
            _column("description"),
        ),
    ),
    _sheet(
        "sheet_index",
        "physical workbook sheet",
        ("physical_sheet",),
        (
            _column("logical_sheet"),
            _column("physical_sheet"),
            _column("partition_index", "int"),
            _column("row_count", "int"),
            _column("column_count", "int"),
            _column("header_sha256"),
        ),
    ),
)
"""Stage 1 workbook-v2 的完整 sheet 契约，顺序即默认写出顺序。"""

SHEET_NAMES = tuple(sheet.name for sheet in SHEET_CONTRACTS)
"""Stage 1 workbook 的稳定 sheet 名称顺序。"""


_RESULT_COLUMNS = (
    _column("session_id"),
    _column("experiment_id"),
    _column("scenario_id"),
    _column("trial_id"),
    _column("event_id"),
    _column("condition_id"),
    _column("variant_id"),
    _column("metric_key"),
    _column("metric_value", "float"),
    _column("metric_unit"),
    _column("aggregation_level"),
    _column("input_workbook_sha256"),
)
"""Stage 2 指标结果表共享列。"""


_SCENARIO_SUMMARY_COLUMNS = _RESULT_COLUMNS + (
    _column("attempt_count", "int", description="进入该指标汇总的全部 event/segment 或 session 尝试数量。"),
    _column("sample_count", "int", description="尝试中得到有限指标值的 event/segment 或 session 数量。"),
    _column("success_rate", "float", description="有限指标值数量除以全部尝试数量；不替代指标自身的成功率语义。"),
    _column("median", "float", description="有限指标值的中位数；存在有限值时必须等于 metric_value。"),
    _column("q1", "float", description="有限指标值的第一四分位数。"),
    _column("q3", "float", description="有限指标值的第三四分位数。"),
    _column("iqr", "float", description="有限指标值第三四分位数与第一四分位数之差。"),
    _column("minimum", "float", description="有限指标值的最小值。"),
    _column("maximum", "float", description="有限指标值的最大值。"),
)
"""场景级低样本量报告必须显式保存的尝试、成功率和完整分布统计。"""

_PAIRED_DELTA_COLUMNS = _RESULT_COLUMNS + (
    _column("component_id", description="实验二归因组件的稳定标识。"),
    _column("full_variant_id", description="配对完整系统，固定为 EgoAnchor。"),
    _column("ablation_variant_id", description="与完整系统配对的单组件消融配置。"),
    _column("full_value", "float", description="完整 EgoAnchor 在同 event 的指标值。"),
    _column("ablation_value", "float", description="单组件消融在同 event 的指标值。"),
    _column("delta", "float", description="消融值减完整系统值；任一侧为空时保持为空。"),
    _column("pair_status", description="complete 或 value_missing；缺行不允许进入结果。"),
)
"""实验二 event-level 配对差值的完整审计列。"""

_PAIRED_SUMMARY_COLUMNS = (
    _column("experiment_id"),
    _column("scenario_id"),
    _column("component_id"),
    _column("full_variant_id"),
    _column("ablation_variant_id"),
    _column("metric_key"),
    _column("metric_unit"),
    _column("attempt_count", "int"),
    _column("sample_count", "int"),
    _column("median", "float"),
    _column("q1", "float"),
    _column("q3", "float"),
    _column("iqr", "float"),
    _column("minimum", "float"),
    _column("maximum", "float"),
    _column("positive_count", "int"),
    _column("zero_count", "int"),
    _column("negative_count", "int"),
    _column("input_workbook_sha256"),
)
"""实验二配对 delta 的低样本量汇总与方向计数列。"""

_VCD_RISK_POINT_COLUMNS = (
    _column("session_id"),
    _column("experiment_id"),
    _column("scenario_id"),
    _column("trial_id"),
    _column("candidate_id"),
    _column("frame_id", "int"),
    _column("source_capture_mono_ms", "float", unit="ms"),
    _column("variant_id"),
    _column("vcd_score", "float"),
    _column("risk_mm", "float", unit="mm"),
    _column("eligible", "bool"),
    _column("exclusion_reason"),
    _column("has_aligned_raw", "bool"),
    _column("reference_pose_valid", "bool"),
    _column("reference_session_id"),
    _column("reference_frame_id", "int"),
    _column("input_workbook_sha256"),
)
"""实际到达 Unity 的完整 EgoAnchor candidate risk 与排除原因。"""

_VCD_CURVE_COLUMNS = (
    _column("scenario_id"),
    _column("reference_kind"),
    _column("risk_kind"),
    _column("point_index", "int"),
    _column("threshold", "float"),
    _column("coverage", "float"),
    _column("risk_mm", "float", unit="mm"),
    _column("group_count", "int"),
    _column("cumulative_count", "int"),
    _column("coverage_denominator", "int"),
    _column("input_workbook_sha256"),
)
"""VCD 与精确随机参考的 mean/tail risk-coverage 长表列。"""

_VCD_AURC_COLUMNS = (
    _column("scenario_id"),
    _column("reference_kind"),
    _column("risk_kind"),
    _column("aurc_mm", "float", unit="mm"),
    _column("candidate_count", "int"),
    _column("coverage_denominator", "int"),
    _column("arrived_count", "int"),
    _column("excluded_no_aligned_count", "int"),
    _column("excluded_missing_reference_count", "int"),
    _column("excluded_invalid_reference_count", "int"),
    _column("excluded_non_finite_pose_count", "int"),
    _column("input_workbook_sha256"),
)
"""mean-risk 右阶梯 AURC 与候选 cohort 审计列。"""

_SENSITIVITY_COLUMNS = (
    _column("scenario_id"),
    _column("metric_key"),
    _column("parameter_name"),
    _column("alternative_id"),
    _column("base_setting"),
    _column("alternative_setting"),
    _column("base_value", "float"),
    _column("alternative_value", "float"),
    _column("delta", "float"),
    _column("input_workbook_sha256"),
)
"""同一敏感性参数可保存多个替代 cohort 的稳定长表列。"""

_EXP1_PLOT_CONTEXT_COLUMNS = (
    _column("plot_id"),
    _column("panel_id"),
    _column("session_id"),
    _column("scenario_id"),
    _column("trial_id"),
    _column("event_id"),
    _column("variant_id"),
)
"""实验一四面板 plot-ready 表共享的稳定上下文列。"""

_EXP1_HEAD_TRACE_COLUMNS = _EXP1_PLOT_CONTEXT_COLUMNS + (
    _column("sample_index", "int"),
    _column("time_ms", "float", unit="ms"),
    _column("head_angular_speed_deg_s", "float", unit="deg/s"),
    _column("translation_error_mm", "float", unit="mm"),
    _column("selection_rule"),
    _column("input_workbook_sha256"),
)
"""静止头动代表事件的头动速度和显示误差时间线。"""

_EXP1_START_STOP_TRACE_COLUMNS = _EXP1_PLOT_CONTEXT_COLUMNS + (
    _column("sample_index", "int"),
    _column("time_ms", "float", unit="ms"),
    _column("reference_displacement_mm", "float", unit="mm"),
    _column("display_displacement_mm", "float", unit="mm"),
    _column("translation_error_mm", "float", unit="mm"),
    _column("phase"),
    _column("has_output_pose", "bool"),
    _column("latest_static_locked", "bool"),
    _column("selection_rule"),
    _column("input_workbook_sha256"),
)
"""起停代表事件的参考、显示、误差和状态时间线。"""

_EXP1_LAG_TRADEOFF_COLUMNS = _EXP1_PLOT_CONTEXT_COLUMNS + (
    _column("point_kind"),
    _column("effective_lag_ms", "float", unit="ms"),
    _column("p95_residual_mm", "float", unit="mm"),
    _column("lag_q1_ms", "float", unit="ms"),
    _column("lag_q3_ms", "float", unit="ms"),
    _column("residual_q1_mm", "float", unit="mm"),
    _column("residual_q3_mm", "float", unit="mm"),
    _column("input_workbook_sha256"),
)
"""持续平移 event 点和系统 median/IQR 的 lag--fidelity 表。"""

_EXP1_OCCLUSION_TRACE_COLUMNS = _EXP1_PLOT_CONTEXT_COLUMNS + (
    _column("sample_index", "int"),
    _column("time_ms", "float", unit="ms"),
    _column("translation_error_mm", "float", unit="mm"),
    _column("occluded", "bool"),
    _column("has_output_pose", "bool"),
    _column("has_display_pose", "bool"),
    _column("selection_rule"),
    _column("input_workbook_sha256"),
)
"""遮挡代表事件的显示误差与 output/display 状态时间线。"""


CSV_TABLE_CONTRACTS = (
    CsvTableContract("analysis_run", "analysis invocation", ("analysis_run_id",), (_column("analysis_run_id"), _column("created_at_utc", "datetime"), _column("code_version"), _column("parameter_set_id"), _column("status"), _column("input_count", "int"), _column("output_root"))),
    CsvTableContract("inputs", "analysis input workbook", ("input_workbook_sha256",), (_column("input_workbook"), _column("input_workbook_sha256"), _column("session_id"), _column("qc_status"), _column("row_count", "int"))),
    CsvTableContract("metric_catalog", "metric definition", ("metric_key",), (_column("metric_key"), _column("label"), _column("formula"), _column("unit"), _column("direction"), _column("scenarios"), _column("aggregation"), _column("source_columns", "json"))),
    CsvTableContract("filter_catalog", "filter definition", ("filter_rule_id",), (_column("filter_rule_id"), _column("description"), _column("included_trials"), _column("excluded_trials"), _column("reason"))),
    CsvTableContract("analysis_qc", "analysis QC check", ("check_id",), (_column("check_id"), _column("status"), _column("observed"), _column("expected"), _column("details"))),
    CsvTableContract("lineage", "result lineage", ("output_path", "output_row_id"), (_column("output_path"), _column("output_row_id"), _column("input_workbook"), _column("input_workbook_sha256"), _column("source_sheet"), _column("source_row_key"), _column("metric_key"))),
    CsvTableContract("sensitivity", "parameter sensitivity", ("scenario_id", "metric_key", "parameter_name", "alternative_id"), _SENSITIVITY_COLUMNS),
    CsvTableContract("trial_windows", "trial plus event window", ("session_id", "trial_id", "event_id"), _RESULT_COLUMNS),
    CsvTableContract("frame_metrics", "render frame", ("session_id", "trial_id", "event_id", "variant_id", "frame_id"), _RESULT_COLUMNS + (_column("frame_id", "int"),)),
    CsvTableContract("candidate_metrics", "candidate", ("session_id", "candidate_id"), _RESULT_COLUMNS + (_column("candidate_id"),)),
    CsvTableContract("event_metrics", "event plus variant plus metric", ("session_id", "scenario_id", "trial_id", "event_id", "variant_id", "metric_key"), _RESULT_COLUMNS),
    CsvTableContract("trial_metrics", "trial plus variant plus metric", ("session_id", "scenario_id", "trial_id", "variant_id", "metric_key"), _RESULT_COLUMNS),
    CsvTableContract("session_metrics", "session plus variant plus metric", ("session_id", "scenario_id", "variant_id", "metric_key"), _RESULT_COLUMNS),
    CsvTableContract(
        "scenario_summary",
        "scenario plus variant plus metric",
        ("scenario_id", "variant_id", "metric_key"),
        _SCENARIO_SUMMARY_COLUMNS,
    ),
    CsvTableContract("paired_deltas", "paired event delta", ("session_id", "scenario_id", "trial_id", "event_id", "component_id", "metric_key"), _PAIRED_DELTA_COLUMNS),
    CsvTableContract("paired_summary", "component plus metric paired delta summary", ("scenario_id", "component_id", "metric_key"), _PAIRED_SUMMARY_COLUMNS),
    CsvTableContract("vcd_risk_points", "received candidate risk point", ("session_id", "candidate_id"), _VCD_RISK_POINT_COLUMNS),
    CsvTableContract("vcd_curve", "coverage threshold point", ("scenario_id", "reference_kind", "risk_kind", "point_index"), _VCD_CURVE_COLUMNS),
    CsvTableContract("vcd_aurc", "scenario mean-risk AURC summary", ("scenario_id", "reference_kind", "risk_kind"), _VCD_AURC_COLUMNS),
    CsvTableContract("plot_catalog", "plot panel", ("plot_id", "panel_id"), (_column("plot_id"), _column("panel_id"), _column("source_csv"), _column("x"), _column("y"), _column("hue"), _column("filter_rule_id"), _column("order", "int"), _column("unit"), _column("target_width"), _column("expected_rows", "int"), _column("data_sha256"))),
    CsvTableContract("exp1_head_motion_trace", "representative render trace", ("plot_id", "panel_id", "session_id", "trial_id", "event_id", "variant_id", "sample_index"), _EXP1_HEAD_TRACE_COLUMNS),
    CsvTableContract("exp1_start_stop_trace", "representative render trace", ("plot_id", "panel_id", "session_id", "trial_id", "event_id", "variant_id", "sample_index"), _EXP1_START_STOP_TRACE_COLUMNS),
    CsvTableContract("exp1_lag_tradeoff", "event plus summary plot point", ("plot_id", "panel_id", "point_kind", "session_id", "trial_id", "event_id", "variant_id"), _EXP1_LAG_TRADEOFF_COLUMNS),
    CsvTableContract("exp1_occlusion_trace", "representative render trace", ("plot_id", "panel_id", "session_id", "trial_id", "event_id", "variant_id", "sample_index"), _EXP1_OCCLUSION_TRACE_COLUMNS),
    CsvTableContract("exp2_component_deltas", "plot row", ("plot_id", "panel_id", "session_id", "scenario_id", "trial_id", "event_id", "component_id", "metric_key"), _PAIRED_DELTA_COLUMNS + (_column("plot_id"), _column("panel_id"))),
    CsvTableContract("exp2_vcd_curve", "plot row", ("plot_id", "panel_id", "reference_kind", "risk_kind", "point_index"), _VCD_CURVE_COLUMNS + (_column("plot_id"), _column("panel_id"))),
    CsvTableContract("numbers", "paper number", ("experiment", "macro_name"), (_column("experiment"), _column("macro_name"), _column("value"), _column("source_csv"), _column("source_sha256"))),
    CsvTableContract("tables", "paper table cell", ("experiment", "table_name", "row_key", "column_key"), (_column("experiment"), _column("table_name"), _column("row_key"), _column("column_key"), _column("display_value"), _column("source_csv"), _column("source_sha256"))),
)
"""Stage 2 全部 CSV 表的稳定契约。"""

CSV_TABLE_NAMES = tuple(table.name for table in CSV_TABLE_CONTRACTS)
"""Stage 2 CSV 表名顺序。"""


def workbook_catalog() -> list[dict[str, Any]]:
    """返回完整 workbook sheet 契约目录。"""

    return [sheet.to_dict() for sheet in SHEET_CONTRACTS]


def csv_catalog() -> list[dict[str, Any]]:
    """返回完整 CSV 表契约目录。"""

    return [table.to_dict() for table in CSV_TABLE_CONTRACTS]


def get_sheet_contract(name: str) -> SheetContract:
    """按稳定名称查找 workbook sheet 契约。"""

    for sheet in SHEET_CONTRACTS:
        if sheet.name == name:
            return sheet
    raise KeyError(f"未知 workbook sheet：{name}")


__all__ = [
    "CSV_TABLE_CONTRACTS",
    "CSV_TABLE_NAMES",
    "DATA_TYPES",
    "SHEET_CONTRACTS",
    "SHEET_NAMES",
    "ColumnContract",
    "CsvTableContract",
    "ForeignKeyContract",
    "SheetContract",
    "csv_catalog",
    "get_sheet_contract",
    "workbook_catalog",
]

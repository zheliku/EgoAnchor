"""Stage 1 workbook 与 Stage 2 CSV 的结构化数据契约。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
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

    return ColumnContract(name=name, dtype=dtype, **kwargs)


def _source_columns() -> tuple[ColumnContract, ...]:
    """返回所有事实表共享的来源追踪列。"""

    return (
        _column("source_file", source_path="source_file"),
        _column("source_line", "int", source_path="source_line"),
        _column("source_row_sha256", source_path="source_row_sha256"),
    )


def _sheet(
    name: str,
    grain: str,
    primary_key: tuple[str, ...],
    columns: Iterable[ColumnContract],
    foreign_keys: tuple[ForeignKeyContract, ...] = (),
) -> SheetContract:
    """构造并返回一个 sheet 契约。"""

    return SheetContract(name, grain, primary_key, tuple(columns), foreign_keys)


_ID_COLUMNS = (
    _column("session_id", source_path="manifest.session_id"),
    _column("experiment_id"),
    _column("scenario_id"),
    _column("trial_id"),
    _column("event_id"),
    _column("condition_id"),
    _column("variant_id"),
)
"""常见跨表稳定键列。"""


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
            _column("config_hash"),
            _column("code_version"),
            _column("generated_at_utc", "datetime"),
            _column("input_sha256"),
        ),
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
            _column("json_path"),
            _column("value_type"),
            _column("value_json"),
            _column("source_file"),
            _column("source_line", "int"),
            _column("source_row_sha256"),
        ),
    ),
    _sheet(
        "variants",
        "session plus variant",
        ("session_id", "variant_id"),
        (
            _column("session_id"),
            _column("variant_id"),
            _column("variant_label"),
            _column("experiment_id"),
            _column("scenario_id"),
            _column("config_hash"),
            _column("uses_capture_time_alignment", "bool"),
            _column("uses_vcd_admission", "bool"),
            _column("uses_temporal_synthesis", "bool"),
            _column("uses_static_lock", "bool"),
            _column("quality_gate"),
            _column("motion_model"),
            _column("smoothing_strategy"),
            _column("source_file"),
            _column("source_row_sha256"),
        ),
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
    ),
    _sheet(
        "completed_trials",
        "completed trial",
        ("session_id", "experiment_id", "scenario_id", "trial_id", "event_id", "condition_id"),
        _ID_COLUMNS[:6] + _source_columns(),
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
        ),
    ),
    _sheet(
        "python_candidates",
        "session plus candidate",
        ("session_id", "candidate_id"),
        _ID_COLUMNS[:1]
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
            _column("pose_matrix_00", "float"),
            _column("pose_matrix_01", "float"),
            _column("pose_matrix_02", "float"),
            _column("pose_matrix_03", "float"),
            _column("pose_matrix_10", "float"),
            _column("pose_matrix_11", "float"),
            _column("pose_matrix_12", "float"),
            _column("pose_matrix_13", "float"),
            _column("pose_matrix_20", "float"),
            _column("pose_matrix_21", "float"),
            _column("pose_matrix_22", "float"),
            _column("pose_matrix_23", "float"),
            _column("pose_matrix_30", "float"),
            _column("pose_matrix_31", "float"),
            _column("pose_matrix_32", "float"),
            _column("pose_matrix_33", "float"),
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
    ),
    _sheet(
        "candidate_flags",
        "candidate plus flag",
        ("candidate_id", "flag_index"),
        (_column("candidate_id"), _column("flag_index", "int"), _column("flag")),
    ),
    _sheet(
        "candidate_diag",
        "candidate plus JSON path",
        ("candidate_id", "json_path"),
        (
            _column("candidate_id"),
            _column("json_path"),
            _column("value_type"),
            _column("value_json"),
            _column("source_file"),
            _column("source_line", "int"),
            _column("source_row_sha256"),
        ),
    ),
    _sheet(
        "unity_reference",
        "session plus frame",
        ("session_id", "frame_id"),
        _ID_COLUMNS[:1]
        + (
            _column("frame_id", "int"),
            _column("capture_mono_ms", "float", unit="ms"),
            _column("capture_unix_ms", "float", unit="ms"),
            _column("capture_unity_frame", "int"),
            _column("reference_pose_valid", "bool"),
            _column("reference_pose_source"),
            _column("reference_pos_x_m", "float", unit="m"),
            _column("reference_pos_y_m", "float", unit="m"),
            _column("reference_pos_z_m", "float", unit="m"),
            _column("reference_rot_x", "float"),
            _column("reference_rot_y", "float"),
            _column("reference_rot_z", "float"),
            _column("reference_rot_w", "float"),
            _column("head_pos", "json"),
            _column("head_rot", "json"),
            _column("cam_pos", "json"),
            _column("cam_rot", "json"),
        )
        + _source_columns(),
    ),
    _sheet(
        "unity_admission",
        "session plus candidate plus variant",
        ("session_id", "candidate_id", "variant_id"),
        _ID_COLUMNS
        + (
            _column("candidate_id"),
            _column("unity_pose_handle_mono_ms", "float", unit="ms"),
            _column("source_capture_mono_ms", "float", unit="ms"),
            _column("world_alignment_mode"),
            _column("uses_capture_time_alignment", "bool"),
            _column("has_aligned_raw", "bool"),
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
    ),
    _sheet(
        "unity_render",
        "session plus render tick plus variant",
        ("session_id", "render_tick_id", "variant_id"),
        _ID_COLUMNS
        + (
            _column("render_tick_id", "int"),
            _column("render_mono_ms", "float", unit="ms"),
            _column("source_frame_id", "int"),
            _column("has_output_pose", "bool"),
            _column("has_display_pose", "bool"),
            _column("reference_pose_valid", "bool"),
            _column("reference_pos", "json"),
            _column("reference_rot", "json"),
            _column("output_pos", "json"),
            _column("output_rot", "json"),
            _column("display_pos", "json"),
            _column("display_rot", "json"),
            _column("anchor_state"),
            _column("policy_action"),
            _column("policy_reason"),
            _column("observation_age_ms", "float", unit="ms"),
            _column("smoothing_delay_ms", "float", unit="ms"),
            _column("latest_static_locked", "bool"),
            _column("latest_accepted_score", "float"),
            _column("quality_gate"),
            _column("motion_model"),
            _column("smoothing_strategy"),
            _column("config_hash"),
        )
        + _source_columns(),
    ),
    _sheet(
        "python_events",
        "source row",
        ("source_file", "source_line"),
        (
            _column("source_file"),
            _column("source_line", "int"),
            _column("event_row_id"),
            _column("event"),
            _column("event_type"),
            _column("session_id"),
            _column("created_unix_ms", "float", unit="ms"),
            _column("mono_ms", "float", unit="ms"),
            _column("payload", "json"),
            _column("source_row_sha256"),
        ),
    ),
    _sheet(
        "unity_events",
        "source row",
        ("source_file", "source_line"),
        (
            _column("source_file"),
            _column("source_line", "int"),
            _column("event_row_id"),
            _column("event"),
            _column("event_type"),
            _column("session_id"),
            _column("created_unix_ms", "float", unit="ms"),
            _column("mono_ms", "float", unit="ms"),
            _column("payload", "json"),
            _column("source_row_sha256"),
        ),
    ),
    _sheet(
        "events",
        "merged source row",
        ("source_file", "source_line"),
        (
            _column("source_file"),
            _column("source_line", "int"),
            _column("event_row_id"),
            _column("event"),
            _column("event_type"),
            _column("session_id"),
            _column("experiment_id"),
            _column("scenario_id"),
            _column("trial_id"),
            _column("event_id"),
            _column("variant_id"),
            _column("created_unix_ms", "float", unit="ms"),
            _column("mono_ms", "float", unit="ms"),
            _column("payload", "json"),
            _column("source_row_sha256"),
        ),
    ),
    _sheet(
        "event_payload",
        "event row plus JSON path",
        ("event_row_id", "json_path"),
        (
            _column("event_row_id"),
            _column("json_path"),
            _column("value_type"),
            _column("value_json"),
            _column("event_role"),
            _column("source_file"),
            _column("source_line", "int"),
            _column("source_row_sha256"),
        ),
    ),
    _sheet(
        "qc_checks",
        "QC check",
        ("check_id",),
        (
            _column("check_id"),
            _column("status"),
            _column("observed"),
            _column("expected"),
            _column("details"),
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
)
"""Stage 1 完整 workbook sheet 契约，顺序即默认写出顺序。"""

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


CSV_TABLE_CONTRACTS = (
    CsvTableContract("analysis_run", "analysis invocation", ("analysis_run_id",), (_column("analysis_run_id"), _column("created_at_utc", "datetime"), _column("code_version"), _column("parameter_set_id"), _column("status"), _column("input_count", "int"), _column("output_root"))),
    CsvTableContract("inputs", "analysis input workbook", ("input_workbook_sha256",), (_column("input_workbook"), _column("input_workbook_sha256"), _column("session_id"), _column("qc_status"), _column("row_count", "int"))),
    CsvTableContract("metric_catalog", "metric definition", ("metric_key",), (_column("metric_key"), _column("label"), _column("formula"), _column("unit"), _column("direction"), _column("scenarios"), _column("aggregation"), _column("source_columns", "json"))),
    CsvTableContract("filter_catalog", "filter definition", ("filter_rule_id",), (_column("filter_rule_id"), _column("description"), _column("included_trials"), _column("excluded_trials"), _column("reason"))),
    CsvTableContract("analysis_qc", "analysis QC check", ("check_id",), (_column("check_id"), _column("status"), _column("observed"), _column("expected"), _column("details"))),
    CsvTableContract("lineage", "result lineage", ("output_path", "output_row_id"), (_column("output_path"), _column("output_row_id"), _column("input_workbook"), _column("input_workbook_sha256"), _column("source_sheet"), _column("source_row_key"), _column("metric_key"))),
    CsvTableContract("sensitivity", "parameter sensitivity", ("scenario_id", "metric_key", "parameter_name"), (_column("scenario_id"), _column("metric_key"), _column("parameter_name"), _column("base_value", "float"), _column("alternative_value", "float"), _column("delta", "float"), _column("input_workbook_sha256"))),
    CsvTableContract("trial_windows", "trial plus event window", ("session_id", "trial_id", "event_id"), _RESULT_COLUMNS),
    CsvTableContract("frame_metrics", "render frame", ("session_id", "trial_id", "event_id", "variant_id", "frame_id"), _RESULT_COLUMNS + (_column("frame_id", "int"),)),
    CsvTableContract("candidate_metrics", "candidate", ("session_id", "candidate_id"), _RESULT_COLUMNS + (_column("candidate_id"),)),
    CsvTableContract("event_metrics", "event plus variant plus metric", ("session_id", "scenario_id", "trial_id", "event_id", "variant_id", "metric_key"), _RESULT_COLUMNS),
    CsvTableContract("trial_metrics", "trial plus variant plus metric", ("session_id", "scenario_id", "trial_id", "variant_id", "metric_key"), _RESULT_COLUMNS),
    CsvTableContract("session_metrics", "session plus variant plus metric", ("session_id", "scenario_id", "variant_id", "metric_key"), _RESULT_COLUMNS),
    CsvTableContract("scenario_summary", "scenario plus variant plus metric", ("scenario_id", "variant_id", "metric_key"), _RESULT_COLUMNS),
    CsvTableContract("paired_deltas", "paired event delta", ("session_id", "scenario_id", "trial_id", "event_id", "metric_key"), _RESULT_COLUMNS + (_column("full_value", "float"), _column("ablation_value", "float"), _column("delta", "float"))),
    CsvTableContract("vcd_risk_points", "candidate risk point", ("session_id", "candidate_id"), _RESULT_COLUMNS + (_column("risk_mm", "float", unit="mm"), _column("vcd_score", "float"), _column("eligible", "bool"))),
    CsvTableContract("vcd_curve", "coverage threshold point", ("scenario_id", "coverage"), (_column("scenario_id"), _column("coverage", "float"), _column("risk_mm", "float", unit="mm"), _column("threshold", "float"), _column("input_workbook_sha256"))),
    CsvTableContract("vcd_aurc", "scenario AURC summary", ("scenario_id",), (_column("scenario_id"), _column("aurc_mm", "float", unit="mm"), _column("candidate_count", "int"), _column("coverage_denominator", "int"), _column("input_workbook_sha256"))),
    CsvTableContract("plot_catalog", "plot panel", ("plot_id", "panel_id"), (_column("plot_id"), _column("panel_id"), _column("source_csv"), _column("x"), _column("y"), _column("hue"), _column("filter_rule_id"), _column("order", "int"), _column("unit"), _column("target_width"), _column("expected_rows", "int"), _column("data_sha256"))),
    CsvTableContract("exp1_static_timeline", "plot row", ("plot_id", "panel_id", "event_id", "variant_id"), _RESULT_COLUMNS + (_column("plot_id"), _column("panel_id"))),
    CsvTableContract("exp1_motion_events", "plot row", ("plot_id", "panel_id", "event_id", "variant_id"), _RESULT_COLUMNS + (_column("plot_id"), _column("panel_id"))),
    CsvTableContract("exp1_occlusion_events", "plot row", ("plot_id", "panel_id", "event_id", "variant_id"), _RESULT_COLUMNS + (_column("plot_id"), _column("panel_id"))),
    CsvTableContract("exp2_component_deltas", "plot row", ("plot_id", "panel_id", "event_id", "metric_key"), _RESULT_COLUMNS + (_column("plot_id"), _column("panel_id"))),
    CsvTableContract("exp2_vcd_curve", "plot row", ("plot_id", "panel_id", "coverage"), (_column("plot_id"), _column("panel_id"), _column("scenario_id"), _column("coverage", "float"), _column("risk_mm", "float", unit="mm"))),
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

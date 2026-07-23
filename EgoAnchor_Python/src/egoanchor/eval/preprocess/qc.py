"""Stage 1 schema-v2 task 的完整只读硬 QC。"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..schema_v2 import SCHEMA_VERSION, SchemaV2Error, validate_schema_mapping
from .events import merged_event_text
from .reader import SourceRow, TaskDataset, read_task


FORMAL_VARIANTS = {
    "Arrival-Hold": ("ArrivalTime", False, False, False, False, False, False),
    "Capture-Hold": ("CaptureTime", True, False, False, False, False, False),
    "One-Euro Anchor": ("CaptureTime", True, True, True, False, True, True),
    "EgoAnchor": ("CaptureTime", True, True, True, True, True, True),
    "EgoAnchor Causal Prediction": ("CaptureTime", True, True, True, False, True, True),
    "EgoAnchor w/o capture-time alignment": ("ArrivalTime", False, True, True, True, True, True),
    "EgoAnchor w/o VCD": ("CaptureTime", True, False, True, True, False, True),
    "EgoAnchor w/o temporal synthesis": ("CaptureTime", True, True, False, True, True, True),
    "EgoAnchor w/o StaticLock": ("CaptureTime", True, True, True, False, True, True),
}
"""当前九路正式采集冻结的 variant 定义。"""

FORMAL_METHODS = {
    "Arrival-Hold": ("cv", "hold", "disabled"),
    "Capture-Hold": ("cv", "hold", "disabled"),
    "One-Euro Anchor": ("oneeuro", "linear_slerp", "enabled"),
    "EgoAnchor": ("kalman", "linear_slerp", "enabled"),
    "EgoAnchor Causal Prediction": ("kalman", "causal_prediction", "enabled"),
    "EgoAnchor w/o capture-time alignment": ("kalman", "linear_slerp", "enabled"),
    "EgoAnchor w/o VCD": ("kalman", "linear_slerp", "disabled"),
    "EgoAnchor w/o temporal synthesis": ("kalman", "predict_to_now", "enabled"),
    "EgoAnchor w/o StaticLock": ("kalman", "linear_slerp", "enabled"),
}
"""下一轮正式采集冻结的运动模型、时序策略和质量门控组合。"""

CURRENT_FORMAL_VARIANT_IDS = frozenset(FORMAL_VARIANTS)
"""当前 Unity 正式场景必须完整记录的九路 variant。"""

CURRENT_VARIANT_MATRIX_ID = "exp12_9_causal_v3"
"""当前 Unity manifest 写入的因果预测配对对照九路矩阵标识。"""

SCORE_FIELDS = (
    "vcd_score",
    "visibility_score",
    "geometry_core_score",
    "color_projection_score",
    "depth_alignment_score",
    "depth_abs_score",
    "depth_struct_score",
    "depth_alpha",
    "latest_accepted_score",
)
"""允许为空、否则必须位于闭区间 [0, 1] 的评分字段。"""

FORBIDDEN_FIELD_PREFIXES = ("rq1_", "rq2_", "gt_")
"""不得重新进入正式输入的旧字段前缀。"""

FORBIDDEN_FIELD_NAMES = {"session_manifest", "unity_capture", "unity_output"}
"""不得重新进入正式输入的旧根字段名称。"""


@dataclass(frozen=True, slots=True)
class QcIssue:
    """一条稳定编码的 Stage 1 QC 错误或警告。"""

    code: str
    """机器可读检查编码。"""

    message: str
    """中文诊断信息。"""

    source_file: str = ""
    """相关原始文件名。"""

    source_line: int | None = None
    """相关 JSONL 物理行号。"""

    def to_dict(self) -> dict[str, Any]:
        """返回可序列化的诊断记录。"""

        return asdict(self)


@dataclass(frozen=True, slots=True)
class StageOneQcReport:
    """一次 task 只读 QC 的错误、警告和审计指标。"""

    session_id: str
    """被检查的 session ID；读取失败时可能为空。"""

    errors: tuple[QcIssue, ...]
    """阻止 Stage 1 发布的硬错误。"""

    warnings: tuple[QcIssue, ...]
    """不阻止发布但必须保留的审计警告。"""

    metrics: Mapping[str, Any]
    """行数、矩阵规模和生命周期统计。"""

    @property
    def passed(self) -> bool:
        """没有硬错误时返回 True。"""

        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        """返回 CLI 和后续 qc_checks sheet 使用的普通字典。"""

        return {
            "session_id": self.session_id,
            "passed": self.passed,
            "errors": [issue.to_dict() for issue in self.errors],
            "warnings": [issue.to_dict() for issue in self.warnings],
            "metrics": dict(self.metrics),
        }


class _QcState:
    """在多项流式检查之间集中收集诊断和指标。"""

    def __init__(self, session_id: str = "") -> None:
        """初始化空诊断集合。"""

        self.session_id = session_id
        """当前 session ID。"""

        self.errors: list[QcIssue] = []
        """累计硬错误。"""

        self.warnings: list[QcIssue] = []
        """累计警告。"""

        self.metrics: dict[str, Any] = {}
        """累计审计指标。"""

    def error(self, code: str, message: str, row: SourceRow | None = None) -> None:
        """追加一条硬错误。"""

        self.errors.append(
            QcIssue(
                code,
                message,
                row.source_file if row else "",
                row.source_line if row else None,
            )
        )

    def warning(self, code: str, message: str, row: SourceRow | None = None) -> None:
        """追加一条审计警告。"""

        self.warnings.append(
            QcIssue(
                code,
                message,
                row.source_file if row else "",
                row.source_line if row else None,
            )
        )

    def report(self) -> StageOneQcReport:
        """冻结并返回当前 QC 报告。"""

        return StageOneQcReport(
            self.session_id,
            tuple(self.errors),
            tuple(self.warnings),
            dict(self.metrics),
        )


@dataclass(frozen=True, slots=True)
class _VariantRecord:
    """合并 manifest 定义与配置后的一个 runtime variant。"""

    variant_id: str
    """稳定 variant ID。"""

    motion_model: str
    """运动模型名称。"""

    smoothing_strategy: str
    """时序输出策略名称。"""

    quality_gate: str
    """质量门控模式。"""

    world_alignment_mode: str
    """ArrivalTime 或 CaptureTime。"""

    flags: tuple[bool, ...]
    """采集对齐、VCD、时序、StaticLock、低分重获取和服务端重获取开关。"""

    config_hash: str
    """Unity FNV-1a variant 配置哈希。"""

    configuration_fingerprint: str
    """全部生效数值参数和模块配置的稳定指纹。"""


def run_task_qc(task: TaskDataset | str | Path) -> StageOneQcReport:
    """流式检查一个完整 task；任何路径都只读且不发布派生文件。"""

    try:
        dataset = task if isinstance(task, TaskDataset) else read_task(task)
    except (OSError, SchemaV2Error, ValueError) as exc:
        state = _QcState()
        state.error("reader_error", str(exc))
        return state.report()

    session_id = str(dataset.manifest.get("session_id") or "")
    state = _QcState(session_id)
    _check_documents(dataset, state)
    variants = _check_variants(dataset.manifest, state)
    expected_variant_ids = set(variants)

    candidate_ids: set[str] = set()
    candidate_frames: dict[str, int] = {}
    reference_frames: set[int] = set()
    reference_capture_times: dict[int, float] = {}
    admission_groups: dict[str, set[str]] = defaultdict(set)
    render_groups: dict[int, set[str]] = defaultdict(set)
    continuity_reset_counts: dict[str, int] = {}
    unknown_render_frames: list[SourceRow] = []
    fragment_events: list[tuple[int, Mapping[str, Any]]] = []
    unity_events: list[SourceRow] = []
    row_counts: dict[str, int] = {}

    try:
        for source_row in dataset.iter_rows("python_candidates"):
            row_counts["python_candidates.jsonl"] = row_counts.get("python_candidates.jsonl", 0) + 1
            _check_common_row(source_row, session_id, state)
            candidate_id = _text(source_row.data.get("candidate_id"))
            frame_id = _integer(source_row.data.get("frame_id"))
            if not candidate_id or frame_id is None:
                state.error("candidate_key", "candidate_id 和 frame_id 必须有效。", source_row)
                continue
            if frame_id < 0:
                state.error("candidate_key", "candidate frame_id 不得为负数。", source_row)
            if candidate_id in candidate_ids:
                state.error("candidate_primary_key", f"candidate_id 重复：{candidate_id}", source_row)
            candidate_ids.add(candidate_id)
            candidate_frames[candidate_id] = frame_id
            _check_candidate_id(candidate_id, session_id, frame_id, state, source_row)
            _check_candidate_pose(source_row, state)
            _check_scores(source_row, state)

        for source_row in dataset.iter_rows("unity_reference"):
            row_counts["unity_reference.jsonl"] = row_counts.get("unity_reference.jsonl", 0) + 1
            _check_common_row(source_row, session_id, state)
            frame_id = _integer(source_row.data.get("frame_id"))
            if frame_id is None:
                state.error("reference_key", "unity_reference frame_id 必须是整数。", source_row)
                continue
            if frame_id < 0:
                state.error("reference_key", "unity_reference frame_id 不得为负数。", source_row)
            if frame_id in reference_frames:
                state.error("reference_primary_key", f"reference frame_id 重复：{frame_id}", source_row)
            reference_frames.add(frame_id)
            capture_time = _finite_float(source_row.data.get("capture_mono_ms"))
            if capture_time is not None:
                reference_capture_times[frame_id] = capture_time
            if bool(source_row.data.get("reference_pose_valid")):
                _check_pose_vectors(source_row, "reference_pos", "reference_rot", state)

        for source_row in dataset.iter_rows("unity_admission"):
            row_counts["unity_admission.jsonl"] = row_counts.get("unity_admission.jsonl", 0) + 1
            _check_common_row(source_row, session_id, state)
            row = source_row.data
            candidate_id = _text(row.get("candidate_id"))
            variant_id = _text(row.get("variant_id"))
            frame_id = _integer(row.get("frame_id"))
            if candidate_id not in candidate_ids:
                state.error("admission_candidate_fk", f"admission 指向未知 candidate：{candidate_id}", source_row)
            elif frame_id != candidate_frames.get(candidate_id):
                state.error("admission_candidate_frame", f"admission frame_id 与 candidate 不一致：{candidate_id}", source_row)
            if frame_id is not None and frame_id < 0:
                state.error("admission_key", "admission frame_id 不得为负数。", source_row)
            if variant_id not in expected_variant_ids:
                state.error("admission_variant", f"admission 使用未知 variant：{variant_id}", source_row)
            if variant_id in admission_groups[candidate_id]:
                state.error("admission_primary_key", f"candidate×variant 重复：{candidate_id} / {variant_id}", source_row)
            admission_groups[candidate_id].add(variant_id)
            _check_variant_row(source_row, variants.get(variant_id), state, admission=True)
            if bool(row.get("has_aligned_raw")):
                _check_pose_vectors(source_row, "aligned_raw_pos", "aligned_raw_rot", state)
            if bool(row.get("has_arrival_time_raw")):
                _check_pose_vectors(source_row, "arrival_time_raw_pos", "arrival_time_raw_rot", state)
            _check_scores(source_row, state)

        for source_row in dataset.iter_rows("unity_render"):
            row_counts["unity_render.jsonl"] = row_counts.get("unity_render.jsonl", 0) + 1
            _check_common_row(source_row, session_id, state)
            row = source_row.data
            tick_id = _integer(row.get("render_tick_id"))
            variant_id = _text(row.get("variant_id"))
            if tick_id is None:
                state.error("render_key", "render_tick_id 必须是整数。", source_row)
                continue
            if tick_id < 0:
                state.error("render_key", "render_tick_id 不得为负数。", source_row)
            if variant_id not in expected_variant_ids:
                state.error("render_variant", f"render 使用未知 variant：{variant_id}", source_row)
            if variant_id in render_groups[tick_id]:
                state.error("render_primary_key", f"tick×variant 重复：{tick_id} / {variant_id}", source_row)
            render_groups[tick_id].add(variant_id)
            _check_variant_row(source_row, variants.get(variant_id), state, admission=False)
            _check_smoothing_diagnostics(
                source_row,
                variants.get(variant_id),
                continuity_reset_counts,
                state,
            )
            source_frame_id = _integer(row.get("source_frame_id"))
            if source_frame_id is not None and source_frame_id >= 0 and source_frame_id not in reference_frames:
                unknown_render_frames.append(source_row)
            if bool(row.get("reference_pose_valid")):
                _check_pose_vectors(source_row, "reference_pos", "reference_rot", state)
            if bool(row.get("has_output_pose")):
                _check_pose_vectors(source_row, "output_pos", "output_rot", state)
            if bool(row.get("has_display_pose")):
                _check_pose_vectors(source_row, "display_pos", "display_rot", state)
            _check_scores(source_row, state)

        for source_rank, table in enumerate(("python_events", "unity_events")):
            filename = f"{table}.jsonl"
            count = 0
            for source_row in dataset.iter_rows(table):
                count += 1
                _check_common_row(source_row, session_id, state)
                fragment_events.append((source_rank, source_row.data))
                if table == "unity_events":
                    unity_events.append(source_row)
            row_counts[filename] = count

        merged_count = 0
        for source_row in dataset.iter_rows("events"):
            merged_count += 1
            _check_common_row(source_row, session_id, state)
        row_counts["events.jsonl"] = merged_count
    except (OSError, SchemaV2Error, ValueError) as exc:
        state.error("reader_error", str(exc))
        state.metrics.update(row_counts)
        return state.report()

    for candidate_id, observed in admission_groups.items():
        if observed != expected_variant_ids:
            state.error(
                "admission_variant_matrix",
                f"candidate {candidate_id} 的 variant 集合不完整：{sorted(observed)}",
            )
    for tick_id, observed in render_groups.items():
        if observed != expected_variant_ids:
            state.error(
                "render_variant_matrix",
                f"render tick {tick_id} 的 variant 集合不完整：{sorted(observed)}",
            )

    if not candidate_ids:
        state.error("candidate_coverage", "正式 task 不得缺少 Python candidate。")
    if not admission_groups:
        state.error("admission_coverage", "正式 task 不得缺少 Unity admission。")
    if not reference_frames:
        state.error("reference_coverage", "正式 task 不得缺少平台参考位姿。")
    if not render_groups:
        state.error("render_coverage", "正式 task 不得缺少逐 tick 九路 render。")

    unconsumed = candidate_ids - set(admission_groups)
    if unconsumed:
        state.warning(
            "python_candidates_not_consumed",
            f"{len(unconsumed)} 条 Python candidate 未进入 Unity；按 latest-only 语义从分析投影排除。",
        )

    _check_render_reference_warmup(unknown_render_frames, reference_frames, reference_capture_times, state)
    _check_writer_stats(dataset, row_counts, state)
    _check_event_merge(dataset, fragment_events, state)
    _check_trial_lifecycle(dataset.manifest, unity_events, state)
    state.metrics.update(row_counts)
    state.metrics.update(
        {
            "variant_count": len(expected_variant_ids),
            "candidate_count": len(candidate_ids),
            "consumed_candidate_count": len(admission_groups),
            "unconsumed_candidate_count": len(unconsumed),
            "reference_count": len(reference_frames),
            "render_tick_count": len(render_groups),
            "warmup_render_row_count": len(unknown_render_frames),
        }
    )
    return state.report()


def variant_config_hash(
    label: str,
    motion_model: str,
    smoothing_strategy: str,
    quality_gate: str,
    world_alignment_mode: str,
    flags: Iterable[bool],
    configuration_fingerprint: str,
) -> str:
    """按 Unity EvalRecorder 的 FNV-1a 字段顺序计算完整 variant 配置哈希。"""

    raw = "|".join(
        (
            label,
            motion_model,
            smoothing_strategy,
            quality_gate,
            world_alignment_mode,
            configuration_fingerprint,
            *("1" if flag else "0" for flag in flags),
        )
    )
    return _fnv1a(raw.encode("utf-8"))


def aggregate_config_hash(config_hashes: Iterable[str]) -> str:
    """按 manifest variant 顺序计算整体 FNV-1a 配置哈希。"""

    return _fnv1a("".join(config_hashes).encode("utf-8"))


def _check_documents(dataset: TaskDataset, state: _QcState) -> None:
    """检查两个 JSON 文档的版本、session 和正式采集状态。"""

    manifest = dataset.manifest
    python_session = dataset.python_session
    for filename, document in (("manifest.json", manifest), ("python_session.json", python_session)):
        try:
            validate_schema_mapping(document)
        except SchemaV2Error as exc:
            state.error("document_schema", f"{filename}: {exc}")
        if document.get("schema_version") != SCHEMA_VERSION:
            state.error("schema_version", f"{filename} schema_version 必须为 {SCHEMA_VERSION}。")
        if document.get("session_id") != state.session_id:
            state.error("session_id", f"{filename} session_id 与 manifest 不一致。")
        forbidden = sorted(_find_forbidden_fields(document))
        if forbidden:
            state.error("forbidden_fields", f"{filename} 包含旧字段：{', '.join(forbidden)}")

    if not state.session_id:
        state.error("session_id", "manifest session_id 不能为空。")
    if manifest.get("object_id") != python_session.get("object_id"):
        state.error("object_id", "manifest 与 python_session object_id 不一致。")
    if manifest.get("run_kind") != "formal":
        state.error("run_kind", "正式 Stage 1 只接受 run_kind=formal。")
    if python_session.get("state") != "python_stopped":
        state.error("python_state", "python_session.state 必须为 python_stopped。")
    if not str(manifest.get("config_hash") or ""):
        state.error("config_hash", "manifest config_hash 不能为空。")
    if manifest.get("frozen_parameter_set_id") != manifest.get("config_hash"):
        state.error("frozen_parameter_set", "frozen_parameter_set_id 必须等于整体 config_hash。")
    platform_reference = manifest.get("platform_reference")
    if not isinstance(platform_reference, Mapping) or platform_reference.get("preflight_passed") is not True:
        state.error("reference_preflight", "平台参考预检必须通过。")
    expected_manifest_files = {
        "python_candidates": "python_candidates.jsonl",
        "unity_reference": "unity_reference.jsonl",
        "unity_admission": "unity_admission.jsonl",
        "unity_render": "unity_render.jsonl",
        "unity_events": "unity_events.jsonl",
        "events": "events.jsonl",
    }
    if manifest.get("log_files") != expected_manifest_files:
        state.error("manifest_log_files", "manifest log_files 与固定文件映射不一致。")
    expected_python_files = {
        "python_candidates": "python_candidates.jsonl",
        "python_events": "python_events.jsonl",
    }
    if python_session.get("python_log_filename") != "python_candidates.jsonl":
        state.error("python_log_files", "python_log_filename 必须为 python_candidates.jsonl。")
    if python_session.get("python_events_log_filename") != "python_events.jsonl":
        state.error("python_log_files", "python_events_log_filename 必须为 python_events.jsonl。")
    if python_session.get("log_files") != expected_python_files:
        state.error("python_log_files", "python_session log_files 与固定文件映射不一致。")


def _check_variants(manifest: Mapping[str, Any], state: _QcState) -> dict[str, _VariantRecord]:
    """检查当前九路矩阵、单项消融和两级 FNV 配置哈希。"""

    raw_configs = manifest.get("variant_configs")
    raw_definitions = manifest.get("variant_definitions")
    if not isinstance(raw_configs, list) or not isinstance(raw_definitions, list):
        state.error("variant_manifest", "manifest 必须包含 variant_configs 和 variant_definitions 数组。")
        return {}
    matrix_id = _text(manifest.get("variant_matrix_id"))
    if matrix_id != CURRENT_VARIANT_MATRIX_ID:
        state.error(
            "variant_matrix_id",
            f"variant_matrix_id 必须为 {CURRENT_VARIANT_MATRIX_ID}：{matrix_id or '<empty>'}",
        )
    configs: dict[str, Mapping[str, Any]] = {}
    for item in raw_configs:
        if not isinstance(item, Mapping):
            state.error("variant_config", "variant_configs 每项必须是对象。")
            continue
        label = _text(item.get("label"))
        if not label:
            state.error("variant_config", "variant config label 不能为空。")
            continue
        if label in configs:
            state.error("variant_config", f"variant config label 重复：{label}")
        configs[label] = item
    definition_ids: set[str] = set()
    records: dict[str, _VariantRecord] = {}
    for item in raw_definitions:
        if not isinstance(item, Mapping):
            state.error("variant_definition", "variant_definitions 每项必须是对象。")
            continue
        variant_id = _text(item.get("variant_id"))
        if variant_id in definition_ids:
            state.error("variant_primary_key", f"variant_id 重复：{variant_id}")
        definition_ids.add(variant_id)
        config = configs.get(variant_id)
        expected = FORMAL_VARIANTS.get(variant_id)
        if not variant_id or config is None or expected is None:
            state.error("variant_definition", f"未知或不完整 variant 定义：{variant_id!r}")
            continue
        alignment, *expected_flags = expected
        flag_names = (
            "uses_capture_time_alignment",
            "uses_vcd_admission",
            "uses_temporal_synthesis",
            "uses_static_lock",
            "uses_low_score_reacquire",
            "uses_server_reacquire",
        )
        raw_flags = tuple(item.get(name) for name in flag_names)
        if any(type(value) is not bool for value in raw_flags):
            state.error("variant_bool_type", f"variant 开关必须是 JSON bool：{variant_id}")
        flags = tuple(value if type(value) is bool else False for value in raw_flags)
        if _text(item.get("world_alignment_mode")) != alignment or flags != tuple(expected_flags):
            state.error("variant_matrix", f"variant 开关矩阵与冻结定义不符：{variant_id}")
        method = (
            _text(config.get("motion_model")),
            _text(config.get("smoothing_strategy")),
            _text(config.get("quality_gate")),
        )
        if method != FORMAL_METHODS[variant_id]:
            state.error("variant_method", f"variant 模型、时序策略或门控与冻结定义不符：{variant_id}")
        configuration_fingerprint = _text(config.get("configuration_fingerprint"))
        if not configuration_fingerprint:
            state.error("variant_fingerprint", f"variant 缺少完整参数指纹：{variant_id}")
        computed = variant_config_hash(
            variant_id,
            *method,
            _text(item.get("world_alignment_mode")),
            flags,
            configuration_fingerprint,
        )
        declared = _text(item.get("config_hash"))
        if declared != computed or _text(config.get("config_hash")) != computed:
            state.error("variant_config_hash", f"variant config_hash 无法重算：{variant_id}")
        records[variant_id] = _VariantRecord(
            variant_id,
            _text(config.get("motion_model")),
            _text(config.get("smoothing_strategy")),
            _text(config.get("quality_gate")),
            _text(item.get("world_alignment_mode")),
            flags,
            declared,
            configuration_fingerprint,
        )

    config_ids = frozenset(configs)
    declared_definition_ids = frozenset(definition_ids)
    if config_ids != declared_definition_ids:
        state.error("variant_count", "variant_configs 与 variant_definitions 的 variant 集合不一致。")
    if config_ids != CURRENT_FORMAL_VARIANT_IDS or declared_definition_ids != CURRENT_FORMAL_VARIANT_IDS:
        state.error(
            "variant_count",
            "正式 session 必须完整记录当前九路 variant。",
        )
    if set(records) != set(configs):
        state.error("variant_count", f"存在未知或不完整的 variant：{sorted(set(configs) - set(records))}")
    config_hashes = [_text(item.get("config_hash")) for item in raw_configs if isinstance(item, Mapping)]
    if aggregate_config_hash(config_hashes) != manifest.get("config_hash"):
        state.error("aggregate_config_hash", "整体 config_hash 与 Unity FNV-1a 重算值不一致。")
    labels = manifest.get("variant_labels")
    expected_order = [item.get("label") for item in raw_configs if isinstance(item, Mapping)]
    if labels != expected_order:
        state.error("variant_order", "variant_labels 与 variant_configs 顺序不一致。")
    return records


def _check_common_row(source_row: SourceRow, session_id: str, state: _QcState) -> None:
    """检查所有事实行共享的 session 与事件字段。"""

    row = source_row.data
    forbidden = sorted(_find_forbidden_fields(row))
    if forbidden:
        state.error("forbidden_fields", f"事实行包含旧字段：{', '.join(forbidden)}", source_row)
    if row.get("session_id") != session_id:
        state.error("row_session_id", "事实行 session_id 与 manifest 不一致。", source_row)
    if not _text(row.get("event")):
        state.error("row_event", "事实行 event 不能为空。", source_row)
    if "event_type" in row and row.get("event") != row.get("event_type"):
        state.error("event_name_mismatch", "事件行 event 与 event_type 必须一致。", source_row)


def _check_candidate_id(candidate_id: str, session_id: str, frame_id: int, state: _QcState, row: SourceRow) -> None:
    """检查 candidate_id 的 session:frame:sequence 格式。"""

    parts = candidate_id.rsplit(":", 2)
    if len(parts) != 3:
        state.error("candidate_id", f"candidate_id 格式错误：{candidate_id}", row)
        return
    try:
        candidate_frame = int(parts[1])
        sequence = int(parts[2])
    except ValueError:
        state.error("candidate_id", f"candidate_id frame/sequence 不是整数：{candidate_id}", row)
        return
    if parts[0] != session_id or candidate_frame != frame_id or sequence < 1:
        state.error("candidate_id", f"candidate_id 与 session/frame 不一致：{candidate_id}", row)


def _check_candidate_pose(source_row: SourceRow, state: _QcState) -> None:
    """检查 has_pose candidate 的矩阵、平移与四元数。"""

    row = source_row.data
    if not bool(row.get("has_pose")):
        return
    matrix = row.get("pose_matrix_cv_camera")
    if not _finite_vector(matrix, 16):
        state.error("candidate_pose_matrix", "has_pose candidate 必须包含 16 个有限矩阵值。", source_row)
    position = [row.get(name) for name in ("pose_tx_m", "pose_ty_m", "pose_tz_m")]
    quaternion = [row.get(name) for name in ("pose_qx", "pose_qy", "pose_qz", "pose_qw")]
    if not _finite_vector(position, 3) or not _valid_quaternion(quaternion):
        state.error("candidate_pose", "has_pose candidate 的位置或四元数不可用。", source_row)


def _check_pose_vectors(source_row: SourceRow, position_field: str, rotation_field: str, state: _QcState) -> None:
    """检查一个位置三元组和可归一化四元数。"""

    row = source_row.data
    if not _finite_vector(row.get(position_field), 3):
        state.error("pose_position", f"{position_field} 必须包含三个有限数值。", source_row)
    if not _valid_quaternion(row.get(rotation_field)):
        state.error("pose_quaternion", f"{rotation_field} 必须是可归一化四元数。", source_row)


def _check_scores(source_row: SourceRow, state: _QcState) -> None:
    """检查所有已知评分字段位于 [0, 1]；颜色不可用允许 null 或负值。"""

    row = source_row.data
    for field in SCORE_FIELDS:
        value = row.get(field)
        if value is None:
            continue
        number = _finite_float(value)
        if number is None:
            state.error("score_finite", f"评分字段 {field} 不是有限数值。", source_row)
            continue
        if field == "color_projection_score" and number < 0.0:
            continue
        if number < 0.0 or number > 1.0:
            state.error("score_range", f"评分字段 {field} 超出 [0, 1]：{number}", source_row)


def _check_variant_row(
    source_row: SourceRow,
    expected: _VariantRecord | None,
    state: _QcState,
    *,
    admission: bool,
) -> None:
    """检查 admission/render 行的配置字段与 manifest 完全一致。"""

    if expected is None:
        return
    row = source_row.data
    for field, expected_value in (
        ("variant_label", expected.variant_id),
        ("motion_model", expected.motion_model),
        ("smoothing_strategy", expected.smoothing_strategy),
        ("quality_gate", expected.quality_gate),
        ("config_hash", expected.config_hash),
    ):
        if row.get(field) != expected_value:
            state.error("variant_row_config", f"{expected.variant_id} 的 {field} 与 manifest 不一致。", source_row)
    if admission:
        alignment = expected.world_alignment_mode
        capture, vcd, temporal, static, _, _ = expected.flags
        for field, matrix_value in (
            ("world_alignment_mode", alignment),
            ("uses_capture_time_alignment", capture),
            ("uses_vcd_admission", vcd),
            ("uses_temporal_synthesis", temporal),
            ("uses_static_lock", static),
        ):
            if row.get(field) != matrix_value:
                state.error("variant_row_matrix", f"{expected.variant_id} 的 {field} 与冻结矩阵不一致。", source_row)


def _check_smoothing_diagnostics(
    source_row: SourceRow,
    expected: _VariantRecord | None,
    continuity_reset_counts: dict[str, int],
    state: _QcState,
) -> None:
    """检查因果预测专用诊断的空值、范围和累计计数语义。"""

    if expected is None:
        return
    row = source_row.data
    horizon = _finite_float(row.get("prediction_horizon_ms"))
    position_residual = _finite_float(row.get("correction_position_residual_m"))
    rotation_residual = _finite_float(row.get("correction_rotation_residual_deg"))
    reset_count = _integer(row.get("continuity_reset_count"))
    is_causal = expected.smoothing_strategy == "causal_prediction"

    if is_causal:
        configured_horizon_ms = _configured_prediction_horizon_ms(expected.configuration_fingerprint)
        configured_half_life_ms = _configured_correction_half_life_ms(expected.configuration_fingerprint)
        if configured_horizon_ms is None:
            state.error("causal_prediction_config", "因果预测配置指纹缺少有效 horizon。", source_row)
        elif horizon is None or not 0.0 <= horizon <= configured_horizon_ms + 0.001:
            state.error(
                "causal_prediction_horizon",
                f"因果预测时域必须位于 [0, {configured_horizon_ms}] ms：{horizon}",
                source_row,
            )
        if configured_half_life_ms is None:
            state.error("causal_prediction_config", "因果预测配置指纹缺少有效 correction-half-life。", source_row)
        if position_residual is None or position_residual < 0.0:
            state.error("causal_correction_residual", "位置校正残差必须是非负有限值。", source_row)
        if rotation_residual is None or rotation_residual < 0.0:
            state.error("causal_correction_residual", "旋转校正残差必须是非负有限值。", source_row)
    elif any(value is not None for value in (horizon, position_residual, rotation_residual)):
        state.error("causal_diagnostics_scope", "非因果预测策略的专用浮点诊断必须为 null。", source_row)

    if reset_count is None or reset_count < 0:
        state.error("continuity_reset_count", "连续性异常重置计数必须是非负整数。", source_row)
        return
    if not is_causal and reset_count != 0:
        state.error("causal_diagnostics_scope", "非因果预测策略的连续性异常重置计数必须为 0。", source_row)
    previous = continuity_reset_counts.get(expected.variant_id)
    if previous is not None and reset_count < previous:
        state.error("continuity_reset_count", "连续性异常重置计数必须在 session 内单调不减。", source_row)
    continuity_reset_counts[expected.variant_id] = reset_count


def _configured_prediction_horizon_ms(configuration_fingerprint: str) -> float | None:
    """从完整配置指纹读取因果预测时域并换算为毫秒。"""

    for part in configuration_fingerprint.split("|"):
        if not part.startswith("horizon:"):
            continue
        horizon_seconds = _finite_float(part.removeprefix("horizon:"))
        if horizon_seconds is not None and horizon_seconds >= 0.0:
            return horizon_seconds * 1000.0
    return None


def _configured_correction_half_life_ms(configuration_fingerprint: str) -> float | None:
    """从完整配置指纹读取因果校正残差半衰期并换算为毫秒。"""

    for part in configuration_fingerprint.split("|"):
        if not part.startswith("correction-half-life:"):
            continue
        half_life_seconds = _finite_float(part.removeprefix("correction-half-life:"))
        if half_life_seconds is not None and half_life_seconds > 0.0:
            return half_life_seconds * 1000.0
    return None


def _check_render_reference_warmup(
    unknown_rows: list[SourceRow],
    reference_frames: set[int],
    reference_times: Mapping[int, float],
    state: _QcState,
) -> None:
    """只允许首条 reference 之前且内嵌参考有效的启动 warmup render 行。"""

    if not unknown_rows:
        return
    if not reference_frames or not reference_times:
        for unknown_row in unknown_rows:
            state.error("render_reference_fk", "render source_frame_id 没有 reference。", unknown_row)
        return
    first_frame = min(reference_frames)
    first_capture = reference_times.get(first_frame, min(reference_times.values()))
    for source_row in unknown_rows:
        source_data = source_row.data
        frame_id = _integer(source_data.get("source_frame_id"))
        capture = _finite_float(source_data.get("source_capture_mono_ms"))
        allowed = (
            frame_id is not None
            and frame_id < first_frame
            and capture is not None
            and capture < first_capture
            and bool(source_data.get("reference_pose_valid"))
        )
        if not allowed:
            state.error("render_reference_fk", f"render source_frame_id 没有 reference：{frame_id}", source_row)


def _check_writer_stats(dataset: TaskDataset, row_counts: Mapping[str, int], state: _QcState) -> None:
    """合并两端停止态统计并核对真实行数、丢行和写入失败。"""

    python_stats = dataset.python_session.get("log_writer_stats")
    manifest_stats = dataset.manifest.get("log_writer_stats")
    if not isinstance(python_stats, Mapping) or not isinstance(manifest_stats, Mapping):
        state.error("writer_stats", "两端 log_writer_stats 必须是对象。")
        return

    for filename in ("python_candidates.jsonl", "python_events.jsonl"):
        _check_single_writer(
            filename,
            python_stats.get(filename),
            row_counts.get(filename, 0),
            state,
            is_python=True,
        )
    for filename in ("unity_reference.jsonl", "unity_admission.jsonl", "unity_render.jsonl"):
        _check_single_writer(
            filename,
            manifest_stats.get(filename),
            row_counts.get(filename, 0),
            state,
            is_python=False,
        )

    event_stats = manifest_stats.get("events.jsonl")
    unity_event_stats = event_stats.get("unity") if isinstance(event_stats, Mapping) else None
    _check_single_writer(
        "unity_events.jsonl",
        unity_event_stats,
        row_counts.get("unity_events.jsonl", 0),
        state,
        is_python=False,
    )
    expected_merged = row_counts.get("python_events.jsonl", 0) + row_counts.get("unity_events.jsonl", 0)
    if row_counts.get("events.jsonl", 0) != expected_merged:
        state.error("events_row_count", "events.jsonl 行数不等于两个事件分片之和。")


def _check_single_writer(
    filename: str,
    stats: Any,
    actual_rows: int,
    state: _QcState,
    *,
    is_python: bool,
) -> None:
    """核对一个 writer 的停止态行数、丢行和错误字段。"""

    if not isinstance(stats, Mapping):
        state.error("writer_stats", f"缺少 {filename} writer 统计。")
        return
    rows_written = _integer(stats.get("rows_written"))
    dropped_rows = _integer(stats.get("dropped_rows"))
    if rows_written is None or rows_written < 0:
        state.error("writer_stats_type", f"{filename} rows_written 必须是非负整数。")
    if dropped_rows is None or dropped_rows < 0:
        state.error("writer_stats_type", f"{filename} dropped_rows 必须是非负整数。")
    if rows_written != actual_rows:
        state.error("writer_row_count", f"{filename} 实际行数 {actual_rows} 与 writer 统计不一致。")
    if dropped_rows != 0:
        state.error("writer_dropped_rows", f"{filename} dropped_rows 必须为 0。")
    if is_python:
        failures = _integer(stats.get("log_write_failures"))
        if failures is None or failures < 0:
            state.error("writer_stats_type", f"{filename} log_write_failures 必须是非负整数。")
        if failures != 0:
            state.error("writer_failures", f"{filename} log_write_failures 必须为 0。")
    else:
        if "write_error" not in stats or not isinstance(stats.get("write_error"), str):
            state.error("writer_stats_type", f"{filename} write_error 必须是字符串。")
        if str(stats.get("write_error") or ""):
            state.error("writer_failures", f"{filename} write_error 必须为空。")


def _check_event_merge(
    dataset: TaskDataset,
    fragment_events: list[tuple[int, Mapping[str, Any]]],
    state: _QcState,
) -> None:
    """按冻结全序重建事件文本并与现有 events.jsonl 逐字节比较。"""

    expected = merged_event_text(fragment_events)
    try:
        actual = (dataset.root / "events.jsonl").read_text(encoding="utf-8")
    except OSError as exc:
        state.error("events_merge", f"无法读取 events.jsonl：{exc}")
        return
    if actual != expected:
        state.error("events_merge", "events.jsonl 不是 Python/Unity 分片的确定性合并结果。")


def _check_trial_lifecycle(
    manifest: Mapping[str, Any],
    unity_events: list[SourceRow],
    state: _QcState,
) -> None:
    """核对最终完成 trial 的唯一生命周期、marker 和场景角色。"""

    groups: dict[tuple[str, str, str], list[SourceRow]] = defaultdict(list)
    for source_row in unity_events:
        row = source_row.data
        trial_id = _text(row.get("trial_id"))
        if trial_id:
            key = (
                _text(row.get("experiment_id")),
                _text(row.get("scenario_id")),
                trial_id,
            )
            groups[key].append(source_row)

    completed: set[tuple[str, str, str]] = set()
    for key, rows in groups.items():
        rows.sort(key=lambda item: float(item.data.get("mono_ms", 0.0)))
        starts = [item for item in rows if _event_name(item.data) == "trial_started"]
        ends = [item for item in rows if _event_name(item.data) == "trial_ended"]
        if len(starts) == 1 and len(ends) == 1:
            end_time = float(ends[0].data.get("mono_ms", 0.0))
            rejected_after = any(
                _event_name(item.data) == "trial_rejected"
                and float(item.data.get("mono_ms", 0.0)) > end_time
                for item in rows
            )
            if not rejected_after:
                completed.add(key)

    manifest_completed: set[tuple[str, str, str]] = set()
    raw_completed = manifest.get("completed_tasks")
    trial_plan = manifest.get("trial_plan")
    if not isinstance(raw_completed, list):
        state.error("completed_tasks", "manifest completed_tasks 必须是数组。")
        return
    if not isinstance(trial_plan, list) or not trial_plan:
        state.error("trial_plan", "manifest trial_plan 必须是非空数组。")
        return
    completed_task_numbers: set[int] = set()
    for item in raw_completed:
        if not isinstance(item, Mapping):
            state.error("completed_tasks", "completed_tasks 每项必须是对象。")
            continue
        task_number = _integer(item.get("task_number"))
        if task_number is None or task_number < 1 or task_number > len(trial_plan):
            state.error("completed_task_number", f"completed task_number 超出 trial_plan：{task_number}")
        elif task_number in completed_task_numbers:
            state.error("completed_task_number", f"completed task_number 重复：{task_number}")
        else:
            completed_task_numbers.add(task_number)
            planned = trial_plan[task_number - 1]
            if not isinstance(planned, Mapping) or (
                planned.get("experiment_id") != item.get("experiment_id")
                or planned.get("scenario_id") != item.get("scenario_id")
            ):
                state.error("completed_task_plan", f"completed task 与 trial_plan 不一致：{task_number}")
        manifest_completed.add(
            (
                _text(item.get("experiment_id")),
                _text(item.get("scenario_id")),
                _text(item.get("trial_id")),
            )
        )
    if completed != manifest_completed:
        state.error(
            "completed_trials",
            f"事件重建完成集合与 manifest 不一致：events={sorted(completed)}, manifest={sorted(manifest_completed)}",
        )

    for key in manifest_completed:
        rows = sorted(groups.get(key, []), key=lambda item: float(item.data.get("mono_ms", 0.0)))
        starts = [item for item in rows if _event_name(item.data) == "trial_started"]
        ends = [item for item in rows if _event_name(item.data) == "trial_ended"]
        if len(starts) != 1 or len(ends) != 1:
            state.error("trial_lifecycle", f"完成 trial 必须恰有一个 started/ended：{key}")
            continue
        if float(starts[0].data.get("mono_ms", 0.0)) >= float(ends[0].data.get("mono_ms", 0.0)):
            state.error("trial_lifecycle", f"trial_started 必须早于 trial_ended：{key}")
        markers = [item for item in rows if _event_name(item.data) == "event_marker"]
        if not markers:
            state.error("trial_markers", f"完成 trial 至少需要一个 marker：{key}")
            continue
        marker_ids = [_text(item.data.get("event_id")) for item in markers]
        if len(marker_ids) != len(set(marker_ids)) or any(not event_id for event_id in marker_ids):
            state.error("marker_event_id", f"marker event_id 必须非空且 trial 内唯一：{key}")
        roles = [_text((item.data.get("payload") or {}).get("event_role")) for item in markers]
        scenario_id = key[1]
        if scenario_id == "start_stop_6dof":
            expected_roles = [
                "transition_started" if index % 2 == 0 else "transition_stopped"
                for index in range(len(roles))
            ]
            if roles != expected_roles or len(roles) % 2 != 0:
                state.error("transition_event_sequence", f"起停角色未严格交替闭合：{roles}")
        if scenario_id == "occlusion_recovery":
            expected_roles = [
                "occlusion_started" if index % 2 == 0 else "target_visible"
                for index in range(len(roles))
            ]
            if roles != expected_roles or len(roles) % 2 != 0:
                state.error("occlusion_event_sequence", f"遮挡角色未严格交替闭合：{roles}")

    state.metrics["completed_trial_count"] = len(completed)


def _event_name(row: Mapping[str, Any]) -> str:
    """读取事件行的稳定事件名称。"""

    return _text(row.get("event") or row.get("event_type"))


def _finite_vector(value: Any, length: int) -> bool:
    """判断值是否为指定长度的有限数值序列。"""

    if not isinstance(value, (list, tuple)) or len(value) != length:
        return False
    return all(_finite_float(item) is not None for item in value)


def _valid_quaternion(value: Any) -> bool:
    """判断四元数有限且范数非零，因此可安全归一化。"""

    if not _finite_vector(value, 4):
        return False
    norm = math.sqrt(sum(float(item) * float(item) for item in value))
    return math.isfinite(norm) and norm > 1e-8


def _finite_float(value: Any) -> float | None:
    """把数值转换为有限 float，布尔和非法值返回 None。"""

    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _integer(value: Any) -> int | None:
    """只接受整数或整数值浮点数，布尔和其他值返回 None。"""

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _text(value: Any) -> str:
    """把空值转换为空字符串，其余值转换为字符串。"""

    return "" if value is None else str(value)


def _find_forbidden_fields(value: Any, *, prefix: str = "") -> set[str]:
    """递归收集旧字段前缀和旧根字段名称。"""

    found: set[str] = set()
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key)
            path = f"{prefix}.{key}" if prefix else key
            lowered = key.lower()
            if lowered.startswith(FORBIDDEN_FIELD_PREFIXES) or lowered in FORBIDDEN_FIELD_NAMES:
                found.add(path)
            found.update(_find_forbidden_fields(item, prefix=path))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found.update(_find_forbidden_fields(item, prefix=f"{prefix}[{index}]"))
    return found


def _fnv1a(data: bytes) -> str:
    """计算 Unity 使用的 64 位 FNV-1a 十六进制摘要。"""

    value = 14695981039346656037
    for byte in data:
        value ^= byte
        value = (value * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return f"{value:016x}"


__all__ = [
    "FORMAL_VARIANTS",
    "QcIssue",
    "StageOneQcReport",
    "aggregate_config_hash",
    "run_task_qc",
    "variant_config_hash",
]

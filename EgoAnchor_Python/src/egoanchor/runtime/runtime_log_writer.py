"""TrackingRuntime 结构化日志写入器。"""

from __future__ import annotations

import math
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from egoanchor.diagnostics import RuntimeEventLogger
from egoanchor.eval.schema_v2 import JsonlTableWriter, PythonCandidateRow
from egoanchor.utils import clamp, get_logger, rotation_matrix_to_quaternion
from .eval_session import update_python_session_metadata
from .runtime_state import RuntimeState

LOGGER = get_logger(__name__, component="RuntimeLogWriter")
"""runtime 结构化日志写入器自身的诊断日志。"""


def _optional_error_code(message: object, field_name: str) -> str:
    """按 Protobuf presence 读取可选 ErrorInfo.code。"""

    has_field = getattr(message, "HasField", None)
    if callable(has_field):
        try:
            if not bool(has_field(field_name)):
                return ""
        except ValueError:
            return _error_code_from_attribute(message, field_name)

    return _error_code_from_attribute(message, field_name)


def _error_code_from_attribute(message: object, field_name: str) -> str:
    """从普通对象属性读取 ErrorInfo.code，兼容单测替身对象。"""

    error = getattr(message, field_name, None)
    return str(getattr(error, "code", "") or "") if error is not None else ""


class PoseLogFactory:
    """从 PoseResult 中提取论文实验与诊断需要的 pose 字段。"""

    def __init__(self) -> None:
        """初始化上一帧 pose 缓存，用于计算相邻 jump。"""

        self.last_pose_matrix: tuple[float, ...] | None = None

    def build(self, msg: object) -> dict[str, float | list[float]]:
        """提取 pose 平移、旋转和相邻 jump。"""

        if not bool(getattr(msg, "has_pose", False)):
            self.last_pose_matrix = None
            return {}
        matrix = getattr(getattr(msg, "pose_matrix_cv_camera", None), "values", None)
        values = self._finite_pose_matrix(matrix)
        if values is None:
            self.last_pose_matrix = None
            return {}

        tx, ty, tz = values[3], values[7], values[11]
        qx, qy, qz, qw = rotation_matrix_to_quaternion(values)
        jump_t = 0.0
        jump_r = 0.0
        if self.last_pose_matrix is not None:
            prev = self.last_pose_matrix
            dx = tx - prev[3]
            dy = ty - prev[7]
            dz = tz - prev[11]
            jump_t = (dx * dx + dy * dy + dz * dz) ** 0.5
            pqx, pqy, pqz, pqw = rotation_matrix_to_quaternion(prev)
            dot = abs(qx * pqx + qy * pqy + qz * pqz + qw * pqw)
            dot = clamp(dot, -1.0, 1.0)
            jump_r = math.degrees(2.0 * math.acos(dot))
        self.last_pose_matrix = values
        return {
            "pose_tx_m": tx,
            "pose_ty_m": ty,
            "pose_tz_m": tz,
            "pose_distance_m": (tx * tx + ty * ty + tz * tz) ** 0.5,
            "pose_qx": qx,
            "pose_qy": qy,
            "pose_qz": qz,
            "pose_qw": qw,
            "pose_matrix_cv_camera": list(values),
            "pose_jump_translation_m": jump_t,
            "pose_jump_rotation_deg": jump_r,
        }

    @staticmethod
    def _finite_pose_matrix(matrix: object) -> tuple[float, ...] | None:
        """读取 4x4 pose 矩阵；长度错误或非有限值会丢弃该 pose 日志字段。"""

        if matrix is None:
            return None
        try:
            values = tuple(float(v) for v in matrix)  # type: ignore[union-attr]
        except (TypeError, ValueError):
            return None
        if len(values) != 16:
            return None
        return values if all(math.isfinite(value) for value in values) else None


class RuntimeLogWriter:
    """集中维护 TrackingRuntime JSONL 事件字段。

    TrackingRuntime 只决定何时发生事件，本类决定事件写入哪些结构化字段，
    避免主循环文件混入 pose/status/heartbeat/command 的日志装配细节。
    """

    def __init__(self, cfg: SimpleNamespace, *, session_id: str, eval_session: object | None = None) -> None:
        """读取 runtime.logging 配置并创建底层事件日志器。"""

        self.logger = self._build_event_logger(cfg, session_id=session_id, eval_session=eval_session)
        """底层 JSONL 事件日志器。"""

        self._eval_session = eval_session
        """共享 eval session；关闭时回写 Python writer 统计片段。"""

        self.pose_results = self._flag(cfg, "log_pose_results", True)
        """是否记录 PoseResult 摘要事件。"""

        self.status_events = self._flag(cfg, "log_status_events", True)
        """是否记录 AnchorStatusEvent 摘要事件。"""

        self.heartbeats = self._flag(cfg, "log_heartbeats", True)
        """是否记录 ServerHeartbeat 摘要事件。"""

        self.commands = self._flag(cfg, "log_commands", True)
        """是否记录 runtime command 执行动作。"""

        self.pose_factory = PoseLogFactory()
        """PoseResult 额外 pose 字段构造器。"""

        self.log_write_failures = 0
        """JSONL 写入失败次数；日志写入失败不应阻断实时链路。"""

        self._candidate_write_failures = 0
        """python_candidates.jsonl 的独立写入失败次数。"""

        self._event_write_failures = 0
        """python_events.jsonl 的独立写入失败次数。"""

        self._candidate_sequences_by_frame: dict[int, int] = {}
        """每个 frame_id 独立计数的 candidate 序号，避免跨端启动时间影响 ID。"""

        self._schema_candidates: JsonlTableWriter | None = None
        self._schema_events: JsonlTableWriter | None = None
        # 与旧日志开关保持一致：关闭 runtime 日志时不创建评估产物。
        if eval_session is not None and self.logger.enabled:
            session_dir = Path(getattr(eval_session, "session_dir"))
            self._schema_candidates = JsonlTableWriter(session_dir / "python_candidates.jsonl", expected_event="python_candidate")
            self._schema_events = JsonlTableWriter(session_dir / "python_events.jsonl")

    def close(self) -> None:
        """逐项关闭日志，并始终尝试回写 schema-v2 最终统计。"""

        try:
            self.logger.close()
        except Exception as exc:  # pragma: no cover - 依赖底层文件系统故障
            self.log_write_failures += 1
            LOGGER.error("关闭 runtime event logger 失败：%s", exc)

        if self._schema_candidates is not None:
            try:
                self._schema_candidates.close()
            except Exception as exc:  # pragma: no cover - 依赖底层文件系统故障
                self.log_write_failures += 1
                self._candidate_write_failures += 1
                LOGGER.error("关闭 python_candidates.jsonl 失败：%s", exc)

        if self._schema_events is not None:
            try:
                self._schema_events.close()
            except Exception as exc:  # pragma: no cover - 依赖底层文件系统故障
                self.log_write_failures += 1
                self._event_write_failures += 1
                LOGGER.error("关闭 python_events.jsonl 失败：%s", exc)

        if self._eval_session is not None and hasattr(self._eval_session, "metadata_path"):
            try:
                update_python_session_metadata(
                    self._eval_session,
                    state="python_stopped",
                    log_writer_stats=self.schema_writer_stats,
                )
            except Exception as exc:  # pragma: no cover - 依赖底层文件系统故障
                self.log_write_failures += 1
                LOGGER.error(
                    "写入 python_session.json 最终停止态失败；本 session 将被 QC 拒绝：%s",
                    exc,
                )

    @property
    def schema_writer_stats(self) -> dict[str, dict[str, int]]:
        """返回 Python schema-v2 文件的真实写入、丢弃和失败统计。"""

        stats: dict[str, dict[str, int]] = {}
        if self._schema_candidates is not None:
            stats["python_candidates.jsonl"] = {
                "rows_written": self._schema_candidates.rows_written,
                "dropped_rows": self._schema_candidates.dropped_rows,
                "log_write_failures": self._candidate_write_failures,
            }
        if self._schema_events is not None:
            stats["python_events.jsonl"] = {
                "rows_written": self._schema_events.rows_written,
                "dropped_rows": self._schema_events.dropped_rows,
                "log_write_failures": self._event_write_failures,
            }
        return stats

    def event(self, event_type: str, **fields: Any) -> None:
        """写入一条含固定字段和 payload 的 schema-v2 runtime 事件。"""

        try:
            if self._schema_events is not None:
                event_fields = dict(fields)
                payload = dict(event_fields.pop("payload", {}) or {})
                reserved = {
                    "schema_version",
                    "event",
                    "event_type",
                    "session_id",
                    "source",
                    "created_unix_ms",
                    "mono_ms",
                    "unity_frame",
                    "severity",
                    "experiment_id",
                    "scenario_id",
                    "trial_id",
                    "event_id",
                    "variant_id",
                    "message",
                }
                payload.update({key: value for key, value in event_fields.items() if key not in reserved})
                row = {
                    "schema_version": 2,
                    "event": str(event_type),
                    "event_type": str(event_type),
                    "session_id": self.logger.session_id,
                    "source": str(event_fields.get("source", "python_runtime")),
                    "created_unix_ms": float(event_fields.get("created_unix_ms", time.time() * 1000.0)),
                    "mono_ms": float(event_fields.get("mono_ms", time.monotonic() * 1000.0)),
                    "unity_frame": int(event_fields.get("unity_frame", -1)),
                    "severity": str(event_fields.get("severity", _event_severity(event_type))),
                    "experiment_id": str(event_fields.get("experiment_id", "")),
                    "scenario_id": str(event_fields.get("scenario_id", "")),
                    "trial_id": str(event_fields.get("trial_id", "")),
                    "event_id": str(event_fields.get("event_id", "")),
                    "variant_id": str(event_fields.get("variant_id", "")),
                    "message": str(event_fields.get("message", "")),
                    "payload": payload,
                }
                self._schema_events.write(row)
            else:
                self.logger.write(event_type, **fields)
        except Exception as exc:
            self.log_write_failures += 1
            if self._schema_events is not None:
                self._event_write_failures += 1
            if self._should_report_log_failure():
                LOGGER.warning("runtime JSONL 写入失败，已跳过 event=%s failures=%d：%s", event_type, self.log_write_failures, exc)

    def pose_result(self, msg: object, *, state: RuntimeState, diagnostics: object | None = None) -> None:
        """记录 PoseResult 的论文相关摘要字段。

        `diagnostics` 是不进入 Protobuf 的 runtime 旁路，用于保存渲染质量等
        Python-only 诊断量，便于离线分析 score 分布和渲染质量开销。
        """

        if not self.pose_results:
            return
        timing = getattr(msg, "timing", SimpleNamespace())
        fields = dict(
            frame_id=int(msg.header.frame_id),
            state=state.value,
            has_pose=bool(msg.has_pose),
            phase=str(msg.phase),
            stage=int(msg.stage),
            pose_source=str(msg.pose_source),
            pose_score=float(msg.reliability_score),
            reliability_flags=list(msg.reliability_flags),
            depth_valid_ratio=float(msg.depth_valid_ratio),
            depth_valid_in_mask=float(msg.depth_valid_in_mask),
            mask_area_ratio=float(msg.mask_area_ratio),
            det_count=int(msg.det_count),
            fps=float(msg.fps),
            total_ms=float(getattr(timing, "total_ms", 0.0)),
            yolo_ms=float(getattr(timing, "yolo_ms", 0.0)),
            depth_ms=float(getattr(timing, "depth_ms", 0.0)),
            cutie_ms=float(getattr(timing, "cutie_ms", 0.0)),
            pose_ms=float(getattr(timing, "pose_ms", 0.0)),
            server_receive_mono_ms=float(getattr(msg, "server_receive_mono_ms", 0.0)),
            server_publish_mono_ms=float(getattr(msg, "server_publish_mono_ms", 0.0)),
        )
        if diagnostics is not None:
            fields.update(
                score_reprojection=float(getattr(diagnostics, "score_reprojection", 0.0)),
                score_depth=float(getattr(diagnostics, "score_depth", 0.0)),
                score_mask=float(getattr(diagnostics, "score_mask", 0.0)),
                color_reprojection=float(getattr(diagnostics, "color_reprojection", -1.0)),
                render_quality_evaluated=bool(getattr(diagnostics, "render_quality_evaluated", False)),
                render_quality_status=str(getattr(diagnostics, "render_quality_status", "")),
                render_quality_mask_iou=float(getattr(diagnostics, "render_quality_mask_iou", 0.0)),
                render_quality_area_ratio_score=float(getattr(diagnostics, "render_quality_area_ratio_score", 0.0)),
                render_quality_render_visible_ratio=float(getattr(diagnostics, "render_quality_render_visible_ratio", 0.0)),
                render_quality_observed_visible_ratio=float(getattr(diagnostics, "render_quality_observed_visible_ratio", 0.0)),
                render_quality_render_area_px=int(getattr(diagnostics, "render_quality_render_area_px", 0)),
                render_quality_depth_inlier=float(getattr(diagnostics, "render_quality_depth_inlier", 0.0)),
                render_quality_depth_alignment=float(getattr(diagnostics, "render_quality_depth_alignment", 0.0)),
                render_quality_depth_absolute=float(getattr(diagnostics, "render_quality_depth_absolute", 0.0)),
                render_quality_depth_structural=float(getattr(diagnostics, "render_quality_depth_structural", 0.0)),
                render_quality_depth_alpha=float(getattr(diagnostics, "render_quality_depth_alpha", 0.0)),
                render_quality_depth_residual_m=float(getattr(diagnostics, "render_quality_depth_residual_m", 0.0)),
                render_quality_ms=float(getattr(diagnostics, "render_quality_ms", 0.0)),
            )
        fields.update(self.pose_factory.build(msg))
        if self._schema_candidates is not None:
            frame_id = int(fields["frame_id"])
            candidate_seq = self._next_candidate_sequence(frame_id)
            row = self._build_candidate_row(
                msg,
                fields=fields,
                diagnostics=diagnostics,
                candidate_seq=candidate_seq,
            )
            try:
                self._schema_candidates.write(row)
            except Exception as exc:
                self.log_write_failures += 1
                self._candidate_write_failures += 1
                if self._should_report_log_failure():
                    LOGGER.warning("schema-v2 candidate 写入失败 frame=%s：%s", fields.get("frame_id"), exc)
        else:
            self.event("pose_result", **fields)

    def _build_candidate_row(
        self,
        msg: object,
        *,
        fields: dict[str, Any],
        diagnostics: object | None,
        candidate_seq: int,
    ) -> PythonCandidateRow:
        """把 PoseResult 和旁路诊断映射为严格 schema-v2 候选行。"""

        color_score = _optional_score(diagnostics, "color_reprojection", default=-1.0)
        flags = [str(flag) for flag in getattr(msg, "reliability_flags", ())]
        if color_score < 0.0 and "color_signal_unavailable" not in flags:
            flags.append("color_signal_unavailable")
        pose_fields = {
            key: fields.get(key)
            for key in (
                "pose_matrix_cv_camera",
                "pose_tx_m",
                "pose_ty_m",
                "pose_tz_m",
                "pose_qx",
                "pose_qy",
                "pose_qz",
                "pose_qw",
            )
        }
        render_diagnostics = {
            key: fields[key]
            for key in (
                "render_quality_evaluated",
                "render_quality_status",
                "render_quality_mask_iou",
                "render_quality_area_ratio_score",
                "render_quality_render_visible_ratio",
                "render_quality_observed_visible_ratio",
                "render_quality_render_area_px",
                "render_quality_depth_inlier",
                "render_quality_depth_alignment",
                "render_quality_depth_absolute",
                "render_quality_depth_structural",
                "render_quality_depth_alpha",
                "render_quality_depth_residual_m",
                "render_quality_ms",
            )
            if key in fields
        }
        failure_reason = str(
            getattr(diagnostics, "failure_reason", "")
            or getattr(msg, "failure_reason", "")
            or ""
        )
        return PythonCandidateRow(
            session_id=self.logger.session_id,
            frame_id=int(fields["frame_id"]),
            candidate_id=f"{self.logger.session_id}:{fields['frame_id']}:{candidate_seq}",
            server_receive_mono_ms=float(fields["server_receive_mono_ms"]),
            server_publish_mono_ms=float(fields["server_publish_mono_ms"]),
            has_pose=bool(fields["has_pose"]),
            pose_matrix_cv_camera=pose_fields["pose_matrix_cv_camera"],
            pose_tx_m=pose_fields["pose_tx_m"],
            pose_ty_m=pose_fields["pose_ty_m"],
            pose_tz_m=pose_fields["pose_tz_m"],
            pose_qx=pose_fields["pose_qx"],
            pose_qy=pose_fields["pose_qy"],
            pose_qz=pose_fields["pose_qz"],
            pose_qw=pose_fields["pose_qw"],
            pose_source=str(fields["pose_source"]),
            phase=str(fields["phase"]),
            stage=int(fields["stage"]),
            failure_reason=failure_reason,
            reliability_flags=flags,
            vcd_score=_optional_score(msg, "reliability_score"),
            visibility_score=_optional_score(diagnostics, "score_mask"),
            geometry_core_score=_optional_score(diagnostics, "geometry_core_score"),
            color_projection_score=None if color_score < 0.0 else color_score,
            depth_alignment_score=_optional_score(diagnostics, "score_depth"),
            depth_abs_score=_optional_score(diagnostics, "render_quality_depth_absolute"),
            depth_struct_score=_optional_score(diagnostics, "render_quality_depth_structural"),
            depth_alpha=_optional_score(diagnostics, "render_quality_depth_alpha"),
            render_diagnostics=render_diagnostics,
            total_ms=float(fields["total_ms"]),
            yolo_ms=float(fields["yolo_ms"]),
            depth_ms=float(fields["depth_ms"]),
            cutie_ms=float(fields["cutie_ms"]),
            pose_ms=float(fields["pose_ms"]),
        )

    def _next_candidate_sequence(self, frame_id: int) -> int:
        """为 frame_id 分配从 1 开始的稳定序号。"""

        sequence = self._candidate_sequences_by_frame.get(frame_id, 0) + 1
        self._candidate_sequences_by_frame[frame_id] = sequence
        return sequence

    def status(self, status: object, *, previous: RuntimeState) -> None:
        """记录 AnchorStatusEvent 的状态迁移摘要。"""

        if not self.status_events:
            return
        self.event(
            "status_event",
            previous_state=previous.value,
            state=str(status.state),
            status_event=str(status.event),
            message=str(status.message),
            request_id=str(status.header.request_id),
            frame_id=int(status.header.frame_id),
            error_code=_optional_error_code(status, "error"),
        )

    def heartbeat(self, heartbeat: object) -> None:
        """记录 ServerHeartbeat 的低频健康状态摘要。"""

        if not self.heartbeats:
            return
        self.event(
            "server_heartbeat",
            state=str(heartbeat.state),
            input_ready=bool(heartbeat.input_ready),
            latest_stereo_frame_id=int(heartbeat.latest_stereo_frame_id),
            camera_info_version=int(heartbeat.camera_info_version),
            runtime_fps=float(heartbeat.runtime_fps),
            publish_fps=float(heartbeat.publish_fps),
            command_queue_length=int(heartbeat.command_queue_length),
            error_code=_optional_error_code(heartbeat, "last_error"),
        )

    def command_execution(self, command: object, result: object, queue_length: int) -> None:
        """记录 runtime 线程实际执行 command 的时间点和动作。"""

        if not self.commands:
            return
        self.event(
            "command_executed",
            command_type=command.command_type.value,
            request_id=command.request_id,
            anchor_id=command.anchor_id,
            queued_mono_ms=float(command.created_mono_ms),
            paused=result.paused,
            stage=result.stage,
            reset_tracking=bool(result.reset_tracking),
            queue_length=queue_length,
        )

    @staticmethod
    def _build_event_logger(cfg: SimpleNamespace, *, session_id: str, eval_session: object | None = None) -> RuntimeEventLogger:
        """根据 TOML 配置创建结构化事件日志器。"""

        logging_cfg = getattr(getattr(cfg, "runtime", SimpleNamespace()), "logging", SimpleNamespace())
        if eval_session is not None:
            output_dir = Path(getattr(eval_session, "session_dir"))
            filename = "python_events.jsonl"
        else:
            python_root = Path(getattr(getattr(cfg, "paths", SimpleNamespace()), "python_root", Path.cwd()))
            raw_output_dir = Path(str(getattr(logging_cfg, "output_dir", "data/runtime_logs"))).expanduser()
            output_dir = raw_output_dir if raw_output_dir.is_absolute() else python_root / raw_output_dir
            filename = str(getattr(logging_cfg, "filename", ""))
        return RuntimeEventLogger(
            enabled=bool(getattr(logging_cfg, "enabled", True)),
            output_dir=output_dir,
            session_id=session_id,
            filename=filename,
            flush_every=int(getattr(logging_cfg, "flush_every", 1)),
        )

    @staticmethod
    def _flag(cfg: SimpleNamespace, name: str, default: bool) -> bool:
        """读取 runtime.logging 中的布尔开关。"""

        logging_cfg = getattr(getattr(cfg, "runtime", SimpleNamespace()), "logging", SimpleNamespace())
        return bool(getattr(logging_cfg, name, default))

    def _should_report_log_failure(self) -> bool:
        """按指数式间隔报告日志写入失败，避免磁盘故障时刷屏。"""

        count = self.log_write_failures
        return count <= 3 or count in (10, 100) or count % 1000 == 0


def _event_severity(event_type: str) -> str:
    """按事件名称提供默认严重级别，显式 severity 仍由调用方覆盖。"""

    return "error" if "error" in str(event_type).lower() else "info"


def _optional_score(source: object | None, name: str, *, default: float | None = None) -> float | None:
    """读取可选评分并把缺失或非有限值转换为 JSON null 语义。"""

    if source is None or not hasattr(source, name):
        return default
    try:
        value = float(getattr(source, name))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


__all__ = ["PoseLogFactory", "RuntimeLogWriter"]

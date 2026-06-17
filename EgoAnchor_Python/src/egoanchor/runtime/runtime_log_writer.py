"""TrackingRuntime 结构化日志写入器。"""

from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from egoanchor.diagnostics import RuntimeEventLogger
from egoanchor.utils import clamp, get_logger, rotation_matrix_to_quaternion
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

    def close(self) -> None:
        """关闭底层日志文件。"""

        try:
            self.logger.close()
        except Exception as exc:  # pragma: no cover - 退出路径只做 best-effort 收尾
            LOGGER.debug("关闭 runtime JSONL 日志失败，已忽略：%s", exc)

    def event(self, event_type: str, **fields: Any) -> None:
        """写入一条通用 runtime 事件。"""

        try:
            self.logger.write(event_type, **fields)
        except Exception as exc:
            self.log_write_failures += 1
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
                score_phase=float(getattr(diagnostics, "score_phase", 0.0)),
                score_reprojection=float(getattr(diagnostics, "score_reprojection", 0.0)),
                score_depth=float(getattr(diagnostics, "score_depth", 0.0)),
                score_mask=float(getattr(diagnostics, "score_mask", 0.0)),
                score_reject=float(getattr(diagnostics, "score_reject", 0.0)),
                score_confidence=float(getattr(diagnostics, "score_confidence", 0.0)),
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
                render_quality_depth_residual_m=float(getattr(diagnostics, "render_quality_depth_residual_m", 0.0)),
                render_quality_ms=float(getattr(diagnostics, "render_quality_ms", 0.0)),
            )
        fields.update(self.pose_factory.build(msg))
        self.event("pose_result", **fields)

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
            filename = str(getattr(eval_session, "python_log_filename"))
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


__all__ = ["PoseLogFactory", "RuntimeLogWriter"]

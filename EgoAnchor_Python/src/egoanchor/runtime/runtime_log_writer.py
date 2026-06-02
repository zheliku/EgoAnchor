"""TrackingRuntime 结构化日志写入器。"""

from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from egoanchor.diagnostics import RuntimeEventLogger
from egoanchor.runtime.runtime_state import RuntimeState
from egoanchor.utils import rotation_matrix_to_quaternion


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
        if matrix is None or len(matrix) != 16:
            self.last_pose_matrix = None
            return {}

        values = tuple(float(v) for v in matrix)
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
            dot = max(-1.0, min(1.0, dot))
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

    def close(self) -> None:
        """关闭底层日志文件。"""

        self.logger.close()

    def event(self, event_type: str, **fields: Any) -> None:
        """写入一条通用 runtime 事件。"""

        self.logger.write(event_type, **fields)

    def pose_result(self, msg: object, *, state: RuntimeState) -> None:
        """记录 PoseResult 的论文相关摘要字段。"""

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
            error_code=str(status.error.code) if status.error is not None else "",
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
            error_code=str(heartbeat.last_error.code) if heartbeat.last_error is not None else "",
        )

    def command_execution(self, command: object, result: object, *, queue_length: int) -> None:
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


__all__ = ["RuntimeLogWriter"]

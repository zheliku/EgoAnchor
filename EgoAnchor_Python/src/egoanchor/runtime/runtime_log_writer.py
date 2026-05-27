"""TrackingRuntime 结构化日志写入器。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from egoanchor.diagnostics import RuntimeEventLogger
from egoanchor.runtime import PoseLogFactory, RuntimeState


class RuntimeLogWriter:
    """集中维护 TrackingRuntime JSONL 事件字段。

    TrackingRuntime 只决定何时发生事件，本类决定事件写入哪些结构化字段，
    避免主循环文件混入 pose/status/heartbeat/command 的日志装配细节。
    """

    def __init__(self, cfg: SimpleNamespace, *, session_id: str) -> None:
        """读取 runtime.logging 配置并创建底层事件日志器。"""

        self.logger = self._build_event_logger(cfg, session_id=session_id)
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
            total_ms=float(msg.timing.total_ms),
            server_publish_mono_ms=float(msg.server_publish_mono_ms),
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
    def _build_event_logger(cfg: SimpleNamespace, *, session_id: str) -> RuntimeEventLogger:
        """根据 TOML 配置创建结构化事件日志器。"""

        logging_cfg = getattr(getattr(cfg, "runtime", SimpleNamespace()), "logging", SimpleNamespace())
        python_root = Path(getattr(getattr(cfg, "paths", SimpleNamespace()), "python_root", Path.cwd()))
        raw_output_dir = Path(str(getattr(logging_cfg, "output_dir", "data/runtime_logs"))).expanduser()
        output_dir = raw_output_dir if raw_output_dir.is_absolute() else python_root / raw_output_dir
        return RuntimeEventLogger(
            enabled=bool(getattr(logging_cfg, "enabled", True)),
            output_dir=output_dir,
            session_id=session_id,
            filename=str(getattr(logging_cfg, "filename", "")),
            flush_every=int(getattr(logging_cfg, "flush_every", 1)),
        )

    @staticmethod
    def _flag(cfg: SimpleNamespace, name: str, default: bool) -> bool:
        """读取 runtime.logging 中的布尔开关。"""

        logging_cfg = getattr(getattr(cfg, "runtime", SimpleNamespace()), "logging", SimpleNamespace())
        return bool(getattr(logging_cfg, name, default))


__all__ = ["RuntimeLogWriter"]

"""runtime tracking loop。

runtime 层是本地 pose pipeline/GPU 状态的唯一 owner。当前阶段在保留 Python
OpenCV debug 的同时，可通过 NATS 发布 camera-space PoseResult 给 Unity 做
frame-aligned anchor 显示；Unity world 变换与平滑仍完全在 Unity 侧完成。
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

from egoanchor.diagnostics import RuntimeEventLogger
from egoanchor.protocol import ProtobufRegistry, QUEST_CAMERA_INFO, QUEST_STEREO, SubjectRegistry
from egoanchor.runtime import (
    CommandDedupStore,
    CommandExecutor,
    CommandQueue,
    HeartbeatFactory,
    PoseResultFactory,
    QuestStreamReceiver,
    RuntimeState,
    StatusEventFactory,
)
from egoanchor.transport import NatsMessageClient, NatsMessageSettings, PoseResultPublisher, ProtobufPublisher

LOGGER = logging.getLogger(__name__)
"""runtime 层日志记录器。"""

if TYPE_CHECKING:
    from egoanchor.perception import QuestPosePipelineOutput


@dataclass(slots=True)
class RuntimeTickResult:
    """TrackingRuntime 单次 tick 的返回结果。"""

    pipeline_output: QuestPosePipelineOutput | None
    """pipeline 输出；无输入且未构建时可为 None。"""

    new_frame_processed: bool
    """本轮是否处理了新的 stereo frame。"""


class TrackingRuntime:
    """Quest stream 接收与 pose pipeline 的组合 runtime。"""

    def __init__(self, cfg: SimpleNamespace, subjects: SubjectRegistry) -> None:
        """保存配置、创建 receiver，并延迟构建 pose pipeline。"""

        self.cfg = cfg
        """runtime TOML 配置对象。"""

        self.subjects = subjects
        """共享 subject registry，用于验证数据面 topic。"""

        for subject in (QUEST_STEREO, QUEST_CAMERA_INFO):
            spec = self.subjects.require(subject)
            if spec.transport != "zmq":
                raise ValueError(f"subject={subject} 必须属于 ZMQ 数据面，实际 transport={spec.transport!r}")

        data_cfg = cfg.network.data_plane
        self.receiver = QuestStreamReceiver(
            listen_host=str(data_cfg.listen_host),
            listen_port=int(data_cfg.listen_port),
            hwm=int(data_cfg.receive_hwm),
            topics=[QUEST_STEREO, QUEST_CAMERA_INFO],
        )
        """Quest ZMQ/Protobuf 输入接收器。"""

        self.pipeline = None
        """QuestPosePipeline 实例；start 时创建，避免构造 runtime 就加载重模型。"""

        self.session_id = uuid.uuid4().hex
        """本次 Python server runtime 会话 ID，贯穿 pose/status/heartbeat 和 JSONL 日志。"""

        self.event_logger = self._build_event_logger(cfg)
        """Python server 结构化事件日志器。"""

        self.log_pose_results = self._logging_flag(cfg, "log_pose_results", True)
        """是否记录 PoseResult 摘要。"""

        self.log_status_events = self._logging_flag(cfg, "log_status_events", True)
        """是否记录 AnchorStatusEvent 摘要。"""

        self.log_heartbeats = self._logging_flag(cfg, "log_heartbeats", True)
        """是否记录 ServerHeartbeat 摘要。"""

        self.log_commands = self._logging_flag(cfg, "log_commands", True)
        """是否记录 runtime command 执行动作。"""

        self.pose_result_factory = PoseResultFactory(session_id=self.session_id)
        """PoseObservation -> Protobuf PoseResult 的映射器。"""

        self.status_event_factory = StatusEventFactory(session_id=self.session_id)
        """runtime 状态/命令事件 -> AnchorStatusEvent 的映射器。"""

        self.heartbeat_factory = HeartbeatFactory(session_id=self.session_id)
        """runtime/input 健康状态 -> ServerHeartbeat 的映射器。"""

        command_cfg = getattr(getattr(cfg, "runtime", SimpleNamespace()), "commands", SimpleNamespace())
        self.command_queue = CommandQueue(max_size=int(getattr(command_cfg, "max_queue_size", 128)))
        """NATS command handler enqueue 的命令队列。"""

        self.command_dedup = CommandDedupStore(ttl_ms=float(getattr(command_cfg, "dedup_ttl_ms", 60_000)))
        """CommandAck request_id 幂等缓存。"""

        self.command_executor = CommandExecutor()
        """命令解释器；TrackingRuntime 在 tick 边界按解释结果操作 pipeline。"""

        self.command_execute_per_tick = max(1, int(getattr(command_cfg, "execute_per_tick", 8)))
        """每轮 tick 最多执行的命令数量。"""

        self.paused = False
        """是否因 control/pause 暂停处理新图像。"""

        self.nats_client: NatsMessageClient | None = None
        """共享 NATS bytes client；pose/status/heartbeat publisher 复用同一连接。"""

        self.pose_publisher: PoseResultPublisher | None = None
        """NATS PoseResult 发布器；配置关闭时为 None。"""

        self.status_publisher: ProtobufPublisher | None = None
        """NATS AnchorStatusEvent 发布器；配置关闭时为 None。"""

        self.heartbeat_publisher: ProtobufPublisher | None = None
        """NATS ServerHeartbeat 发布器；配置关闭时为 None。"""

        self._build_message_publishers(cfg)

        self.pose_publish_attempts = 0
        """已尝试发布 PoseResult 的次数。"""

        self.pose_publish_submitted = 0
        """成功提交到后台 NATS event loop 的 PoseResult 数量。"""

        self.status_publish_attempts = 0
        """已尝试发布 AnchorStatusEvent 的次数。"""

        self.status_publish_submitted = 0
        """成功提交到后台 NATS event loop 的 AnchorStatusEvent 数量。"""

        self.heartbeat_publish_attempts = 0
        """已尝试发布 ServerHeartbeat 的次数。"""

        self.heartbeat_publish_submitted = 0
        """成功提交到后台 NATS event loop 的 ServerHeartbeat 数量。"""

        heartbeat_cfg = getattr(getattr(cfg, "runtime", SimpleNamespace()), "heartbeat", SimpleNamespace())
        self.heartbeat_interval_s = max(0.1, float(getattr(heartbeat_cfg, "interval_s", 1.0)))
        """ServerHeartbeat 发布间隔，单位秒。"""

        self.last_heartbeat_mono_s = 0.0
        """上一次心跳尝试发布的本地单调时间，单位秒。"""

        self.last_tick_mono_s = 0.0
        """上一次 tick 的本地单调时间，单位秒。"""

        self.runtime_fps = 0.0
        """TrackingRuntime tick 频率的轻量 EMA。"""

        self.state = RuntimeState.BOOTING
        """Python server runtime 当前状态。"""

        self.last_error = None
        """最近一次结构化 runtime 错误；无错误时为 None。"""

        self.last_logged_pose_matrix: tuple[float, ...] | None = None
        """上一条成功写入日志的 camera-space pose matrix，用于计算相邻 pose jump。"""

        self.started = False
        """runtime 是否已经启动。"""

    @property
    def endpoint(self) -> str:
        """返回 ZMQ 监听 endpoint。"""

        return self.receiver.endpoint

    def start(self) -> None:
        """启动 receiver 并构建 pose pipeline。"""

        if self.started:
            return
        from egoanchor.perception import build_quest_pose_pipeline

        self.receiver.start()
        if self.pose_publisher is not None:
            self.pose_publisher.start()
        self.pipeline = build_quest_pose_pipeline(self.cfg)
        self.pipeline.set_stage(int(self.cfg.server.run_stage))
        self.started = True
        self._log_event("runtime_started", endpoint=self.endpoint, run_stage=int(self.cfg.server.run_stage), state=self.state.value)
        self._set_state(RuntimeState.WAITING_INPUT, event="RUNTIME_STARTED", message="TrackingRuntime 已启动，等待 Quest 输入。")

    def close(self) -> None:
        """关闭 receiver 与 NATS publisher；OpenCV 窗口由 app 层关闭。"""

        self._set_state(RuntimeState.STOPPED, event="RUNTIME_STOPPED", message="TrackingRuntime 已停止。")
        self._log_event("runtime_stopped", state=RuntimeState.STOPPED.value)
        if self.pipeline is not None and hasattr(self.pipeline, "close"):
            self.pipeline.close()
        if self.pose_publisher is not None:
            self.pose_publisher.close()
        elif self.nats_client is not None:
            self.nats_client.close()
        self.receiver.close()
        self.event_logger.close()
        self.started = False

    def tick(self, return_debug: bool = True) -> RuntimeTickResult:
        """poll latest Quest input，并在有新 stereo 时运行 pose pipeline。"""

        if not self.started or self.pipeline is None:
            raise RuntimeError("TrackingRuntime 尚未 start。")
        self._update_runtime_fps()
        try:
            self._execute_pending_commands()
            data_cfg = self.cfg.network.data_plane
            self.receiver.poll_latest(timeout_ms=int(data_cfg.poll_timeout_ms))
            if self.paused:
                self._set_state(RuntimeState.PAUSED)
                self._maybe_publish_heartbeat()
                return RuntimeTickResult(pipeline_output=None, new_frame_processed=False)

            self._refresh_input_state_before_pipeline()
            output = self.pipeline.process(self.receiver.get_latest_stereo(), self.receiver.get_latest_camera_info())
            if output.new_frame_processed and output.observation is not None:
                self._update_state_from_observation(output.observation)
                self._publish_observation(output.observation)
            self._maybe_publish_heartbeat()
            return RuntimeTickResult(pipeline_output=output if return_debug else None, new_frame_processed=output.new_frame_processed)
        except Exception as exc:
            self.last_error = self._build_error("RUNTIME_EXCEPTION", str(exc), exc.__class__.__name__)
            self._log_event("runtime_error", state=RuntimeState.ERROR.value, error_code=self.last_error.code, message=str(exc), details=exc.__class__.__name__)
            self._set_state(RuntimeState.ERROR, event="RUNTIME_ERROR", message=str(exc), error=self.last_error)
            raise

    def set_stage(self, stage: int) -> None:
        """设置 pipeline debug stage。"""

        if self.pipeline is not None:
            self.pipeline.set_stage(stage)
        self._set_state(self.state, event="STAGE_SET", message=f"debug stage 已切换为 {stage}。")

    def reset_tracking_state(self) -> None:
        """响应键盘 r：重置 pose tracking 状态。"""

        if self.pipeline is not None:
            self.pipeline.reset_tracking_state()
        self._set_state(RuntimeState.DETECTING, event="RESET_APPLIED", message="本地键盘触发 reset tracking。")

    def get_stats(self):
        """返回 Quest stream receiver 的 latest-only 统计快照。"""

        return self.receiver.get_stats()

    def get_pose_publish_stats(self) -> dict[str, int | bool]:
        """返回 PoseResult 发布统计快照。"""

        publisher = self.pose_publisher
        if publisher is None:
            return {"enabled": False, "attempts": self.pose_publish_attempts, "submitted": 0, "published": 0, "failed": 0, "pending": 0}
        return {
            "enabled": bool(publisher.enabled),
            "attempts": self.pose_publish_attempts,
            "submitted": self.pose_publish_submitted,
            "published": int(publisher.published_count),
            "failed": int(publisher.failed_count),
            "pending": int(publisher.pending_count),
        }

    def get_command_stats(self) -> dict[str, int | bool]:
        """返回 command queue/dedup 统计。"""

        return {"paused": self.paused, "queue_length": len(self.command_queue), "dedup_size": len(self.command_dedup)}

    def _build_message_publishers(self, cfg: SimpleNamespace) -> None:
        """根据配置创建共享 NATS client 与三类 Protobuf 发布器。"""

        settings = NatsMessageSettings.from_config(cfg)
        if not settings.enabled:
            return
        client = NatsMessageClient(settings)
        self._attach_command_router(client)
        self.nats_client = client
        self.pose_publisher = PoseResultPublisher(client, subject=settings.pose_result_subject, max_pending_futures=settings.max_pending_futures)
        self.status_publisher = ProtobufPublisher(client, subject=settings.anchor_status_subject, max_pending_futures=settings.max_pending_futures)
        self.heartbeat_publisher = ProtobufPublisher(client, subject=settings.server_heartbeat_subject, max_pending_futures=settings.max_pending_futures)

    def _publish_observation(self, observation) -> None:
        """把当前帧观测转换为 PoseResult 并投递到 NATS。"""

        msg = self.pose_result_factory.build(observation)
        if self.log_pose_results:
            self._log_pose_result(msg)
        if self.pose_publisher is None or not self.pose_publisher.enabled:
            return
        self.pose_publish_attempts += 1
        if self.pose_publisher.publish_pose_result(msg):
            self.pose_publish_submitted += 1

    def _publish_status(self, msg) -> None:
        """把 AnchorStatusEvent 投递到 NATS。"""

        if self.status_publisher is None or not self.status_publisher.enabled:
            return
        self.status_publish_attempts += 1
        if self.status_publisher.publish(msg):
            self.status_publish_submitted += 1

    def _publish_heartbeat(self) -> None:
        """构造并发布 ServerHeartbeat。"""

        msg = self.heartbeat_factory.build(
            self.state,
            input_stats=self.receiver.get_stats(),
            runtime_fps=self.runtime_fps,
            publish_fps=0.0,
            command_stats=self.get_command_stats(),
            last_error=self.last_error,
        )
        if self.log_heartbeats:
            self._log_heartbeat(msg)
        if self.heartbeat_publisher is None or not self.heartbeat_publisher.enabled:
            return
        self.heartbeat_publish_attempts += 1
        if self.heartbeat_publisher.publish(msg):
            self.heartbeat_publish_submitted += 1

    def _maybe_publish_heartbeat(self) -> None:
        """按固定低频发布 ServerHeartbeat。"""

        now = time.monotonic()
        if now - self.last_heartbeat_mono_s < self.heartbeat_interval_s:
            return
        self.last_heartbeat_mono_s = now
        self._publish_heartbeat()

    def _attach_command_router(self, client: NatsMessageClient) -> None:
        """把 command request/reply router 绑定到 NATS client。"""

        from egoanchor.handlers import register_command_handlers
        from egoanchor.routing import HandlerContext, HandlerRegistry, NatsRouter, iter_nats_request_specs

        handlers = HandlerRegistry()
        register_command_handlers(handlers)
        router = NatsRouter(
            self.subjects,
            ProtobufRegistry(),
            handlers,
            HandlerContext(commands=self.command_queue, dedup=self.command_dedup),
        )
        for spec in iter_nats_request_specs(self.subjects):
            client.add_subscription(spec.name, router.handle_message)

    def _execute_pending_commands(self) -> None:
        """在 runtime 主循环顺序执行已接受 command。"""

        if self.pipeline is None:
            return
        for command in self.command_queue.pop_many(self.command_execute_per_tick):
            result = self.command_executor.interpret(command)
            if self.log_commands:
                self._log_command_execution(command, result)
            if result.paused is not None:
                self.paused = bool(result.paused)
            if result.stage is not None:
                self.pipeline.set_stage(result.stage)
            if result.reset_tracking:
                self.pipeline.reset_tracking_state()
            self._publish_command_status(command, result)

    def _publish_command_status(self, command, result) -> None:
        """发布 runtime command 执行后的状态事件。"""

        if command.command_type.value == "reset":
            self._set_state(RuntimeState.DETECTING, event="RESET_APPLIED", message="reset command 已在 runtime 线程执行。", request_id=command.request_id)
            return
        if command.command_type.value == "reacquire":
            self._set_state(
                RuntimeState.REACQUIRING,
                event="REACQUIRE_STARTED",
                message="reacquire command 已在 runtime 线程执行，等待后续有效 pose。",
                request_id=command.request_id,
            )
            return
        if result.paused is True:
            self._set_state(RuntimeState.PAUSED, event="PAUSE_APPLIED", message="runtime 已暂停处理新图像。", request_id=command.request_id)
            return
        if result.paused is False:
            self._set_state(RuntimeState.DETECTING, event="RESUME_APPLIED", message="runtime 已恢复处理新图像。", request_id=command.request_id)
            return
        if result.stage is not None:
            self._set_state(self.state, event="STAGE_SET", message=f"debug stage 已切换为 {result.stage}。", request_id=command.request_id)

    def _refresh_input_state_before_pipeline(self) -> None:
        """根据 latest input 更新等待输入/等待标定状态。"""

        stereo = self.receiver.get_latest_stereo()
        camera_info = self.receiver.get_latest_camera_info()
        if stereo is None:
            self._set_state(RuntimeState.WAITING_INPUT)
        elif camera_info is None:
            self._set_state(RuntimeState.WAITING_CALIBRATION)
        elif self.state in (RuntimeState.WAITING_INPUT, RuntimeState.WAITING_CALIBRATION, RuntimeState.BOOTING):
            self._set_state(RuntimeState.DETECTING, event="INPUT_READY", message="Quest stereo 与 camera_info 已就绪。")

    def _update_state_from_observation(self, observation) -> None:
        """根据 PoseObservation 更新 Python runtime 状态。"""

        hint = str(getattr(observation, "tracking_state_hint", "") or "").upper()
        phase = str(getattr(observation, "phase", "") or "").upper()
        if bool(getattr(observation, "has_pose", False)):
            if self.state == RuntimeState.REACQUIRING:
                self._set_state(
                    RuntimeState.TRACKING,
                    event="REACQUIRE_SUCCEEDED",
                    message="reacquire 后已重新获得有效 pose。",
                    frame_id=getattr(observation, "frame_id", None),
                )
            else:
                self._set_state(RuntimeState.TRACKING)
            self.last_error = None
            return

        if "LOST" in hint or "LOST" in phase or "REJECT" in phase:
            self._set_state(RuntimeState.LOST)
        elif "REGISTER" in hint or "REGISTER" in phase:
            self._set_state(RuntimeState.REGISTERING)
        else:
            self._set_state(RuntimeState.DETECTING)

    def _set_state(self, state: RuntimeState, *, event: str = "", message: str = "", request_id: str = "", frame_id: int | None = None, error=None) -> None:
        """更新 runtime 状态，并在状态变化或显式事件时发布 AnchorStatusEvent。"""

        previous = self.state
        self.state = state
        should_publish = bool(event) or previous != state or error is not None
        if not should_publish:
            return
        event_name = event or "STATE_CHANGED"
        status = self.status_event_factory.build(
            state,
            event=event_name,
            message=message or f"{previous.value} -> {state.value}",
            request_id=request_id,
            frame_id=frame_id,
            error=error,
        )
        self._publish_status(status)
        if self.log_status_events:
            self._log_status(status, previous)
        LOGGER.info("[TrackingRuntime] state=%s event=%s message=%s", state.value, event_name, status.message)

    def _update_runtime_fps(self) -> None:
        """更新 runtime tick 频率 EMA。"""

        now = time.monotonic()
        if self.last_tick_mono_s > 0.0:
            dt = max(now - self.last_tick_mono_s, 1e-6)
            instant_fps = 1.0 / dt
            self.runtime_fps = instant_fps if self.runtime_fps <= 0.0 else self.runtime_fps * 0.9 + instant_fps * 0.1
        self.last_tick_mono_s = now

    @staticmethod
    def _build_error(code: str, message: str, details: str = ""):
        """构造共享 ErrorInfo，避免 runtime 层直接依赖具体生成文件路径。"""

        from egoanchor.protocol import common_pb2

        return common_pb2.ErrorInfo(code=str(code or ""), message=str(message or ""), details=str(details or ""))

    def _build_event_logger(self, cfg: SimpleNamespace) -> RuntimeEventLogger:
        """根据 TOML 配置创建结构化事件日志器。"""

        logging_cfg = getattr(getattr(cfg, "runtime", SimpleNamespace()), "logging", SimpleNamespace())
        python_root = Path(getattr(getattr(cfg, "paths", SimpleNamespace()), "python_root", Path.cwd()))
        raw_output_dir = Path(str(getattr(logging_cfg, "output_dir", "data/runtime_logs"))).expanduser()
        output_dir = raw_output_dir if raw_output_dir.is_absolute() else python_root / raw_output_dir
        return RuntimeEventLogger(
            enabled=bool(getattr(logging_cfg, "enabled", True)),
            output_dir=output_dir,
            session_id=self.session_id,
            filename=str(getattr(logging_cfg, "filename", "")),
            flush_every=int(getattr(logging_cfg, "flush_every", 1)),
        )

    @staticmethod
    def _logging_flag(cfg: SimpleNamespace, name: str, default: bool) -> bool:
        """读取 runtime.logging 中的布尔开关。"""

        logging_cfg = getattr(getattr(cfg, "runtime", SimpleNamespace()), "logging", SimpleNamespace())
        return bool(getattr(logging_cfg, name, default))

    def _log_event(self, event_type: str, **fields) -> None:
        """写入一条 runtime 结构化事件。"""

        self.event_logger.write(event_type, **fields)

    def _log_pose_result(self, msg) -> None:
        """记录 PoseResult 的论文相关摘要字段。"""

        pose_fields = self._pose_log_fields(msg)
        fields = dict(
            frame_id=int(msg.header.frame_id),
            state=self.state.value,
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
        fields.update(pose_fields)
        self._log_event("pose_result", **fields)

    def _pose_log_fields(self, msg) -> dict[str, float]:
        """提取 pose 平移、旋转和相邻 jump，便于诊断 frame alignment 残差。"""

        if not bool(getattr(msg, "has_pose", False)):
            self.last_logged_pose_matrix = None
            return {}
        matrix = getattr(getattr(msg, "pose_matrix_cv_camera", None), "values", None)
        if matrix is None or len(matrix) != 16:
            self.last_logged_pose_matrix = None
            return {}

        values = tuple(float(v) for v in matrix)
        tx, ty, tz = values[3], values[7], values[11]
        qx, qy, qz, qw = self._rotation_matrix_to_quaternion(values)
        jump_t = 0.0
        jump_r = 0.0
        if self.last_logged_pose_matrix is not None:
            prev = self.last_logged_pose_matrix
            dx = tx - prev[3]
            dy = ty - prev[7]
            dz = tz - prev[11]
            jump_t = (dx * dx + dy * dy + dz * dz) ** 0.5
            pqx, pqy, pqz, pqw = self._rotation_matrix_to_quaternion(prev)
            dot = abs(qx * pqx + qy * pqy + qz * pqz + qw * pqw)
            dot = max(-1.0, min(1.0, dot))
            import math

            jump_r = math.degrees(2.0 * math.acos(dot))
        self.last_logged_pose_matrix = values
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
    def _rotation_matrix_to_quaternion(matrix: tuple[float, ...]) -> tuple[float, float, float, float]:
        """把 row-major 4x4 旋转部分转换为归一化四元数 x/y/z/w。"""

        import math

        m00, m01, m02 = matrix[0], matrix[1], matrix[2]
        m10, m11, m12 = matrix[4], matrix[5], matrix[6]
        m20, m21, m22 = matrix[8], matrix[9], matrix[10]
        trace = m00 + m11 + m22
        if trace > 0.0:
            s = math.sqrt(trace + 1.0) * 2.0
            qw = 0.25 * s
            qx = (m21 - m12) / s
            qy = (m02 - m20) / s
            qz = (m10 - m01) / s
        elif m00 > m11 and m00 > m22:
            s = math.sqrt(1.0 + m00 - m11 - m22) * 2.0
            qw = (m21 - m12) / s
            qx = 0.25 * s
            qy = (m01 + m10) / s
            qz = (m02 + m20) / s
        elif m11 > m22:
            s = math.sqrt(1.0 + m11 - m00 - m22) * 2.0
            qw = (m02 - m20) / s
            qx = (m01 + m10) / s
            qy = 0.25 * s
            qz = (m12 + m21) / s
        else:
            s = math.sqrt(1.0 + m22 - m00 - m11) * 2.0
            qw = (m10 - m01) / s
            qx = (m02 + m20) / s
            qy = (m12 + m21) / s
            qz = 0.25 * s
        norm = max((qx * qx + qy * qy + qz * qz + qw * qw) ** 0.5, 1e-12)
        return qx / norm, qy / norm, qz / norm, qw / norm

    def _log_status(self, status, previous: RuntimeState) -> None:
        """记录 AnchorStatusEvent 的状态迁移摘要。"""

        self._log_event(
            "status_event",
            previous_state=previous.value,
            state=str(status.state),
            status_event=str(status.event),
            message=str(status.message),
            request_id=str(status.header.request_id),
            frame_id=int(status.header.frame_id),
            error_code=str(status.error.code) if status.error is not None else "",
        )

    def _log_heartbeat(self, heartbeat) -> None:
        """记录 ServerHeartbeat 的低频健康状态摘要。"""

        self._log_event(
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

    def _log_command_execution(self, command, result) -> None:
        """记录 runtime 线程实际执行 command 的时间点和动作。"""

        self._log_event(
            "command_executed",
            command_type=command.command_type.value,
            request_id=command.request_id,
            anchor_id=command.anchor_id,
            queued_mono_ms=float(command.created_mono_ms),
            paused=result.paused,
            stage=result.stage,
            reset_tracking=bool(result.reset_tracking),
            queue_length=len(self.command_queue),
        )


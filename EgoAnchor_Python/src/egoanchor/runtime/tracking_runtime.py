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

from egoanchor.protocol import ProtobufRegistry, QUEST_CAMERA_INFO, QUEST_STEREO, SubjectRegistry
from egoanchor.transport import NatsMessageClient, NatsMessageSettings, ProtobufPublisher
from .commands import (
    CommandDedupStore,
    CommandExecutor,
    CommandPump,
    CommandQueue,
)
from .eval_session import create_eval_session
from .message_factories import HeartbeatFactory, PoseResultFactory, StatusEventFactory
from .quest_stream_receiver import QuestStreamReceiver
from .runtime_log_writer import RuntimeLogWriter
from .runtime_state import RuntimeState

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

        self.eval_session = self._create_eval_session_if_enabled(cfg)
        """Python 先启动时创建的共享评估 session；关闭时为 None。"""

        self.session_id = self.eval_session.session_id if self.eval_session is not None else uuid.uuid4().hex
        """本次 Python server runtime 会话 ID，贯穿 pose/status/heartbeat 和 JSONL 日志。"""

        self.log_writer = RuntimeLogWriter(cfg, session_id=self.session_id, eval_session=self.eval_session)
        """Python server 结构化事件日志写入器。"""

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

        self.paused = False
        """是否因 control/pause 暂停处理新图像。"""

        self.command_pump = CommandPump(
            queue=self.command_queue,
            executor=self.command_executor,
            execute_per_tick=int(getattr(command_cfg, "execute_per_tick", 8)),
            log_execution=self.log_writer.command_execution,
            set_paused=lambda value: setattr(self, "paused", bool(value)),
            set_stage=self._set_pipeline_stage,
            reset_tracking=self._reset_pipeline_tracking,
            get_state=lambda: self.state,
            publish_state=self._set_state,
        )
        """runtime owner 线程上的 command 顺序执行器。"""

        self.nats_client: NatsMessageClient | None = None
        """共享 NATS bytes client；pose/status/heartbeat publisher 复用同一连接。"""

        self.pose_publisher: ProtobufPublisher | None = None
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
        self.log_writer.event("runtime_started", endpoint=self.endpoint, run_stage=int(self.cfg.server.run_stage), state=self.state.value)
        self._set_state(RuntimeState.WAITING_INPUT, event="RUNTIME_STARTED", message="TrackingRuntime 已启动，等待 Quest 输入。")

    def close(self) -> None:
        """关闭 receiver 与 NATS publisher；OpenCV 窗口由 app 层关闭。"""

        self._set_state(RuntimeState.STOPPED, event="RUNTIME_STOPPED", message="TrackingRuntime 已停止。")
        self.log_writer.event("runtime_stopped", state=RuntimeState.STOPPED.value)
        if self.pipeline is not None and hasattr(self.pipeline, "close"):
            self.pipeline.close()
        if self.pose_publisher is not None:
            self.pose_publisher.close()
        elif self.nats_client is not None:
            self.nats_client.close()
        self.receiver.close()
        self.log_writer.close()
        self.started = False

    def tick(self, return_debug: bool = True) -> RuntimeTickResult:
        """poll latest Quest input，并在有新 stereo 时运行 pose pipeline。"""

        if not self.started or self.pipeline is None:
            raise RuntimeError("TrackingRuntime 尚未 start。")
        self._update_runtime_fps()
        try:
            self.command_pump.execute_pending(pipeline_ready=self.pipeline is not None)
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
                self._publish_observation(output.observation, diagnostics=output.diagnostics)
            self._maybe_publish_heartbeat()
            return RuntimeTickResult(pipeline_output=output if return_debug else None, new_frame_processed=output.new_frame_processed)
        except Exception as exc:
            self.last_error = self._build_error("RUNTIME_EXCEPTION", str(exc), exc.__class__.__name__)
            self.log_writer.event("runtime_error", state=RuntimeState.ERROR.value, error_code=self.last_error.code, message=str(exc), details=exc.__class__.__name__)
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
        self.pose_publisher = ProtobufPublisher(client, subject=settings.pose_result_subject, max_pending_futures=settings.max_pending_futures)
        self.status_publisher = ProtobufPublisher(client, subject=settings.anchor_status_subject, max_pending_futures=settings.max_pending_futures)
        self.heartbeat_publisher = ProtobufPublisher(client, subject=settings.server_heartbeat_subject, max_pending_futures=settings.max_pending_futures)

    def _create_eval_session_if_enabled(self, cfg: SimpleNamespace):
        """按配置创建可被 Unity 自动复用的 Python eval session 目录。"""

        logging_cfg = getattr(getattr(cfg, "runtime", SimpleNamespace()), "logging", SimpleNamespace())
        if not bool(getattr(logging_cfg, "eval_session_enabled", False)):
            return None
        python_root = getattr(getattr(cfg, "paths", SimpleNamespace()), "python_root", Path.cwd())
        eval_root = Path(str(getattr(logging_cfg, "eval_output_dir", "data/eval"))).expanduser()
        if not eval_root.is_absolute():
            eval_root = Path(python_root) / eval_root
        return create_eval_session(
            eval_root,
            str(getattr(getattr(cfg, "runtime", SimpleNamespace()), "object_id", "default")),
            metadata_filename=str(getattr(logging_cfg, "eval_metadata_filename", "python_session.json")),
            python_log_filename=str(getattr(logging_cfg, "filename", "")),
        )

    def _publish_observation(self, observation, *, diagnostics=None) -> None:
        """把当前帧观测转换为 PoseResult 并投递到 NATS。"""

        msg = self.pose_result_factory.build(observation)
        self.log_writer.pose_result(msg, state=self.state, diagnostics=diagnostics)
        if self.pose_publisher is None or not self.pose_publisher.enabled:
            return
        self.pose_publish_attempts += 1
        if self.pose_publisher.publish(msg):
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
        self.log_writer.heartbeat(msg)
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
        from egoanchor.routing import HandlerContext, HandlerRegistry, NatsRouter

        handlers = HandlerRegistry()
        register_command_handlers(handlers)
        router = NatsRouter(
            self.subjects,
            ProtobufRegistry(),
            handlers,
            HandlerContext(commands=self.command_queue, dedup=self.command_dedup),
        )
        for spec in self.subjects.by_transport("nats"):
            if spec.direction != "unity_to_python" or spec.mode != "request_reply":
                continue
            client.add_subscription(spec.name, router.handle_message)

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
        self.log_writer.status(status, previous=previous)
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

    def _set_pipeline_stage(self, stage: int) -> None:
        """由 CommandPump 在 owner 线程切换 pipeline stage。"""

        if self.pipeline is not None:
            self.pipeline.set_stage(stage)

    def _reset_pipeline_tracking(self) -> None:
        """由 CommandPump 在 owner 线程重置 tracking 状态。"""

        if self.pipeline is not None:
            self.pipeline.reset_tracking_state()

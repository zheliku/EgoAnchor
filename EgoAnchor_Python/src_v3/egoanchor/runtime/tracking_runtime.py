"""v3 runtime tracking loop。

runtime 层是本地 pose pipeline/GPU 状态的唯一 owner。当前阶段在保留 Python
OpenCV debug 的同时，可通过 NATS 发布 camera-space PoseResult 给 Unity 做
frame-aligned anchor 显示；Unity world 变换与平滑仍完全在 Unity 侧完成。
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING

from egoanchor.protocol import ProtobufRegistry, QUEST_CAMERA_INFO, QUEST_STEREO, SubjectRegistry
from egoanchor.runtime import CommandDedupStore, CommandExecutor, CommandQueue, PoseResultFactory, QuestStreamReceiver
from egoanchor.transport import NatsMessageClient, NatsMessageSettings, PoseResultPublisher

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
        """v3 runtime TOML 配置对象。"""

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

        self.pose_result_factory = PoseResultFactory()
        """PoseObservation -> Protobuf PoseResult 的映射器。"""

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

        self.pose_publisher: PoseResultPublisher | None = self._build_pose_publisher(cfg)
        """NATS PoseResult 发布器；配置关闭时为 None。"""

        self.pose_publish_attempts = 0
        """已尝试发布 PoseResult 的次数。"""

        self.pose_publish_submitted = 0
        """成功提交到后台 NATS event loop 的 PoseResult 数量。"""

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

    def close(self) -> None:
        """关闭 receiver 与 NATS publisher；OpenCV 窗口由 app 层关闭。"""

        if self.pose_publisher is not None:
            self.pose_publisher.close()
        self.receiver.close()
        self.started = False

    def tick(self, return_debug: bool = True) -> RuntimeTickResult:
        """poll latest Quest input，并在有新 stereo 时运行 pose pipeline。"""

        if not self.started or self.pipeline is None:
            raise RuntimeError("TrackingRuntime 尚未 start。")
        self._execute_pending_commands()
        if self.paused:
            return RuntimeTickResult(pipeline_output=None, new_frame_processed=False)
        data_cfg = self.cfg.network.data_plane
        self.receiver.poll_latest(timeout_ms=int(data_cfg.poll_timeout_ms))
        output = self.pipeline.process(self.receiver.get_latest_stereo(), self.receiver.get_latest_camera_info())
        if output.new_frame_processed and output.observation is not None:
            self._publish_observation(output.observation)
        return RuntimeTickResult(pipeline_output=output if return_debug else None, new_frame_processed=output.new_frame_processed)

    def set_stage(self, stage: int) -> None:
        """设置 pipeline debug stage。"""

        if self.pipeline is not None:
            self.pipeline.set_stage(stage)

    def reset_tracking_state(self) -> None:
        """响应键盘 r：重置 pose tracking 状态。"""

        if self.pipeline is not None:
            self.pipeline.reset_tracking_state()

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

    def _build_pose_publisher(self, cfg: SimpleNamespace) -> PoseResultPublisher | None:
        """根据配置创建 NATS PoseResult 发布器。"""

        settings = NatsMessageSettings.from_config(cfg)
        if not settings.enabled:
            return None
        client = NatsMessageClient(settings)
        self._attach_command_router(client)
        return PoseResultPublisher(client, subject=settings.pose_result_subject, max_pending_futures=settings.max_pending_futures)

    def _publish_observation(self, observation) -> None:
        """把当前帧观测转换为 PoseResult 并投递到 NATS。"""

        if self.pose_publisher is None or not self.pose_publisher.enabled:
            return
        msg = self.pose_result_factory.build(observation)
        self.pose_publish_attempts += 1
        if self.pose_publisher.publish_pose_result(msg):
            self.pose_publish_submitted += 1

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
            if result.paused is not None:
                self.paused = bool(result.paused)
            if result.stage is not None:
                self.pipeline.set_stage(result.stage)
            if result.reset_tracking:
                self.pipeline.reset_tracking_state()

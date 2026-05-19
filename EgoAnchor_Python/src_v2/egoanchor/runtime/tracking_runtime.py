"""v2 TrackingRuntime。

TrackingRuntime 是计划中的“唯一拥有 pipeline/GPU 状态”的对象。
当前阶段在 Python 本地运行 perception pipeline，并可选通过 NATS 发布
相机坐标系 `PoseResult`，由 Unity v2 Anchor Runtime 负责 frame_id 对齐、
OpenCV->Unity 坐标转换和 world anchor 显示。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np

from egoanchor.perception import QuestPosePipeline, build_quest_pose_pipeline
from egoanchor.protocol import QUEST_CAMERA_INFO, QUEST_STEREO
from egoanchor.transport import AnchorCommandService, PoseResultPublisher

from .command_queue import CommandQueue, RuntimeCommand
from .pose_result_factory import pose_result_from_observation
from .quest_stream_receiver import QuestStreamReceiver


@dataclass(slots=True)
class RuntimeTickResult:
    """TrackingRuntime 单次 tick 的轻量返回值。"""

    has_new_output: bool = False
    debug_dashboard_bgr: np.ndarray | None = None
    debug_stereo_bgr: np.ndarray | None = None
    observation_frame_id: int | None = None
    has_pose: bool = False


class TrackingRuntime:
    """v2 runtime 主循环。

    它是后续 NATS command handler、perception pipeline、pose publisher 的汇合点，
    也是唯一允许持有 GPU/pipeline 状态的对象。
    """

    def __init__(self, cfg: SimpleNamespace) -> None:
        """保存配置并创建数据面接收器。"""

        self.cfg = cfg
        self.receiver = QuestStreamReceiver(
            listen_host=cfg.network.data_plane.listen_host,
            listen_port=cfg.network.data_plane.listen_port,
            hwm=cfg.network.data_plane.receive_hwm,
            topics=[QUEST_STEREO, QUEST_CAMERA_INFO],
        )
        self.pipeline: QuestPosePipeline | None = None
        self.command_queue = CommandQueue()
        self.pose_publisher = PoseResultPublisher.from_config(cfg)
        self.command_service = AnchorCommandService(self.pose_publisher.client, self.command_queue)
        self._paused = False
        self._last_log_time = 0.0
        self._last_pose_log_frame_id: int | None = None
        self._last_published_frame_id: int | None = None

    def start(self) -> None:
        self.receiver.start()
        self.command_service.register_handlers()
        self.pose_publisher.start()
        # tracking_server 作为主 runtime 入口时也创建 perception pipeline；
        # quest_video_stream_demo 仍是纯通信 demo，不会触发模型加载。
        self.pipeline = build_quest_pose_pipeline(self.cfg)

    def stop(self) -> None:
        self.pose_publisher.close()
        self.receiver.close()

    def tick(self, *, return_debug: bool = False) -> RuntimeTickResult:
        """执行一次轻量 runtime tick。

        当前做：
        - poll ZMQ latest 输入；
        - 若已收到 camera_info/stereo，则运行 QuestPosePipeline；
        - 可选发布 NATS PoseResult；
        - 周期打印链路统计与 pose 诊断。

        后续扩展点：
        - command_queue.poll()
        - reset/reacquire/control command handler
        """

        result = RuntimeTickResult()
        self._drain_commands()
        if self._paused:
            return result
        self.receiver.poll_latest(timeout_ms=int(self.cfg.network.data_plane.poll_timeout_ms))
        if self.pipeline is not None:
            output = self.pipeline.process(
                stereo_msg=self.receiver.get_latest_stereo(),
                camera_info_msg=self.receiver.get_latest_camera_info(),
                return_debug=return_debug,
            )
            if output is not None:
                result.has_new_output = True
                if output.debug is not None:
                    result.debug_dashboard_bgr, result.debug_stereo_bgr = output.debug
                obs = output.observation
                result.observation_frame_id = obs.frame_id
                result.has_pose = bool(obs.has_pose)
                if obs.frame_id != self._last_published_frame_id:
                    self.pose_publisher.publish_pose_result(pose_result_from_observation(obs))
                    self._last_published_frame_id = obs.frame_id
                if obs.has_pose and obs.frame_id != self._last_pose_log_frame_id:
                    logging.debug(
                        "[TrackingRuntime] pose frame_id=%s phase=%s rel=%.2f depth=%.1f%% in_mask=%.1f%%",
                        obs.frame_id,
                        obs.phase,
                        obs.reliability_score,
                        obs.depth_valid_ratio * 100.0,
                        obs.depth_valid_in_mask * 100.0,
                    )
                    self._last_pose_log_frame_id = obs.frame_id
                self._drain_commands()
        now = time.perf_counter()
        if now - self._last_log_time >= 3.0:
            stats = self.receiver.get_stats()
            logging.info(
                "[TrackingRuntime] received=%d stereo=%d camera_info=%d failed=%d latest_frame_id=%s",
                stats.received,
                stats.decoded_stereo,
                stats.decoded_camera_info,
                stats.decode_failed,
                stats.latest_stereo_frame_id,
            )
            if self.pose_publisher.enabled:
                logging.info(
                    "[TrackingRuntime] pose_publish subject=%s published=%d failed=%d latest_frame_id=%s",
                    self.pose_publisher.subject,
                    self.pose_publisher.published_count,
                    self.pose_publisher.failed_count,
                    self._last_published_frame_id,
                )
                logging.info(
                    "[TrackingRuntime] command_queue=%d accepted=%d rejected=%d duplicates=%d",
                    len(self.command_queue),
                    self.command_service.accepted_count,
                    self.command_service.rejected_count,
                    self.command_service.duplicate_count,
                )
            self._last_log_time = now
        return result

    def _drain_commands(self) -> None:
        """顺序消费 NATS command queue，保证 pipeline 状态单线程拥有。"""

        while True:
            command = self.command_queue.pop()
            if command is None:
                return
            self._apply_command(command)

    def _apply_command(self, command: RuntimeCommand) -> None:
        """执行一个 runtime command。"""

        if command.command_type in {"reset", "reacquire"}:
            self.reset_tracking_state()
            logging.info("[TrackingRuntime] applied command=%s request_id=%s", command.command_type, command.request_id)
        elif command.command_type == "control":
            if command.action == "SET_STAGE" and command.stage is not None:
                self.set_stage(command.stage)
            elif command.action == "PAUSE":
                self._paused = True
            elif command.action == "RESUME":
                self._paused = False
            logging.info(
                "[TrackingRuntime] applied control action=%s stage=%s request_id=%s",
                command.action,
                command.stage,
                command.request_id,
            )
        else:
            logging.warning("[TrackingRuntime] unknown command=%s request_id=%s", command.command_type, command.request_id)

    def set_stage(self, stage: int) -> None:
        """切换 perception pipeline debug 阶段。"""

        if self.pipeline is None:
            return
        self.pipeline.set_stage(stage)

    def reset_tracking_state(self) -> None:
        """重置 FoundationPose/Cutie 时序状态。"""

        if self.pipeline is None:
            return
        self.pipeline.reset_tracking_state()

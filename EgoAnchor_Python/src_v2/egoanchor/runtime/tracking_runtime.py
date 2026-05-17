"""v2 TrackingRuntime。

TrackingRuntime 是计划中的“唯一拥有 pipeline/GPU 状态”的对象。
当前阶段可在 Python 本地运行 perception pipeline 并打印 pose 诊断；
仍然不通过 NATS/ZMQ 向 Unity 发布 PoseResult，避免提前绕过后续 Anchor Runtime 设计。
"""

from __future__ import annotations

import logging
import time
from types import SimpleNamespace

from egoanchor.perception.quest_pose_pipeline import QuestPosePipeline, build_quest_pose_pipeline
from egoanchor.protocol import QUEST_CAMERA_INFO, QUEST_STEREO
from egoanchor.transport import ZmqDataPlaneReceiver


class TrackingRuntime:
    """v2 runtime 主循环骨架。"""

    def __init__(self, cfg: SimpleNamespace) -> None:
        self.cfg = cfg
        self.receiver = ZmqDataPlaneReceiver(
            listen_host=cfg.network.data_plane.listen_host,
            listen_port=cfg.network.data_plane.listen_port,
            hwm=cfg.network.data_plane.receive_hwm,
            topics=[QUEST_STEREO, QUEST_CAMERA_INFO],
        )
        self.pipeline: QuestPosePipeline | None = None
        self._last_log_time = 0.0
        self._last_pose_log_frame_id: int | None = None

    def start(self) -> None:
        self.receiver.start()
        # tracking_server 作为主 runtime 入口时也创建 perception pipeline；
        # quest_video_stream_demo 仍是纯通信 demo，不会触发模型加载。
        self.pipeline = build_quest_pose_pipeline(self.cfg)

    def stop(self) -> None:
        self.receiver.close()

    def tick(self) -> None:
        """执行一次轻量 runtime tick。

        当前做：
        - poll ZMQ latest 输入；
        - 若已收到 camera_info/stereo，则运行 QuestPosePipeline；
        - 周期打印链路统计与 pose 诊断。

        后续扩展点：
        - command_queue.poll()
        - nats_control_plane.publish_pose_result(...)
        """

        self.receiver.poll_latest(timeout_ms=int(self.cfg.network.data_plane.poll_timeout_ms))
        if self.pipeline is not None:
            output = self.pipeline.process(
                stereo_msg=self.receiver.get_latest_stereo(),
                camera_info_msg=self.receiver.get_latest_camera_info(),
                return_debug=False,
            )
            if output is not None and output.observation.has_pose and output.observation.frame_id != self._last_pose_log_frame_id:
                obs = output.observation
                logging.debug(
                    "[TrackingRuntime] pose frame_id=%s phase=%s rel=%.2f depth=%.1f%% in_mask=%.1f%%",
                    obs.frame_id,
                    obs.phase,
                    obs.reliability_score,
                    obs.depth_valid_ratio * 100.0,
                    obs.depth_valid_in_mask * 100.0,
                )
                self._last_pose_log_frame_id = obs.frame_id
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
            self._last_log_time = now

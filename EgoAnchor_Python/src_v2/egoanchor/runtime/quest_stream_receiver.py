"""Quest stream 接收与 Protobuf 解码。

Unity 侧对应组件是 `Client/QuestStreamPublisher.cs`：它组合 Quest source 与
`ZmqTopicPublisher` 发送 stereo/camera_info。Python 侧本模块组合通用
`ZmqTopicSubscriber` 与共享 Protobuf，维护 Quest 输入 latest cache。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from google.protobuf.message import DecodeError

from egoanchor.protocol import QUEST_CAMERA_INFO, QUEST_STEREO
from egoanchor.protocol import quest_pb2
from egoanchor.transport.zmq_topic_subscriber import ZmqTopicSubscriber


@dataclass(frozen=True)
class QuestInputStats:
    """Quest 输入累计统计。"""

    received: int
    decoded_stereo: int
    decoded_camera_info: int
    decode_failed: int
    invalid_multipart: int
    zmq_errors: int
    latest_stereo_frame_id: int | None
    latest_camera_info_frame_id: int | None
    latest_stereo_age_ms: float | None
    latest_camera_info_age_ms: float | None


class LatestQuestInputStore:
    """Quest 输入最新值缓存。

    latest-only 是实时视频链路的核心策略：
    - stereo 高频消息只保留最新一帧，避免模型或显示阻塞时累积旧帧；
    - camera_info 低频独立缓存，避免被 stereo drain 掩盖。
    """

    def __init__(self) -> None:
        self.latest_stereo: quest_pb2.QuestStereoFrame | None = None
        self.latest_camera_info: quest_pb2.QuestCameraInfo | None = None
        self.latest_stereo_rx_mono_ms: float | None = None
        self.latest_camera_info_rx_mono_ms: float | None = None
        self.decoded_stereo = 0
        self.decoded_camera_info = 0
        self.decode_failed = 0

    def update_stereo(self, msg: quest_pb2.QuestStereoFrame) -> None:
        self.latest_stereo = msg
        self.latest_stereo_rx_mono_ms = time.perf_counter() * 1000.0
        self.decoded_stereo += 1

    def update_camera_info(self, msg: quest_pb2.QuestCameraInfo) -> None:
        self.latest_camera_info = msg
        self.latest_camera_info_rx_mono_ms = time.perf_counter() * 1000.0
        self.decoded_camera_info += 1

    def snapshot_stats(self, *, received: int | None = None, invalid_multipart: int = 0, zmq_errors: int = 0) -> QuestInputStats:
        now_ms = time.perf_counter() * 1000.0
        received_count = self.decoded_stereo + self.decoded_camera_info if received is None else received
        stereo_frame_id = (
            int(self.latest_stereo.header.frame_id)
            if self.latest_stereo is not None and self.latest_stereo.HasField("header")
            else None
        )
        camera_info_frame_id = (
            int(self.latest_camera_info.header.frame_id)
            if self.latest_camera_info is not None and self.latest_camera_info.HasField("header")
            else None
        )
        return QuestInputStats(
            received=received_count,
            decoded_stereo=self.decoded_stereo,
            decoded_camera_info=self.decoded_camera_info,
            decode_failed=self.decode_failed,
            invalid_multipart=invalid_multipart,
            zmq_errors=zmq_errors,
            latest_stereo_frame_id=stereo_frame_id,
            latest_camera_info_frame_id=camera_info_frame_id,
            latest_stereo_age_ms=(
                now_ms - self.latest_stereo_rx_mono_ms
                if self.latest_stereo_rx_mono_ms is not None
                else None
            ),
            latest_camera_info_age_ms=(
                now_ms - self.latest_camera_info_rx_mono_ms
                if self.latest_camera_info_rx_mono_ms is not None
                else None
            ),
        )


class QuestStreamReceiver:
    """Unity `QuestStreamPublisher` 的 Python 侧接收器。"""

    def __init__(
        self,
        listen_host: str = "*",
        listen_port: int = 15557,
        hwm: int = 20,
        topics: list[str] | None = None,
    ) -> None:
        self.topics = topics or [QUEST_STEREO, QUEST_CAMERA_INFO]
        self.subscriber = ZmqTopicSubscriber(
            listen_host=listen_host,
            listen_port=listen_port,
            hwm=hwm,
            topics=self.topics,
        )
        self.store = LatestQuestInputStore()

    @property
    def endpoint(self) -> str:
        """当前 ZMQ 监听 endpoint。"""

        return self.subscriber.endpoint

    def start(self) -> None:
        """启动底层 ZMQ topic subscriber。"""

        self.subscriber.start()

    def close(self) -> None:
        """关闭底层 ZMQ topic subscriber。"""

        self.subscriber.close()

    def poll_latest(self, timeout_ms: int = 0) -> dict[str, Any]:
        """轮询 ZMQ topic payload，并解码 Quest Protobuf。"""

        latest_payloads = self.subscriber.poll_latest(timeout_ms=timeout_ms)
        if not latest_payloads:
            return {}

        decoded: dict[str, Any] = {}
        for topic, payload in latest_payloads.items():
            try:
                if topic == QUEST_STEREO:
                    msg = quest_pb2.QuestStereoFrame()
                    msg.ParseFromString(payload)
                    self.store.update_stereo(msg)
                    decoded[topic] = msg
                elif topic == QUEST_CAMERA_INFO:
                    msg = quest_pb2.QuestCameraInfo()
                    msg.ParseFromString(payload)
                    self.store.update_camera_info(msg)
                    decoded[topic] = msg
                else:
                    logging.debug("[QuestStreamReceiver] Ignore unknown topic=%s", topic)
            except DecodeError:
                self.store.decode_failed += 1
                logging.warning("[QuestStreamReceiver] Protobuf decode failed topic=%s bytes=%d", topic, len(payload))
        return decoded

    def get_latest_stereo(self) -> quest_pb2.QuestStereoFrame | None:
        return self.store.latest_stereo

    def get_latest_camera_info(self) -> quest_pb2.QuestCameraInfo | None:
        return self.store.latest_camera_info

    def get_stats(self) -> QuestInputStats:
        topic_stats = self.subscriber.get_stats()
        return self.store.snapshot_stats(
            received=topic_stats.received,
            invalid_multipart=topic_stats.invalid_multipart,
            zmq_errors=topic_stats.zmq_errors,
        )

    def __enter__(self) -> "QuestStreamReceiver":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()


__all__ = ["LatestQuestInputStore", "QuestInputStats", "QuestStreamReceiver"]
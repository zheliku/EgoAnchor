"""Quest stream 接收器。

本模块把纯传输层的 topic payload 转换成 Quest Protobuf，并写入 latest-only 输入缓存。
"""

from __future__ import annotations

import logging
from typing import Any

from google.protobuf.message import DecodeError

from egoanchor.protocol import QUEST_CAMERA_INFO, QUEST_STEREO, quest_pb2
from egoanchor.runtime import LatestQuestInputStore, QuestInputStats
from egoanchor.transport import ZmqTopicSubscriber


class QuestStreamReceiver:
    """Unity QuestStreamPublisher 的 Python 侧接收器。"""

    def __init__(self, listen_host: str = "*", listen_port: int = 15557, hwm: int = 20, topics: list[str] | None = None) -> None:
        """组装 ZMQ subscriber 与 Quest 输入缓存。"""

        self.topics = topics or [QUEST_STEREO, QUEST_CAMERA_INFO]
        self.subscriber = ZmqTopicSubscriber(listen_host=listen_host, listen_port=listen_port, hwm=hwm, topics=self.topics)
        self.store = LatestQuestInputStore()

    @property
    def endpoint(self) -> str:
        """返回当前监听 endpoint。"""

        return self.subscriber.endpoint

    def start(self) -> None:
        """启动底层 ZMQ subscriber。"""

        self.subscriber.start()

    def close(self) -> None:
        """关闭底层 ZMQ subscriber。"""

        self.subscriber.close()

    def poll_latest(self, timeout_ms: int = 0) -> dict[str, Any]:
        """轮询 ZMQ 并解码本轮每个 topic 的最新 Protobuf。"""

        latest_payloads = self.subscriber.poll_latest(timeout_ms=timeout_ms)
        if not latest_payloads:
            return {}

        decoded: dict[str, Any] = {}
        for topic, payload in latest_payloads.items():
            try:
                if topic == QUEST_STEREO:
                    msg = quest_pb2.QuestStereoFrame()
                    msg.ParseFromString(payload)
                    if self.store.update_stereo(msg):
                        decoded[topic] = msg
                elif topic == QUEST_CAMERA_INFO:
                    msg = quest_pb2.QuestCameraInfo()
                    msg.ParseFromString(payload)
                    self.store.update_camera_info(msg)
                    decoded[topic] = msg
                else:
                    logging.debug("[QuestStreamReceiver] ignore unknown topic=%s", topic)
            except DecodeError:
                self.store.mark_decode_failed()
                logging.warning("[QuestStreamReceiver] protobuf decode failed topic=%s bytes=%d", topic, len(payload))
        return decoded

    def get_latest_stereo(self) -> quest_pb2.QuestStereoFrame | None:
        """读取最新 stereo 帧。"""

        return self.store.latest_stereo

    def get_latest_camera_info(self) -> quest_pb2.QuestCameraInfo | None:
        """读取最新 camera_info。"""

        return self.store.latest_camera_info

    def get_stats(self) -> QuestInputStats:
        """合并 ZMQ 与 Protobuf 层统计。"""

        topic_stats = self.subscriber.get_stats()
        return self.store.snapshot_stats(
            received=topic_stats.received,
            invalid_multipart=topic_stats.invalid_multipart,
            zmq_errors=topic_stats.zmq_errors,
        )

    def __enter__(self) -> "QuestStreamReceiver":
        """支持 `with` 语句自动启动接收器。"""

        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """离开 `with` 语句时自动关闭接收器。"""

        self.close()

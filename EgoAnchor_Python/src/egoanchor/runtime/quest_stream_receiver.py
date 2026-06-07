"""Quest stream 接收器。

本模块把纯传输层的 topic payload 转换成 Quest Protobuf，并写入 latest-only 输入缓存。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from google.protobuf.message import DecodeError

from egoanchor.protocol import QUEST_CAMERA_INFO, QUEST_STEREO, extract_client_id, extract_frame_id, extract_session_id, quest_pb2
from egoanchor.transport import ZmqTopicSubscriber
from egoanchor.utils import LatestValueStore, get_logger

LOGGER = get_logger(__name__, component="QuestStreamReceiver")
"""Quest stream receiver 日志记录器。"""


@dataclass(frozen=True)
class QuestInputStats:
    """Quest 输入接收与解码统计。"""

    received: int
    decoded_stereo: int
    decoded_camera_info: int
    decode_failed: int
    invalid_multipart: int
    zmq_errors: int
    stale_stereo_dropped: int
    stream_restarts: int
    camera_info_version: int
    latest_stereo_frame_id: int | None
    latest_camera_info_frame_id: int | None
    latest_session_id: str
    latest_client_id: str
    latest_stereo_age_ms: float | None
    latest_camera_info_age_ms: float | None


class LatestQuestInputStore:
    """按 topic 保存 Quest 输入最新值。"""

    def __init__(self) -> None:
        """初始化 stereo、camera_info 与统计计数器。"""

        self._stereo_store: LatestValueStore[quest_pb2.QuestStereoFrame] = LatestValueStore()
        self._camera_info_store: LatestValueStore[quest_pb2.QuestCameraInfo] = LatestValueStore()
        self.latest_stereo_frame_id: int | None = None
        self.latest_camera_info_frame_id: int | None = None
        self.latest_session_id = ""
        self.latest_stereo_session_id = ""
        self.latest_camera_info_session_id = ""
        self.latest_client_id = ""
        self.camera_info_version = 0
        self.decoded_stereo = 0
        self.decoded_camera_info = 0
        self.decode_failed = 0
        self.stale_stereo_dropped = 0
        self.stream_restarts = 0

    @property
    def latest_stereo(self) -> quest_pb2.QuestStereoFrame | None:
        """返回最新 stereo 帧；没有收到时为 None。"""

        return self._stereo_store.peek()

    @property
    def latest_camera_info(self) -> quest_pb2.QuestCameraInfo | None:
        """返回最新 camera_info；没有收到时为 None。"""

        return self._camera_info_store.peek()

    def update_stereo(self, msg: quest_pb2.QuestStereoFrame) -> bool:
        """更新 stereo 最新帧；同一 Unity 会话内 frame_id 倒退或重复时丢弃。"""

        frame_id = extract_frame_id(msg)
        session_id = extract_session_id(msg)
        client_id = extract_client_id(msg)
        same_session = not session_id or not self.latest_stereo_session_id or session_id == self.latest_stereo_session_id

        if same_session and frame_id is not None and self.latest_stereo_frame_id is not None and frame_id <= self.latest_stereo_frame_id:
            self.stale_stereo_dropped += 1
            return False

        if not same_session:
            self.stream_restarts += 1
            self._stereo_store.clear()
            self.latest_stereo_frame_id = None

        self._stereo_store.put(msg, count_drop=True)
        self.latest_stereo_frame_id = frame_id
        self.latest_stereo_session_id = session_id or self.latest_stereo_session_id
        self.latest_session_id = self.latest_stereo_session_id or self.latest_camera_info_session_id
        self.latest_client_id = client_id or self.latest_client_id
        self.decoded_stereo += 1
        return True

    def update_camera_info(self, msg: quest_pb2.QuestCameraInfo) -> None:
        """更新 camera_info 最新值，并递增独立版本号。"""

        self._camera_info_store.put(msg, count_drop=True)
        self.latest_camera_info_frame_id = extract_frame_id(msg)
        self.latest_camera_info_session_id = extract_session_id(msg) or self.latest_camera_info_session_id
        self.latest_session_id = self.latest_stereo_session_id or self.latest_camera_info_session_id
        self.latest_client_id = extract_client_id(msg) or self.latest_client_id
        self.decoded_camera_info += 1
        self.camera_info_version += 1

    def mark_decode_failed(self) -> None:
        """记录一次 Protobuf 解码失败。"""

        self.decode_failed += 1

    def snapshot_stats(self, *, received: int, invalid_multipart: int, zmq_errors: int) -> QuestInputStats:
        """生成对外展示的输入统计快照。"""

        now_ms = time.perf_counter() * 1000.0
        return QuestInputStats(
            received=received,
            decoded_stereo=self.decoded_stereo,
            decoded_camera_info=self.decoded_camera_info,
            decode_failed=self.decode_failed,
            invalid_multipart=invalid_multipart,
            zmq_errors=zmq_errors,
            stale_stereo_dropped=self.stale_stereo_dropped,
            stream_restarts=self.stream_restarts,
            camera_info_version=self.camera_info_version,
            latest_stereo_frame_id=self.latest_stereo_frame_id,
            latest_camera_info_frame_id=self.latest_camera_info_frame_id,
            latest_session_id=self.latest_session_id,
            latest_client_id=self.latest_client_id,
            latest_stereo_age_ms=self._stereo_store.age_ms(now_ms),
            latest_camera_info_age_ms=self._camera_info_store.age_ms(now_ms),
        )


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
                    LOGGER.debug("ignore unknown topic=%s", topic)
            except DecodeError:
                self.store.mark_decode_failed()
                LOGGER.warning("protobuf decode failed topic=%s bytes=%d", topic, len(payload))
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

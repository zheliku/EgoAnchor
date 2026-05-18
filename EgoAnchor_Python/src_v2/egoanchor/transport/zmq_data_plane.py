"""v2 ZMQ 数据面接收器。

职责边界：
- 只处理 ZMQ SUB socket、multipart topic、Protobuf 解析和 topic 级 latest-drain。
- 不导入 OpenCV，不做 JPEG 解码，不调用任何模型。
- 输出最新 QuestStereoFrame / QuestCameraInfo，供 runtime 或 demo 使用。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import zmq
from google.protobuf.message import DecodeError

from egoanchor.protocol import QUEST_CAMERA_INFO, QUEST_STEREO
from egoanchor.protocol import quest_pb2


@dataclass(frozen=True)
class DataPlaneStats:
    """ZMQ 数据面累计统计。"""

    received: int
    decoded_stereo: int
    decoded_camera_info: int
    decode_failed: int
    latest_stereo_frame_id: int | None
    latest_camera_info_frame_id: int | None
    latest_stereo_age_ms: float | None
    latest_camera_info_age_ms: float | None


class LatestQuestInputStore:
    """Quest 输入最新值缓存。

    latest-only 是实时视频链路的核心策略：
    - stereo 高频消息只保留每个 topic 最新一帧，避免模型或显示阻塞时累积旧帧。
    - camera_info 虽然低频，也独立缓存，避免被 stereo drain 掩盖。
    """

    def __init__(self) -> None:
        self.latest_stereo: quest_pb2.QuestStereoFrame | None = None
        self.latest_camera_info: quest_pb2.QuestCameraInfo | None = None
        self.latest_stereo_rx_mono_ms: float | None = None
        self.latest_camera_info_rx_mono_ms: float | None = None
        self.received = 0
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

    def snapshot_stats(self) -> DataPlaneStats:
        now_ms = time.perf_counter() * 1000.0
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
        return DataPlaneStats(
            received=self.received,
            decoded_stereo=self.decoded_stereo,
            decoded_camera_info=self.decoded_camera_info,
            decode_failed=self.decode_failed,
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


class ZmqDataPlaneReceiver:
    """Unity/Quest -> Python 的 v2 ZMQ 数据面接收器。"""

    def __init__(
        self,
        listen_host: str = "*",
        listen_port: int = 15557,
        hwm: int = 20,
        topics: list[str] | None = None,
    ) -> None:
        self.endpoint = f"tcp://{listen_host}:{int(listen_port)}"
        self.hwm = int(hwm)
        self.topics = topics or [QUEST_STEREO, QUEST_CAMERA_INFO]
        self.store = LatestQuestInputStore()
        self._ctx: zmq.Context[zmq.Socket[bytes]] = zmq.Context.instance()
        self._socket: zmq.Socket[bytes] | None = None

    def start(self) -> None:
        """创建 SUB socket 并 bind 到数据面端口。"""

        if self._socket is not None:
            return
        socket = self._ctx.socket(zmq.SUB)
        socket.setsockopt(zmq.RCVHWM, max(self.hwm, 1))
        for topic in self.topics:
            socket.setsockopt_string(zmq.SUBSCRIBE, topic)
        socket.bind(self.endpoint)
        self._socket = socket
        logging.info("[ZmqDataPlaneReceiver] Listening on %s topics=%s", self.endpoint, self.topics)

    def close(self) -> None:
        """关闭 socket。"""

        if self._socket is not None:
            self._socket.close(linger=0)
            self._socket = None

    def poll_latest(self, timeout_ms: int = 0) -> dict[str, Any]:
        """轮询并按 topic latest-drain。

        返回值是本次 poll 解码成功的最新消息字典；内部 store 同步更新。
        """

        latest_payloads = self._recv_all_latest_payloads(timeout_ms=timeout_ms)
        if not latest_payloads:
            return {}

        decoded: dict[str, Any] = {}
        for topic, payload in latest_payloads.items():
            self.store.received += 1
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
                    logging.debug("[ZmqDataPlaneReceiver] Ignore unknown topic=%s", topic)
            except DecodeError:
                self.store.decode_failed += 1
                logging.warning("[ZmqDataPlaneReceiver] Protobuf decode failed topic=%s bytes=%d", topic, len(payload))
        return decoded

    def get_latest_stereo(self) -> quest_pb2.QuestStereoFrame | None:
        return self.store.latest_stereo

    def get_latest_camera_info(self) -> quest_pb2.QuestCameraInfo | None:
        return self.store.latest_camera_info

    def get_stats(self) -> DataPlaneStats:
        return self.store.snapshot_stats()

    def _recv_all_latest_payloads(self, timeout_ms: int) -> dict[str, bytes] | None:
        """读取队列中所有可用 multipart，只保留每个 topic 最新 payload。"""

        if self._socket is None:
            raise RuntimeError("ZmqDataPlaneReceiver 尚未 start。")

        try:
            if not self._socket.poll(timeout=max(int(timeout_ms), 0)):
                return None

            latest: dict[str, bytes] = {}
            while True:
                try:
                    parts = self._socket.recv_multipart(flags=zmq.NOBLOCK)
                except zmq.Again:
                    break

                if len(parts) != 2:
                    logging.warning("[ZmqDataPlaneReceiver] Drop invalid multipart len=%d", len(parts))
                    continue
                topic = parts[0].decode("utf-8", errors="replace")
                latest[topic] = bytes(parts[1])
            return latest
        except zmq.ZMQError as exc:
            logging.warning("[ZmqDataPlaneReceiver] ZMQ receive error: %s", exc)
            return None

    def __enter__(self) -> "ZmqDataPlaneReceiver":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

"""v2 ZMQ topic 订阅器。

职责边界与 Unity `ZmqTopicPublisher.cs` 对齐：
- 只处理 ZMQ SUB socket、multipart `[topic_utf8, payload_bytes]` 和 topic 级 latest-drain。
- 不导入 Protobuf schema，不知道 Quest 图像、camera_info、anchor 或模型。
- 输出 topic -> payload bytes，交给 runtime/client 层做协议解析和业务缓存。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import zmq


@dataclass(frozen=True)
class ZmqTopicSubscriberStats:
    """ZMQ topic subscriber 累计统计。"""

    received: int
    invalid_multipart: int
    zmq_errors: int
    latest_topic_names: tuple[str, ...]
    latest_topic_age_ms: dict[str, float]


@dataclass
class LatestTopicPayloadStore:
    """topic -> latest payload bytes 缓存。"""

    latest_payload_by_topic: dict[str, bytes] = field(default_factory=dict)
    latest_rx_mono_ms_by_topic: dict[str, float] = field(default_factory=dict)
    received: int = 0
    invalid_multipart: int = 0
    zmq_errors: int = 0

    def update(self, topic: str, payload: bytes) -> None:
        """记录某个 topic 最新 payload。"""

        self.latest_payload_by_topic[topic] = payload
        self.latest_rx_mono_ms_by_topic[topic] = time.perf_counter() * 1000.0
        self.received += 1

    def snapshot_stats(self) -> ZmqTopicSubscriberStats:
        """返回 topic subscriber 统计快照。"""

        now_ms = time.perf_counter() * 1000.0
        ages = {
            topic: now_ms - rx_ms
            for topic, rx_ms in self.latest_rx_mono_ms_by_topic.items()
        }
        return ZmqTopicSubscriberStats(
            received=self.received,
            invalid_multipart=self.invalid_multipart,
            zmq_errors=self.zmq_errors,
            latest_topic_names=tuple(sorted(self.latest_payload_by_topic.keys())),
            latest_topic_age_ms=ages,
        )


class ZmqTopicSubscriber:
    """Unity `ZmqTopicPublisher` 的 Python 侧对等 SUB 接收器。"""

    def __init__(
        self,
        listen_host: str = "*",
        listen_port: int = 15557,
        hwm: int = 20,
        topics: list[str] | None = None,
    ) -> None:
        self.endpoint = f"tcp://{listen_host}:{int(listen_port)}"
        self.hwm = int(hwm)
        self.topics = tuple(topics or [])
        self.store = LatestTopicPayloadStore()
        self._ctx: zmq.Context[zmq.Socket[bytes]] = zmq.Context.instance()
        self._socket: zmq.Socket[bytes] | None = None

    def start(self) -> None:
        """创建 SUB socket 并 bind 到 topic 接收端口。"""

        if self._socket is not None:
            return
        socket = self._ctx.socket(zmq.SUB)
        socket.setsockopt(zmq.RCVHWM, max(self.hwm, 1))
        if self.topics:
            for topic in self.topics:
                socket.setsockopt_string(zmq.SUBSCRIBE, topic)
        else:
            socket.setsockopt_string(zmq.SUBSCRIBE, "")
        socket.bind(self.endpoint)
        self._socket = socket
        logging.info("[ZmqTopicSubscriber] Listening on %s topics=%s", self.endpoint, self.topics or ("*",))

    def close(self) -> None:
        """关闭 socket。"""

        if self._socket is not None:
            self._socket.close(linger=0)
            self._socket = None

    def poll_latest(self, timeout_ms: int = 0) -> dict[str, bytes]:
        """轮询并按 topic latest-drain。

        返回值只包含本次 poll 中收到的 topic 最新 payload；内部 store 会同步保留跨 tick 最新值。
        """

        latest = self._recv_all_latest_payloads(timeout_ms=timeout_ms)
        if not latest:
            return {}
        for topic, payload in latest.items():
            self.store.update(topic, payload)
        return latest

    def get_latest_payload(self, topic: str) -> bytes | None:
        """读取某个 topic 的最新 payload bytes。"""

        return self.store.latest_payload_by_topic.get(topic)

    def get_stats(self) -> ZmqTopicSubscriberStats:
        """返回累计统计。"""

        return self.store.snapshot_stats()

    def _recv_all_latest_payloads(self, timeout_ms: int) -> dict[str, bytes] | None:
        """读取队列中所有可用 multipart，只保留每个 topic 最新 payload。"""

        if self._socket is None:
            raise RuntimeError("ZmqTopicSubscriber 尚未 start。")

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
                    self.store.invalid_multipart += 1
                    logging.warning("[ZmqTopicSubscriber] Drop invalid multipart len=%d", len(parts))
                    continue
                topic = parts[0].decode("utf-8", errors="replace")
                latest[topic] = bytes(parts[1])
            return latest
        except zmq.ZMQError as exc:
            self.store.zmq_errors += 1
            logging.warning("[ZmqTopicSubscriber] ZMQ receive error: %s", exc)
            return None

    def __enter__(self) -> "ZmqTopicSubscriber":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()


__all__ = ["LatestTopicPayloadStore", "ZmqTopicSubscriber", "ZmqTopicSubscriberStats"]
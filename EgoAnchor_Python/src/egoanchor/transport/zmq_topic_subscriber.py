"""ZMQ topic 订阅器。

本模块是纯传输层：只处理 socket、multipart 格式和 topic 级 latest-drain，
不导入 Protobuf、不理解 Quest 图像或 anchor 业务。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import zmq


@dataclass(frozen=True)
class ZmqTopicSubscriberStats:
    """ZMQ topic subscriber 的累计统计快照。"""

    received: int
    invalid_multipart: int
    zmq_errors: int
    latest_topic_names: tuple[str, ...]
    latest_topic_age_ms: dict[str, float]


@dataclass
class LatestTopicPayloadStore:
    """topic -> latest payload bytes 的轻量缓存。"""

    latest_payload_by_topic: dict[str, bytes] = field(default_factory=dict)
    latest_rx_mono_ms_by_topic: dict[str, float] = field(default_factory=dict)
    received: int = 0
    invalid_multipart: int = 0
    zmq_errors: int = 0

    def update(self, topic: str, payload: bytes) -> None:
        """记录某个 topic 的最新 payload。"""

        self.latest_payload_by_topic[topic] = payload
        self.latest_rx_mono_ms_by_topic[topic] = time.perf_counter() * 1000.0
        self.received += 1

    def snapshot_stats(self) -> ZmqTopicSubscriberStats:
        """生成当前缓存状态的只读统计。"""

        now_ms = time.perf_counter() * 1000.0
        ages = {topic: now_ms - rx_ms for topic, rx_ms in self.latest_rx_mono_ms_by_topic.items()}
        return ZmqTopicSubscriberStats(
            received=self.received,
            invalid_multipart=self.invalid_multipart,
            zmq_errors=self.zmq_errors,
            latest_topic_names=tuple(sorted(self.latest_payload_by_topic.keys())),
            latest_topic_age_ms=ages,
        )


class ZmqTopicSubscriber:
    """接收 Unity PUB 发送的 multipart `[topic_utf8, payload_bytes]`。"""

    def __init__(self, listen_host: str = "*", listen_port: int = 15557, hwm: int = 20, topics: list[str] | None = None) -> None:
        """初始化 SUB socket 参数，但不立即 bind。"""

        self._started = False
        self.endpoint = f"tcp://{listen_host}:{int(listen_port)}"
        self.hwm = max(int(hwm), 1)
        self.topics = tuple(topics or [])
        self.store = LatestTopicPayloadStore()
        self._ctx = zmq.Context.instance()
        self._socket: Any | None = None

    def start(self) -> None:
        """创建并绑定 SUB socket。"""

        if self._started:
            return
        self._started = True
        logging.info("[ZmqTopicSubscriber] starting")
        socket = self._ctx.socket(zmq.SUB)
        socket.setsockopt(zmq.RCVHWM, self.hwm)
        if self.topics:
            for topic in self.topics:
                socket.setsockopt_string(zmq.SUBSCRIBE, topic)
        else:
            socket.setsockopt_string(zmq.SUBSCRIBE, "")
        try:
            socket.bind(self.endpoint)
            self._socket = socket
        except Exception:
            socket.close(linger=0)
            self._started = False
            raise
        logging.info("[ZmqTopicSubscriber] listening endpoint=%s topics=%s hwm=%d", self.endpoint, self.topics or ("*",), self.hwm)

    def close(self) -> None:
        """关闭 SUB socket，linger=0 避免退出 demo 时阻塞。"""

        if not self._started:
            return
        self._started = False
        logging.info("[ZmqTopicSubscriber] closing")
        if self._socket is not None:
            self._socket.close(linger=0)
            self._socket = None

    def poll_latest(self, timeout_ms: int = 0) -> dict[str, bytes]:
        """读取当前可用消息，并只返回每个 topic 的最新 payload。"""

        latest = self._recv_all_latest_payloads(timeout_ms=timeout_ms)
        if not latest:
            return {}
        for topic, payload in latest.items():
            self.store.update(topic, payload)
        return latest

    def get_stats(self) -> ZmqTopicSubscriberStats:
        """返回累计接收统计。"""

        return self.store.snapshot_stats()

    def _recv_all_latest_payloads(self, timeout_ms: int) -> dict[str, bytes] | None:
        """内部 drain socket 队列，只保留每个 topic 最后一条消息。"""

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
                    logging.warning("[ZmqTopicSubscriber] drop invalid multipart len=%d", len(parts))
                    continue
                topic = parts[0].decode("utf-8", errors="replace")
                latest[topic] = bytes(parts[1])
            return latest
        except zmq.ZMQError as exc:
            self.store.zmq_errors += 1
            logging.warning("[ZmqTopicSubscriber] receive error: %s", exc)
            return None


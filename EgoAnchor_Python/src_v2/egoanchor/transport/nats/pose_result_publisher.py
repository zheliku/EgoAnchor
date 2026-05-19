"""NATS PoseResult 发布器。"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import Future
from types import SimpleNamespace

from google.protobuf.message import Message as ProtobufMessage

from .nats_control_client import NatsControlClient
from .nats_control_settings import NatsControlSettings


class PoseResultPublisher:
    """同步 TrackingRuntime 可调用的 PoseResult 发布器。

    本类只处理 `PoseResult` subject、Protobuf 序列化、Future 限流和统计。
    它不导入 perception，也不负责 `PoseObservation -> PoseResult` 映射；该映射属于
    runtime 层，避免 transport 反向依赖算法/感知层。
    """

    def __init__(self, client: NatsControlClient, *, subject: str, max_pending_futures: int = 32) -> None:
        self.client = client
        self.subject = str(subject)
        self.max_pending_futures = max(1, int(max_pending_futures))
        self._pending: list[Future[None]] = []
        self._published = 0
        self._failed = 0

    @classmethod
    def from_config(cls, cfg: SimpleNamespace) -> "PoseResultPublisher":
        """从 v2 runtime 配置创建 PoseResult 发布器。"""

        settings = NatsControlSettings.from_config(cfg)
        return cls(
            NatsControlClient(settings),
            subject=settings.pose_result_subject,
            max_pending_futures=settings.max_pending_futures,
        )

    @property
    def enabled(self) -> bool:
        """Pose 发布链路是否启用。"""

        return self.client.enabled

    @property
    def published_count(self) -> int:
        """已成功投递到 NATS 客户端的消息数量。"""

        return self._published

    @property
    def failed_count(self) -> int:
        """发布失败或被丢弃的消息数量。"""

        return self._failed + self.client.connect_failed_count

    def start(self) -> None:
        """启动底层 NATS client。"""

        self.client.start()

    def close(self) -> None:
        """关闭底层 NATS client。"""

        self.client.close()

    def publish_pose_result(self, msg: ProtobufMessage) -> bool:
        """发布 Protobuf PoseResult bytes。

        返回值只表示“是否成功投递到后台 event loop”，不等价于 NATS server 已持久化；
        NATS pub/sub 本身也是 at-most-once，小 pose 流按 latest-only 语义使用。
        """

        if not self.enabled:
            return False
        loop = self.client.loop
        if loop is None or not loop.is_running() or not self.client.is_connected:
            self._failed += 1
            return False
        self._drain_completed_futures()
        if len(self._pending) >= self.max_pending_futures:
            # 避免 NATS 断连时无限积累 Future；pose 流只保留最新语义，直接丢弃当前包。
            self._failed += 1
            return False
        payload = msg.SerializeToString()
        future: Future[None] = asyncio.run_coroutine_threadsafe(self._publish_bytes(payload), loop)
        self._pending.append(future)
        return True

    async def _publish_bytes(self, payload: bytes) -> None:
        """实际 NATS publish 协程。"""

        try:
            await self.client.publish(self.subject, payload)
            self._published += 1
        except Exception as exc:
            self._failed += 1
            logging.debug("[PoseResultPublisher] publish PoseResult 失败 subject=%s：%s", self.subject, exc)

    def _drain_completed_futures(self) -> None:
        """清理已完成 Future，并观察异常避免 unobserved exception。"""

        if not self._pending:
            return
        remaining: list[Future[None]] = []
        for future in self._pending:
            if not future.done():
                remaining.append(future)
                continue
            try:
                future.result()
            except Exception as exc:
                self._failed += 1
                logging.debug("[PoseResultPublisher] 后台 publish future 异常：%s", exc)
        self._pending = remaining


__all__ = ["PoseResultPublisher"]
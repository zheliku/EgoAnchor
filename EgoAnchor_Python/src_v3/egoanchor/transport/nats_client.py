"""v3 NATS 消息面传输实现。

本模块是计划中的唯一 NATS transport 文件：``transport/nats_client.py``。
它只负责 NATS 连接、bytes publish/subscribe、后台 asyncio loop 和 publish 限流，
不理解 perception、Unity anchor 或 pipeline/GPU 状态。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable, Iterable
from concurrent.futures import Future
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from google.protobuf.message import Message as ProtobufMessage

from egoanchor.protocol import POSE_RESULT

MessageCallback = Callable[[str, bytes, str | None], Awaitable[bytes | None]]
"""NATS bytes callback 类型：输入 subject/payload/reply，输出可选 reply payload。"""


@dataclass(frozen=True, slots=True)
class NatsMessageSettings:
    """NATS 消息面运行参数。

    配置对象只描述连接、subject 和发布队列容量，不包含任何 pose 语义，
    因此可以长期保持在 transport 层。
    """

    enabled: bool = False
    """是否启用 NATS 消息面。"""

    url: str = "nats://127.0.0.1:4222"
    """NATS server URL；Quest/Unity 真机测试时通常指向开发机 IP。"""

    pose_result_subject: str = POSE_RESULT
    """PoseResult 发布 subject，来自共享协议契约。"""

    client_name: str = "egoanchor-python-v3"
    """Python NATS 客户端名称，便于 nats-server 日志排查。"""

    connect_timeout_s: float = 2.0
    """初次连接超时时间，单位秒。"""

    request_timeout_s: float = 1.0
    """request/reply 默认超时，当前主要预留给未来 Python 主动请求。"""

    max_pending_futures: int = 32
    """后台 publish Future 最大积压数量；超过后丢弃新 pose，保持 latest-only。"""

    wait_ready_on_start: bool = False
    """start 时是否等待首次连接完成；关闭可避免 nats-server 未启动时阻塞模型加载。"""

    @classmethod
    def from_config(cls, cfg: SimpleNamespace) -> "NatsMessageSettings":
        """从 v3 TOML 配置读取 NATS 消息面参数。"""

        network = getattr(cfg, "network", SimpleNamespace())
        message = getattr(network, "message_plane", SimpleNamespace())
        return cls(
            enabled=bool(getattr(message, "enabled", False)),
            url=str(getattr(message, "url", "nats://127.0.0.1:4222")),
            pose_result_subject=str(getattr(message, "pose_result_subject", POSE_RESULT)),
            client_name=str(getattr(message, "client_name", "egoanchor-python-v3")),
            connect_timeout_s=float(getattr(message, "connect_timeout_s", 2.0)),
            request_timeout_s=float(getattr(message, "request_timeout_s", 1.0)),
            max_pending_futures=int(getattr(message, "max_pending_futures", 32)),
            wait_ready_on_start=bool(getattr(message, "wait_ready_on_start", False)),
        )


class NatsMessageClient:
    """后台 asyncio NATS bytes 客户端。

    Runtime 主线程只调用本类的同步入口；真正的 NATS I/O 在后台线程执行。
    request/reply handler 通过 `add_subscription` 注册，回调只处理 bytes，不接触 pipeline。
    """

    def __init__(self, settings: NatsMessageSettings) -> None:
        """保存 NATS 配置并初始化后台线程状态。"""

        self.settings = settings
        """NATS 消息面配置。"""

        self._loop: asyncio.AbstractEventLoop | None = None
        """后台 asyncio event loop；未启动时为 None。"""

        self._thread: threading.Thread | None = None
        """承载 event loop 的后台线程。"""

        self._ready = threading.Event()
        """首次连接尝试完成事件；用于可选等待。"""

        self._closed = False
        """关闭标记；用于避免退出时继续重连或发布。"""

        self._nc: Any | None = None
        """nats-py 连接对象；保持 Any，避免 transport 类型向上泄漏。"""

        self._subscriptions: list[Any] = []
        """nats-py subscription handles，用于关闭阶段释放引用。"""

        self._pending_subscriptions: list[tuple[str, MessageCallback]] = []
        """连接建立前登记的 subject callback 列表。"""

        self._connect_failed = 0
        """NATS 连接失败计数。"""

    @property
    def enabled(self) -> bool:
        """消息面是否启用。"""

        return self.settings.enabled

    @property
    def url(self) -> str:
        """当前 NATS server URL。"""

        return self.settings.url

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        """返回后台 event loop；未启动时为 None。"""

        return self._loop

    @property
    def is_connected(self) -> bool:
        """是否已有可发布的 NATS 连接。"""

        return self._nc is not None

    @property
    def connect_failed_count(self) -> int:
        """累计连接失败次数。"""

        return self._connect_failed

    def start(self) -> None:
        """启动后台 NATS event loop 并尝试连接。"""

        if not self.enabled:
            logging.info("[NatsMessageClient:v3] network.message_plane.enabled=false，消息面保持关闭。")
            return
        if self._thread is not None:
            return

        self._closed = False
        self._ready.clear()
        self._thread = threading.Thread(target=self._run_loop_thread, name="EgoAnchorV3NatsMessageClient", daemon=True)
        self._thread.start()
        if self.settings.wait_ready_on_start:
            timeout_s = max(float(self.settings.connect_timeout_s) + 0.5, 0.5)
            if not self._ready.wait(timeout=timeout_s):
                logging.warning("[NatsMessageClient:v3] 等待 NATS 首次连接超时，后续消息会在连接可用前被丢弃。")

    def close(self) -> None:
        """关闭后台 NATS 连接和 event loop。"""

        self._closed = True
        loop = self._loop
        if loop is None:
            return

        if loop.is_running():
            try:
                future = asyncio.run_coroutine_threadsafe(self._close_async(), loop)
                future.result(timeout=1.0)
            except Exception as exc:  # pragma: no cover - 退出路径只记录，不影响进程关闭
                logging.debug("[NatsMessageClient:v3] 关闭 NATS 时出现非致命异常：%s", exc)
            loop.call_soon_threadsafe(loop.stop)

        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._thread = None
        self._loop = None

    async def publish(self, subject: str, payload: bytes) -> None:
        """向指定 subject 发布 bytes payload。"""

        if self._nc is None:
            raise RuntimeError("NATS client is not connected")
        await self._nc.publish(subject, payload)

    def add_subscription(self, subject: str, callback: MessageCallback) -> None:
        """登记一个 bytes 订阅；必须在 start 前调用。"""

        self._pending_subscriptions.append((subject, callback))

    def add_subscriptions(self, specs: Iterable[tuple[str, MessageCallback]]) -> None:
        """批量登记订阅。"""

        for subject, callback in specs:
            self.add_subscription(subject, callback)

    def _run_loop_thread(self) -> None:
        """后台线程入口：创建并运行 asyncio event loop。"""

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.create_task(self._connect_async())
        try:
            self._loop.run_forever()
        finally:
            self._loop.run_until_complete(self._close_async())
            self._loop.close()

    async def _connect_async(self) -> None:
        """连接 NATS；运行期导入 nats-py，保证关闭消息面时不触发依赖加载。"""

        try:
            import nats  # type: ignore

            self._nc = await nats.connect(
                servers=[self.settings.url],
                name=self.settings.client_name,
                connect_timeout=float(self.settings.connect_timeout_s),
                allow_reconnect=True,
                max_reconnect_attempts=-1,
            )
            await self._attach_pending_subscriptions()
            logging.info("[NatsMessageClient:v3] connected url=%s", self.settings.url)
        except Exception as exc:
            self._nc = None
            self._connect_failed += 1
            logging.error("[NatsMessageClient:v3] 连接 NATS 失败 url=%s：%s", self.settings.url, exc)
        finally:
            self._ready.set()

    async def _attach_pending_subscriptions(self) -> None:
        """把 start 前登记的 subscriptions 绑定到 nats-py。"""

        if self._nc is None:
            return
        for subject, callback in self._pending_subscriptions:

            async def _wrapped(msg: Any, *, _callback: MessageCallback = callback) -> None:
                """把 nats-py msg 转换成统一 bytes callback。"""

                response = await _callback(str(msg.subject), bytes(msg.data), getattr(msg, "reply", None) or None)
                if getattr(msg, "reply", None) and response is not None:
                    await self._nc.publish(msg.reply, response)

            self._subscriptions.append(await self._nc.subscribe(subject, cb=_wrapped))
            logging.info("[NatsMessageClient:v3] subscribed subject=%s", subject)

    async def _close_async(self) -> None:
        """异步关闭 NATS 连接。"""

        if self._nc is None:
            return
        try:
            await self._nc.flush(timeout=0.2)
        except Exception:
            pass
        try:
            await self._nc.close()
        except Exception:
            pass
        self._nc = None
        self._subscriptions.clear()


class PoseResultPublisher:
    """同步 runtime 可调用的 PoseResult 发布器。

    本类负责 Protobuf 序列化、subject 发布和后台 Future 限流；
    它不负责把 PoseObservation 映射成 Protobuf，也不理解 Unity world anchor。
    """

    def __init__(self, client: NatsMessageClient, *, subject: str, max_pending_futures: int = 32) -> None:
        """保存底层 NATS client 与发布参数。"""

        self.client = client
        """底层 bytes NATS client。"""

        self.subject = str(subject)
        """PoseResult 发布 subject。"""

        self.max_pending_futures = max(1, int(max_pending_futures))
        """后台 publish Future 最大积压数。"""

        self._pending: list[Future[None]] = []
        """尚未完成的后台 publish Future。"""

        self._submitted = 0
        """成功提交到后台 event loop 的消息数量。"""

        self._published = 0
        """后台 publish 协程成功返回的消息数量。"""

        self._failed = 0
        """本发布器发现的失败或丢弃数量。"""

    @property
    def enabled(self) -> bool:
        """PoseResult 发布链路是否启用。"""

        return self.client.enabled

    @property
    def submitted_count(self) -> int:
        """已提交到后台 event loop 的消息数量。"""

        return self._submitted

    @property
    def published_count(self) -> int:
        """后台 NATS publish 已成功完成的消息数量。"""

        self._drain_completed_futures()
        return self._published

    @property
    def failed_count(self) -> int:
        """发布失败、连接失败或限流丢弃数量。"""

        self._drain_completed_futures()
        return self._failed + self.client.connect_failed_count

    @property
    def pending_count(self) -> int:
        """尚未完成的后台 publish Future 数量。"""

        self._drain_completed_futures()
        return len(self._pending)

    def start(self) -> None:
        """启动底层 NATS client。"""

        self.client.start()

    def close(self) -> None:
        """关闭底层 NATS client。"""

        self.client.close()

    def publish_pose_result(self, msg: ProtobufMessage) -> bool:
        """发布一条 Protobuf PoseResult。

        返回值只表示“是否成功提交到后台 event loop”，不保证订阅端已经收到。
        PoseResult 是实时 latest-only 小消息；NATS 未连接或队列积压时直接丢弃当前包。
        """

        if not self.enabled:
            return False
        loop = self.client.loop
        if loop is None or not loop.is_running() or not self.client.is_connected:
            self._failed += 1
            return False

        self._drain_completed_futures()
        if len(self._pending) >= self.max_pending_futures:
            self._failed += 1
            return False

        payload = msg.SerializeToString()
        future: Future[None] = asyncio.run_coroutine_threadsafe(self._publish_bytes(payload), loop)
        self._pending.append(future)
        self._submitted += 1
        return True

    async def _publish_bytes(self, payload: bytes) -> None:
        """实际执行 NATS publish 的协程。"""

        try:
            await self.client.publish(self.subject, payload)
            self._published += 1
        except Exception as exc:
            self._failed += 1
            logging.debug("[PoseResultPublisher:v3] publish PoseResult 失败 subject=%s：%s", self.subject, exc)

    def _drain_completed_futures(self) -> None:
        """清理已完成 Future，并观察异常，避免后台异常泄漏。"""

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
                logging.debug("[PoseResultPublisher:v3] 后台 publish future 异常：%s", exc)
        self._pending = remaining


class NatsClient(NatsMessageClient):
    """v3 NATS bytes client 的短别名。

    保留该别名是为了让业务代码可以使用计划中的简洁命名；当前实现仍复用
    `NatsMessageClient` 的完整能力。
    """


__all__ = ["MessageCallback", "NatsClient", "NatsMessageClient", "NatsMessageSettings", "PoseResultPublisher"]
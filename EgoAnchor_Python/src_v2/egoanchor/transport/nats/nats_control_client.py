"""NATS 控制面客户端。"""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
from collections.abc import Awaitable, Callable
from typing import Any

from .nats_control_settings import NatsControlSettings

BytesRequestHandler = Callable[[bytes], bytes | Awaitable[bytes]]


class NatsControlClient:
    """Python v2 NATS 控制面客户端。

    与 Unity `NatsControlClient.cs` 命名对齐：本类只负责 NATS 连接生命周期、
    后台 asyncio event loop 和底层 publish 操作，不知道 PoseObservation、Unity Transform
    或 FoundationPose/GPU 状态。具体消息发布器应依赖本类，而不是直接散落 `nats.connect`。
    """

    def __init__(self, settings: NatsControlSettings) -> None:
        self.settings = settings
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._closed = False
        self._nc: Any | None = None
        self._connect_failed = 0
        self._subscriptions: dict[str, BytesRequestHandler] = {}

    @property
    def enabled(self) -> bool:
        """控制面是否启用。"""

        return self.settings.enabled

    @property
    def url(self) -> str:
        """NATS server URL。"""

        return self.settings.url

    @property
    def is_connected(self) -> bool:
        """是否已有可用 NATS 连接。"""

        return self._nc is not None

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        """后台 asyncio event loop。"""

        return self._loop

    @property
    def connect_failed_count(self) -> int:
        """连接失败计数。"""

        return self._connect_failed

    def start(self) -> None:
        """启动后台 NATS event loop 并尝试连接。"""

        if not self.enabled:
            logging.info("[NatsControlClient] control_plane.enabled=false，控制面保持关闭。")
            return
        if self._thread is not None:
            return
        self._closed = False
        self._ready.clear()
        self._thread = threading.Thread(target=self._run_loop_thread, name="EgoAnchorNatsControlClient", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=max(self.settings.connect_timeout_s + 0.5, 0.5)):
            logging.warning("[NatsControlClient] 等待 NATS 连接初始化超时，后续发布会先被丢弃直到连接可用。")

    def close(self) -> None:
        """关闭后台连接。"""

        self._closed = True
        loop = self._loop
        if loop is None:
            return
        if loop.is_running():
            try:
                future = asyncio.run_coroutine_threadsafe(self._close_async(), loop)
                future.result(timeout=1.0)
            except Exception as exc:  # pragma: no cover - 关闭路径只记录，不影响退出
                logging.debug("[NatsControlClient] 关闭 NATS 时出现非致命异常：%s", exc)
            loop.call_soon_threadsafe(loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._thread = None
        self._loop = None

    async def publish(self, subject: str, payload: bytes) -> None:
        """发布一段 Protobuf bytes。"""

        if self._nc is None:
            raise RuntimeError("NATS client is not connected")
        await self._nc.publish(subject, payload)

    async def request(self, subject: str, payload: bytes, *, timeout_s: float | None = None) -> bytes:
        """发送 request/reply 请求并返回 reply bytes。"""

        if self._nc is None:
            raise RuntimeError("NATS client is not connected")
        reply = await self._nc.request(subject, payload, timeout=timeout_s or self.settings.request_timeout_s)
        return bytes(reply.data or b"")

    def subscribe_request_handler(self, subject: str, handler: BytesRequestHandler) -> None:
        """注册 bytes request/reply handler。

        handler 只应 parse/validate/enqueue/ack，不直接触碰 TrackingRuntime 的 GPU/pipeline 状态。
        """

        if not subject or not callable(handler):
            return
        self._subscriptions[subject] = handler
        loop = self._loop
        if self.enabled and loop is not None and loop.is_running() and self._nc is not None:
            asyncio.run_coroutine_threadsafe(self._subscribe_one(subject, handler), loop)

    def _run_loop_thread(self) -> None:
        """后台线程入口。"""

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.create_task(self._connect_async())
        try:
            self._loop.run_forever()
        finally:
            self._loop.run_until_complete(self._close_async())
            self._loop.close()

    async def _connect_async(self) -> None:
        """连接 NATS。导入 nats-py 放在运行期，避免 disabled 时要求依赖。"""

        try:
            import nats  # type: ignore

            self._nc = await nats.connect(
                servers=[self.settings.url],
                name=self.settings.client_name,
                connect_timeout=self.settings.connect_timeout_s,
                allow_reconnect=True,
                max_reconnect_attempts=-1,
            )
            for subject, handler in self._subscriptions.items():
                await self._subscribe_one(subject, handler)
            logging.info("[NatsControlClient] connected url=%s", self.settings.url)
        except Exception as exc:
            self._nc = None
            self._connect_failed += 1
            logging.error("[NatsControlClient] 连接 NATS 失败 url=%s：%s", self.settings.url, exc)
        finally:
            self._ready.set()

    async def _subscribe_one(self, subject: str, handler: BytesRequestHandler) -> None:
        """订阅一个 request/reply subject。"""

        if self._nc is None:
            return

        async def _callback(msg: Any) -> None:
            try:
                result = handler(bytes(msg.data or b""))
                if inspect.isawaitable(result):
                    result = await result
                await msg.respond(bytes(result or b""))
            except Exception as exc:
                logging.warning("[NatsControlClient] request handler failed subject=%s: %s", subject, exc)
                try:
                    await msg.respond(b"")
                except Exception:
                    pass

        await self._nc.subscribe(subject, cb=_callback)
        logging.info("[NatsControlClient] subscribed request subject=%s", subject)

    async def _close_async(self) -> None:
        """异步关闭 NATS 连接。"""

        if self._nc is not None:
            try:
                await self._nc.flush(timeout=0.2)
            except Exception:
                pass
            try:
                await self._nc.close()
            except Exception:
                pass
            self._nc = None


__all__ = ["BytesRequestHandler", "NatsControlClient"]
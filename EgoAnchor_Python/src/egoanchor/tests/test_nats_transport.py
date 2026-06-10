"""NATS transport 层契约测试。"""

from __future__ import annotations

import asyncio
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from egoanchor.transport import NatsMessageClient, NatsMessageSettings


class _FakeNatsConnection:
    """测试用 NATS 连接替身，只记录订阅。"""

    def __init__(self) -> None:
        """初始化订阅记录。"""

        self.subscriptions: list[tuple[str, object]] = []
        self.published: list[tuple[str, bytes]] = []
        self.publish_fails = False

    async def subscribe(self, subject: str, cb: object) -> object:
        """模拟 nats-py subscribe。"""

        self.subscriptions.append((subject, cb))
        return object()

    async def publish(self, subject: str, payload: bytes) -> None:
        """模拟 nats-py publish。"""

        if self.publish_fails:
            raise RuntimeError("publish down")
        self.published.append((subject, payload))


class _FakeNatsModule:
    """测试用 nats 模块替身，可配置前几次连接失败。"""

    def __init__(self, fail_count: int) -> None:
        """保存失败次数并初始化连接记录。"""

        self.fail_count = int(fail_count)
        self.attempts = 0
        self.connection = _FakeNatsConnection()

    async def connect(self, **kwargs: object) -> _FakeNatsConnection:
        """前 fail_count 次抛异常，之后返回连接替身。"""

        self.attempts += 1
        if self.attempts <= self.fail_count:
            raise RuntimeError("nats down")
        return self.connection


class _BlockingNatsModule:
    """测试用 nats 模块替身，模拟连接调用长时间挂起。"""

    async def connect(self, **kwargs: object) -> _FakeNatsConnection:
        """一直等待，直到客户端 close 取消连接任务。"""

        await asyncio.sleep(10.0)
        return _FakeNatsConnection()


class NatsMessageClientTest(unittest.TestCase):
    """验证 NatsMessageClient 不触网的同步契约。"""

    async def _noop_callback(self, subject: str, payload: bytes, reply: str | None) -> bytes | None:
        """测试用 bytes callback，不执行任何业务逻辑。"""

        return None

    def test_add_subscription_before_start_buffers_callback(self) -> None:
        """start 前登记的订阅应进入待绑定列表，等待连接后统一 attach。"""

        client = NatsMessageClient(NatsMessageSettings(enabled=False))
        callback = self._noop_callback

        client.add_subscription("egoanchor.test", callback)

        self.assertEqual(len(client._pending_subscriptions), 1)
        subject, stored_callback = client._pending_subscriptions[0]
        self.assertEqual(subject, "egoanchor.test")
        self.assertIs(stored_callback, callback)

    def test_add_subscription_after_start_fails_fast(self) -> None:
        """start 后再登记订阅不会自动 attach，应立即报错暴露调用顺序问题。"""

        client = NatsMessageClient(NatsMessageSettings(enabled=False))
        client._started = True

        with self.assertRaisesRegex(RuntimeError, "start 前调用"):
            client.add_subscription("egoanchor.test", self._noop_callback)

        self.assertEqual(client._pending_subscriptions, [])

    def test_initial_connect_failure_keeps_retrying_until_connected(self) -> None:
        """NATS server 晚启动时，首次失败后后台应继续重试并绑定订阅。"""

        async def run_case() -> None:
            """在当前 event loop 内直接运行连接协程，避免启动真实后台线程。"""

            fake_nats = _FakeNatsModule(fail_count=2)
            sleep_ready_states: list[bool] = []
            client = NatsMessageClient(
                NatsMessageSettings(
                    enabled=True,
                    connect_timeout_s=0.01,
                    initial_retry_interval_s=0.01,
                )
            )
            client.add_subscription("egoanchor.test", self._noop_callback)
            real_sleep = asyncio.sleep

            async def fake_sleep(delay_s: float) -> None:
                """记录首次失败后 ready 是否已释放，并跳过真实等待。"""

                sleep_ready_states.append(client._ready.is_set())
                await real_sleep(0)

            with patch.dict(sys.modules, {"nats": fake_nats}), patch("egoanchor.transport.nats_client.asyncio.sleep", fake_sleep):
                await client._connect_until_ready_async()

            self.assertEqual(fake_nats.attempts, 3)
            self.assertEqual(client.connect_failed_count, 2)
            self.assertTrue(client._ready.is_set())
            self.assertTrue(all(sleep_ready_states))
            self.assertIs(client._nc, fake_nats.connection)
            self.assertEqual(len(fake_nats.connection.subscriptions), 1)
            self.assertEqual(fake_nats.connection.subscriptions[0][0], "egoanchor.test")

        asyncio.run(run_case())

    def test_start_then_immediate_close_stops_background_thread(self) -> None:
        """start 后立刻 close 也应收掉后台 loop，不留下 NATS 线程空跑。"""

        client = NatsMessageClient(
            NatsMessageSettings(
                enabled=True,
                connect_timeout_s=0.01,
                initial_retry_interval_s=0.01,
            )
        )

        with patch.dict(sys.modules, {"nats": _BlockingNatsModule()}):
            client.start()
            client.close()

        self.assertFalse(client._started)
        self.assertIsNone(client._thread)
        self.assertIsNone(client._loop)

    def test_subscription_callback_exception_isolated(self) -> None:
        """request callback 抛异常时不应逃出 nats-py 后台回调。"""

        async def run_case() -> None:
            """绑定 fake 订阅并直接触发 wrapper callback。"""

            async def failing_callback(subject: str, payload: bytes, reply: str | None) -> bytes | None:
                """模拟业务 callback 意外失败。"""

                raise RuntimeError("handler failed")

            fake_nats = _FakeNatsModule(fail_count=0)
            client = NatsMessageClient(NatsMessageSettings(enabled=True))
            client.add_subscription("egoanchor.test", failing_callback)

            with patch.dict(sys.modules, {"nats": fake_nats}):
                self.assertTrue(await client._connect_once_async())

            callback = fake_nats.connection.subscriptions[0][1]
            await callback(SimpleNamespace(subject="egoanchor.test", data=b"payload", reply="_INBOX.1"))  # type: ignore[misc]

            self.assertEqual(client.subscription_callback_failed_count, 1)
            self.assertEqual(fake_nats.connection.published, [])

        asyncio.run(run_case())

    def test_subscription_reply_publish_exception_isolated(self) -> None:
        """request reply 发布失败时应记录计数，不让后台 callback 抛出异常。"""

        async def run_case() -> None:
            """绑定 fake 订阅并模拟 reply publish 失败。"""

            async def reply_callback(subject: str, payload: bytes, reply: str | None) -> bytes | None:
                """模拟业务 callback 正常返回 reply bytes。"""

                return b"ack"

            fake_nats = _FakeNatsModule(fail_count=0)
            client = NatsMessageClient(NatsMessageSettings(enabled=True))
            client.add_subscription("egoanchor.test", reply_callback)

            with patch.dict(sys.modules, {"nats": fake_nats}):
                self.assertTrue(await client._connect_once_async())

            fake_nats.connection.publish_fails = True
            callback = fake_nats.connection.subscriptions[0][1]
            await callback(SimpleNamespace(subject="egoanchor.test", data=b"payload", reply="_INBOX.2"))  # type: ignore[misc]

            self.assertEqual(client.subscription_reply_failed_count, 1)

        asyncio.run(run_case())


if __name__ == "__main__":
    unittest.main()

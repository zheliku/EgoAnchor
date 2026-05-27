"""transport 生命周期基类测试。"""

from __future__ import annotations

import unittest

from egoanchor.transport import BaseTransportClient


class _LifecycleProbe(BaseTransportClient):
    """单测用最小传输客户端。"""

    def __init__(self) -> None:
        """初始化测试计数。"""

        super().__init__("LifecycleProbe")
        self.start_calls = 0
        """真实 start 逻辑被执行的次数。"""

        self.close_calls = 0
        """真实 close 逻辑被执行的次数。"""

    def start(self) -> None:
        """模拟子类 start 入口。"""

        if not self.begin_start():
            return
        self.start_calls += 1

    def close(self) -> None:
        """模拟子类 close 入口。"""

        if not self.begin_close():
            return
        self.close_calls += 1


class TransportLifecycleTest(unittest.TestCase):
    """验证 start/close 状态机不会重复执行真实传输逻辑。"""

    def test_start_is_idempotent_until_close(self) -> None:
        """连续 start 只应执行一次子类真实启动逻辑。"""

        client = _LifecycleProbe()

        client.start()
        client.start()

        self.assertTrue(client.is_started)
        self.assertEqual(client.start_calls, 1)

    def test_close_is_idempotent_and_allows_restart(self) -> None:
        """关闭未启动客户端不应执行真实释放，关闭后允许重新启动。"""

        client = _LifecycleProbe()

        client.close()
        client.start()
        client.close()
        client.close()
        client.start()

        self.assertTrue(client.is_started)
        self.assertEqual(client.start_calls, 2)
        self.assertEqual(client.close_calls, 1)


if __name__ == "__main__":
    unittest.main()

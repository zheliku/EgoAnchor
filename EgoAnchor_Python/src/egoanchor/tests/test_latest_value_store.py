"""latest-only 值缓存工具测试。"""

from __future__ import annotations

import unittest

from egoanchor.utils import LatestValueStore


class LatestValueStoreTest(unittest.TestCase):
    """验证 latest-only 缓存的替换、取走和统计语义。"""

    def test_put_replaces_latest_and_counts_drop(self) -> None:
        """覆盖旧值时可记录一次 latest-only 丢弃。"""

        store: LatestValueStore[str] = LatestValueStore()

        store.put("first")
        store.put("second", count_drop=True)

        self.assertEqual(store.peek(), "second")
        self.assertEqual(store.seen_count, 2)
        self.assertEqual(store.drop_count, 1)
        self.assertIsNotNone(store.updated_mono_ms)

    def test_take_clears_value_without_resetting_counts(self) -> None:
        """取走最新值后应清空缓存，但保留累计统计。"""

        store: LatestValueStore[int] = LatestValueStore()
        store.put(7)

        self.assertEqual(store.take(), 7)
        self.assertIsNone(store.peek())
        self.assertEqual(store.seen_count, 1)


if __name__ == "__main__":
    unittest.main()

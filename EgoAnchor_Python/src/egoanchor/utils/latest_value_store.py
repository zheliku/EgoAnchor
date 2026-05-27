"""通用 latest-only 值缓存。"""

from __future__ import annotations

import time
from typing import Generic, TypeVar

T = TypeVar("T")


class LatestValueStore(Generic[T]):
    """保存一个最新值，并记录替换/消费统计。"""

    def __init__(self) -> None:
        """初始化空缓存和累计计数。"""

        self._value: T | None = None
        self.updated_mono_ms: float | None = None
        self.seen_count = 0
        self.drop_count = 0

    def put(self, value: T, *, count_drop: bool = False) -> None:
        """写入最新值；需要时把覆盖旧值计为一次丢弃。"""

        if count_drop and self._value is not None:
            self.drop_count += 1
        self._value = value
        self.updated_mono_ms = time.perf_counter() * 1000.0
        self.seen_count += 1

    def peek(self) -> T | None:
        """读取当前最新值但不清空缓存。"""

        return self._value

    def take(self) -> T | None:
        """取走当前最新值并清空缓存。"""

        value = self._value
        self._value = None
        self.updated_mono_ms = None
        return value

    def clear(self) -> None:
        """清空当前值；保留累计 seen/drop 统计。"""

        self._value = None
        self.updated_mono_ms = None

    def age_ms(self, now_mono_ms: float | None = None) -> float | None:
        """返回最新值年龄，尚未写入时返回 None。"""

        if self.updated_mono_ms is None:
            return None
        now = time.perf_counter() * 1000.0 if now_mono_ms is None else float(now_mono_ms)
        return now - self.updated_mono_ms


__all__ = ["LatestValueStore"]

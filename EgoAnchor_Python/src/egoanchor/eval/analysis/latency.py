"""使用显式单调时钟域计算 candidate arrival 和 Python processing。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class ClockDomain(str, Enum):
    """离线分析允许参与时延计算的单调时钟域。"""

    UNITY = "unity_monotonic"
    """Unity 进程的单调时钟。"""

    PYTHON = "python_monotonic"
    """Python 进程的单调时钟。"""


@dataclass(frozen=True, slots=True)
class MonotonicTimestamp:
    """携带进程时钟域的单调时间戳。"""

    value_ms: float
    """单调时间戳数值，单位毫秒。"""

    clock: ClockDomain
    """时间戳所属的进程单调时钟。"""

    def __post_init__(self) -> None:
        """拒绝非有限时间和非法时钟域。"""

        if not math.isfinite(self.value_ms):
            raise ValueError("单调时间戳必须是有限值")
        if not isinstance(self.clock, ClockDomain):
            raise ValueError("单调时间戳必须声明合法时钟域")


def elapsed_ms(start: MonotonicTimestamp, end: MonotonicTimestamp) -> float:
    """计算同一单调时钟域内的非负耗时。

    参数：
        start: 区间开始时间戳。
        end: 区间结束时间戳。
    """

    if start.clock is not end.clock:
        raise ValueError(f"禁止跨单调时钟相减：{start.clock.value} -> {end.clock.value}")
    duration = end.value_ms - start.value_ms
    if duration < 0.0:
        raise ValueError("单调时钟结束时间早于开始时间")
    return duration


def _require_clock_domain(
    start: MonotonicTimestamp,
    end: MonotonicTimestamp,
    expected: ClockDomain,
    metric_name: str,
) -> None:
    """校验一组时间戳来自同一预期单调时钟域。

    参数：
        start: 区间开始时间戳。
        end: 区间结束时间戳。
        expected: 指标契约要求的时钟域。
        metric_name: 报错时使用的指标名称。
    """

    if start.clock is not end.clock:
        raise ValueError(f"禁止跨单调时钟计算 {metric_name}")
    if start.clock is not expected:
        raise ValueError(f"{metric_name} 必须使用 {expected.value}")


def candidate_arrival_ms(
    source_capture: MonotonicTimestamp,
    unity_pose_handle: MonotonicTimestamp,
) -> float:
    """计算 Unity 同域的 candidate arrival 时延。

    参数：
        source_capture: 图像时刻代理 ``source_capture_mono_ms``。
        unity_pose_handle: Unity 处理候选的 ``unity_pose_handle_mono_ms``。
    """

    _require_clock_domain(source_capture, unity_pose_handle, ClockDomain.UNITY, "candidate arrival")
    return elapsed_ms(source_capture, unity_pose_handle)


def python_processing_ms(
    server_receive: MonotonicTimestamp,
    server_publish: MonotonicTimestamp,
) -> float:
    """计算 Python 同域的 server processing 时延。

    参数：
        server_receive: Python 接收候选的 ``server_receive_mono_ms``。
        server_publish: Python 发布候选的 ``server_publish_mono_ms``。
    """

    _require_clock_domain(server_receive, server_publish, ClockDomain.PYTHON, "Python processing")
    return elapsed_ms(server_receive, server_publish)


__all__ = [
    "ClockDomain",
    "MonotonicTimestamp",
    "candidate_arrival_ms",
    "elapsed_ms",
    "python_processing_ms",
]

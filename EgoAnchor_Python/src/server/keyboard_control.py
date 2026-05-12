"""Keyboard control for local OpenCV debug mode."""

from __future__ import annotations

import logging
from typing import Protocol


class KeyboardControllablePipeline(Protocol):
    """本地 OpenCV 调试热键需要的最小 Pipeline 接口。

    这里刻意只声明热键会用到的成员，避免把 quest/realsense 等具体
    Pipeline 类型耦合进通用键盘处理模块。后续只要对象提供这些能力，
    就可以复用同一套热键逻辑。
    """

    stage: int

    def reset_tracking_state(self) -> None: ...

    def set_stage(self, stage: int) -> None: ...


def handle_debug_key(
    key: int,
    pipeline: KeyboardControllablePipeline,
    enable_keyboard_control: bool,
) -> str | None:
    """处理本地调试热键。

    返回值：
    - "quit"：退出服务。
    - "reset"：已经重置跟踪状态，调用方需要更新时间和统计。
    - None：无动作。
    """
    if key in (27, ord("q")):
        return "quit"

    if not enable_keyboard_control:
        return None

    if key == ord("r"):
        pipeline.reset_tracking_state()
        logging.info("[object_tracking_server] manual reset tracking")
        return "reset"

    if key in (ord("1"), ord("2"), ord("3"), ord("4")):
        pipeline.set_stage(int(chr(key)))
        logging.info("[object_tracking_server] switch stage -> %d", pipeline.stage)
        return "reset"

    return None

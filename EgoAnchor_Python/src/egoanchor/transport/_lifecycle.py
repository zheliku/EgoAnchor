"""传输客户端通用生命周期辅助。"""

from __future__ import annotations

import logging


class BaseTransportClient:
    """传输层 start/close 状态机基类。

    本类只处理“是否已经启动”的通用状态和轻量日志，不理解 ZMQ socket、
    NATS event loop 或任何 EgoAnchor 业务语义。子类仍然完整拥有自己的连接、
    订阅、重连和关闭细节。
    """

    def __init__(self, log_name: str) -> None:
        """保存日志名称并初始化未启动状态。"""

        self._lifecycle_log_name = str(log_name)
        """日志中使用的短名称。"""

        self._lifecycle_started = False
        """当前客户端是否已经完成 start 入口。"""

    @property
    def is_started(self) -> bool:
        """客户端是否处于已启动状态。"""

        return self._lifecycle_started

    def begin_start(self) -> bool:
        """尝试进入启动流程。

        返回 False 表示子类已启动，调用方应直接返回；返回 True 表示本次调用
        获得启动权，后续可以执行真实 socket/event-loop 初始化。
        """

        if self._lifecycle_started:
            return False
        self._lifecycle_started = True
        logging.info("[%s] starting", self._lifecycle_log_name)
        return True

    def cancel_start(self) -> None:
        """启动失败时回滚生命周期状态。"""

        self._lifecycle_started = False

    def begin_close(self) -> bool:
        """尝试进入关闭流程。

        返回 False 表示当前未启动或已经关闭；返回 True 表示子类应执行真实释放。
        """

        if not self._lifecycle_started:
            return False
        self._lifecycle_started = False
        logging.info("[%s] closing", self._lifecycle_log_name)
        return True


__all__ = ["BaseTransportClient"]

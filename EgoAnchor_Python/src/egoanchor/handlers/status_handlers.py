"""status handlers 预留模块。

当前 Python 只发布 status/heartbeat/pose，不从 Unity 接收 status 类 pub/sub 消息。
保留本模块是为了让 handlers 层结构和计划一致，后续新增低频配置/调试消息时统一注册。
"""

from __future__ import annotations

from egoanchor.routing import HandlerRegistry


def register_status_handlers(registry: HandlerRegistry) -> None:
    """当前无 Python 接收侧 status handler。"""

    _ = registry


__all__ = ["register_status_handlers"]

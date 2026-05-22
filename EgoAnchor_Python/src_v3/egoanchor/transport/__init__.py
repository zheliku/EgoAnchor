"""v3 传输层包级入口。"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from .zmq_topic_subscriber import LatestTopicPayloadStore, ZmqTopicSubscriber, ZmqTopicSubscriberStats

_LAZY_EXPORTS = {
    "NatsClient": "egoanchor.transport.nats_client",
    "NatsMessageClient": "egoanchor.transport.nats_client",
    "NatsMessageSettings": "egoanchor.transport.nats_client",
    "PoseResultPublisher": "egoanchor.transport.nats_client",
}


def __getattr__(name: str) -> Any:
    """惰性导出 NATS 组件，避免未启用消息面时导入 nats-py 相关模块。"""

    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value


__all__ = [
    "LatestTopicPayloadStore",
    "NatsClient",
    "NatsMessageClient",
    "NatsMessageSettings",
    "PoseResultPublisher",
    "ZmqTopicSubscriber",
    "ZmqTopicSubscriberStats",
]

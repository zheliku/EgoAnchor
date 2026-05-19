from __future__ import annotations

"""
v2 command idempotency store。

命令层 request/reply 可能因为网络 timeout 被 Unity 重试。客户端重试同一个命令
时必须复用 `header.request_id`；server 看到重复 request_id 时返回之前的 ack，
但不重复入队、不重复执行。
"""

import time
from dataclasses import dataclass

from egoanchor.protocol.v1.common_pb2 import CommandAck


@dataclass
class _Entry:
    ack: CommandAck
    expires_mono_ms: float


class CommandDedupStore:
    """基于 request_id 的 TTL 去重缓存。"""

    def __init__(self, ttl_ms: float = 60_000.0) -> None:
        self._ttl_ms = ttl_ms
        self._entries: dict[str, _Entry] = {}

    def get(self, request_id: str) -> CommandAck | None:
        """查询重复请求；命中时返回 ack 副本，并把 duplicate 标记为 True。"""
        self._prune()
        entry = self._entries.get(request_id)
        if entry is None:
            return None
        ack = CommandAck()
        ack.CopyFrom(entry.ack)
        ack.duplicate = True
        return ack

    def remember(self, request_id: str, ack: CommandAck) -> None:
        """记录某个 request_id 的首次处理结果。"""
        if not request_id:
            return
        stored = CommandAck()
        stored.CopyFrom(ack)
        self._entries[request_id] = _Entry(stored, time.monotonic() * 1000.0 + self._ttl_ms)

    def _prune(self) -> None:
        """清理过期 request_id，避免缓存无限增长。"""
        now = time.monotonic() * 1000.0
        expired = [key for key, entry in self._entries.items() if entry.expires_mono_ms <= now]
        for key in expired:
            del self._entries[key]

    def __len__(self) -> int:
        """返回当前有效去重记录数量。"""
        self._prune()
        return len(self._entries)

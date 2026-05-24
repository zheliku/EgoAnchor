"""command request_id 幂等缓存。"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from egoanchor.protocol import CommandAck


@dataclass(slots=True)
class _Entry:
    ack: CommandAck
    expires_mono_ms: float


class CommandDedupStore:
    """基于 header.request_id 的 TTL 去重缓存。"""

    def __init__(self, ttl_ms: float = 60_000.0) -> None:
        self._ttl_ms = float(ttl_ms)
        self._entries: dict[str, _Entry] = {}
        self._lock = threading.Lock()

    def get(self, request_id: str) -> CommandAck | None:
        """命中重复 request_id 时返回 ack 副本，并标记 duplicate=true。"""

        with self._lock:
            self._prune_locked()
            entry = self._entries.get(request_id)
            if entry is None:
                return None
            ack = CommandAck()
            ack.CopyFrom(entry.ack)
            ack.duplicate = True
            return ack

    def remember(self, request_id: str, ack: CommandAck) -> None:
        """记录某个 request_id 的首次 ack。"""

        if not request_id:
            return
        with self._lock:
            stored = CommandAck()
            stored.CopyFrom(ack)
            self._entries[request_id] = _Entry(stored, time.monotonic() * 1000.0 + self._ttl_ms)

    def _prune_locked(self) -> None:
        now = time.monotonic() * 1000.0
        expired = [key for key, entry in self._entries.items() if entry.expires_mono_ms <= now]
        for key in expired:
            del self._entries[key]

    def __len__(self) -> int:
        with self._lock:
            self._prune_locked()
            return len(self._entries)


__all__ = ["CommandDedupStore"]

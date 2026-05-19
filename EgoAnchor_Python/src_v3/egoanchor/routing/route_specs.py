"""v3 route spec helpers。"""

from __future__ import annotations

from collections.abc import Iterable

from egoanchor.protocol import SubjectRegistry, SubjectSpec


def iter_nats_request_specs(subjects: SubjectRegistry) -> Iterable[SubjectSpec]:
    """遍历所有 Unity->Python NATS request/reply subject。"""

    for spec in subjects.by_transport("nats"):
        if spec.direction == "unity_to_python" and spec.mode == "request_reply":
            yield spec


__all__ = ["iter_nats_request_specs"]
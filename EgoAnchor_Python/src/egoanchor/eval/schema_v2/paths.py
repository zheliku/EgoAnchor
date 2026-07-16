"""schema-v2 固定目录与文件路径。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EvalV2Paths:
    """一次评估 session 的全部固定路径。

    各端通过固定文件名协作，禁止把 session id 拼入文件名或通过 glob 猜测输入。
    """

    session_dir: Path
    """session 根目录。"""

    manifest: Path
    """跨端汇总清单。"""

    python_candidates: Path
    """Python candidate 长表。"""

    python_events: Path
    """Python runtime 事件分片。"""

    unity_events: Path
    """Unity runtime 与人工事件分片。"""

    unity_reference: Path
    """Unity 平台参考轨迹。"""

    unity_admission: Path
    """candidate 与 variant 的接纳结果长表。"""

    unity_render: Path
    """render tick 与 variant 的输出长表。"""

    events: Path
    """跨端 session/runtime/人工标记事件。"""

    audit_samples: Path
    """需要人工复核的审计样本目录。"""

    @classmethod
    def for_session(cls, session_dir: str | Path) -> "EvalV2Paths":
        """根据 session 根目录构造全部固定路径。"""

        root = Path(session_dir).expanduser()
        return cls(
            session_dir=root,
            manifest=root / "manifest.json",
            python_candidates=root / "python_candidates.jsonl",
            python_events=root / "python_events.jsonl",
            unity_events=root / "unity_events.jsonl",
            unity_reference=root / "unity_reference.jsonl",
            unity_admission=root / "unity_admission.jsonl",
            unity_render=root / "unity_render.jsonl",
            events=root / "events.jsonl",
            audit_samples=root / "audit_samples",
        )

    def jsonl_paths(self) -> tuple[Path, ...]:
        """按契约顺序返回全部 JSONL 文件路径。"""

        return (
            self.python_candidates,
            self.unity_reference,
            self.unity_admission,
            self.unity_render,
            self.events,
        )


__all__ = ["EvalV2Paths"]

"""集中定义实验三来源门禁状态及其产物隔离规则。"""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Final, Literal, Mapping, TypeAlias, cast

from .artifacts import ArtifactSpec


SourceGateStatus: TypeAlias = Literal[
    "approved",
    "known_synthetic",
    "unapproved_formal",
    "nonformal",
]
"""来源门禁的四种稳定状态。"""

REHEARSAL_DIRECTORY: Final = "rehearsal_not_paper_evidence"
"""未通过门禁的产物统一写入的隔离目录。"""

_GATE_SUFFIXES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "known_synthetic": "__known_synthetic_rehearsal_not_paper_evidence",
        "unapproved_formal": "__unapproved_formal_rehearsal_not_paper_evidence",
        "nonformal": "__nonformal_rehearsal_not_paper_evidence",
    }
)
"""三种演练状态对应的稳定文件名后缀。"""

_SOURCE_GATE_STATUSES: Final = frozenset({"approved", *_GATE_SUFFIXES})
"""分析管线接受的完整门禁状态集合。"""


def require_source_gate_status(value: object) -> SourceGateStatus:
    """返回合法门禁状态，拒绝缺失值和未知状态。"""

    if not isinstance(value, str) or value not in _SOURCE_GATE_STATUSES:
        raise ValueError(f"未知实验三来源门禁状态：{value!r}")
    return cast(SourceGateStatus, value)


def is_paper_eligible(status: SourceGateStatus) -> bool:
    """判断门禁状态是否允许生成和复制论文正式资源。"""

    return require_source_gate_status(status) == "approved"


def gate_suffix(status: SourceGateStatus) -> str:
    """返回演练状态的文件名后缀；正式状态不附加后缀。"""

    checked = require_source_gate_status(status)
    if checked == "approved":
        return ""
    return _GATE_SUFFIXES[checked]


def artifact_path(
    root: Path,
    artifact: ArtifactSpec,
    status: SourceGateStatus,
) -> Path:
    """按门禁状态返回正式路径或带状态后缀的演练路径。"""

    checked = require_source_gate_status(status)
    category_root = root.expanduser().resolve() / artifact.category
    if is_paper_eligible(checked):
        return category_root / artifact.canonical_name
    name = Path(artifact.canonical_name)
    isolated_name = f"{name.stem}{gate_suffix(checked)}{name.suffix}"
    return category_root / REHEARSAL_DIRECTORY / isolated_name


__all__ = [
    "REHEARSAL_DIRECTORY",
    "SourceGateStatus",
    "artifact_path",
    "gate_suffix",
    "is_paper_eligible",
    "require_source_gate_status",
]

"""离线分析各阶段契约版本和变更记录。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ContractVersion:
    """描述一个可独立演进的离线分析契约版本。"""

    name: str
    """契约名称。"""

    version: int
    """单调递增的整数版本。"""

    description: str
    """面向审计者的中文说明。"""

    def to_dict(self) -> dict[str, Any]:
        """返回可序列化的版本记录。"""

        return asdict(self)


@dataclass(frozen=True, slots=True)
class ContractChange:
    """记录一次契约变更及其兼容性边界。"""

    version: str
    """变更所属的契约版本标识。"""

    summary: str
    """变更摘要。"""

    breaking: bool
    """是否破坏已有阶段输入或输出。"""

    def to_dict(self) -> dict[str, Any]:
        """返回可序列化的变更记录。"""

        return asdict(self)


CONTRACT_VERSIONS = (
    ContractVersion("workbook", 2, "Stage 1 无损 XLSX 工作簿契约"),
    ContractVersion("csv", 1, "Stage 2 指标与论文数据 CSV 契约"),
    ContractVersion("metrics", 1, "实验一/二指标定义契约"),
    ContractVersion("analysis_params", 1, "冻结分析参数契约"),
)
"""当前冻结的契约版本目录。"""

CONTRACT_CHANGELOG = (
    ContractChange("workbook-v1", "建立完整事实 sheet、来源追踪和 QC sheet。", True),
    ContractChange(
        "workbook-v2",
        "补齐科学分析字段、标量 pose、外键、未知字段和超长值分片。",
        True,
    ),
    ContractChange("csv-v1", "固定 event/trial/session、plot 和 paper 长表。", True),
    ContractChange("metrics-v1", "固定五场景指标、单位、方向和 TeX 命名。", True),
)
"""当前仓库已确认的契约变更记录。"""


def versions_as_dicts() -> list[dict[str, Any]]:
    """返回版本目录的普通字典列表。"""

    return [item.to_dict() for item in CONTRACT_VERSIONS]


def changelog_as_dicts() -> list[dict[str, Any]]:
    """返回变更记录的普通字典列表。"""

    return [item.to_dict() for item in CONTRACT_CHANGELOG]


__all__ = [
    "CONTRACT_CHANGELOG",
    "CONTRACT_VERSIONS",
    "ContractChange",
    "ContractVersion",
    "changelog_as_dicts",
    "versions_as_dicts",
]

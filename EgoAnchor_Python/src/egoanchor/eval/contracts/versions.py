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
    ContractVersion("csv", 8, "Stage 2 GPT final v2 图表与论文数据 CSV 契约"),
    ContractVersion("metrics", 6, "实验一/二组件近端 raw 对齐指标契约"),
    ContractVersion("analysis_params", 5, "实验一/二静止波动与遮挡尾部参数契约"),
    ContractVersion("analysis_workbook", 1, "Stage 2 实验审阅 XLSX 契约"),
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
    ContractChange("csv-v2", "场景汇总显式保存尝试数、成功率、样本数和完整分布。", True),
    ContractChange("csv-v3", "补齐组件配对键、空值状态、VCD 曲线维度与敏感性审计列。", True),
    ContractChange("csv-v4", "以四张专用 plot-ready 表替换实验一旧 event 图表。", True),
    ContractChange("csv-v5", "增加实验二 Full/Ablated/Delta 机制归因图与审阅工作簿表。", True),
    ContractChange(
        "csv-v6",
        "压缩论文显示表的重复语义列，冻结配对方向同行显示和三位有效数字投影。",
        True,
    ),
    ContractChange(
        "csv-v7",
        "按 GPT final v2 呈现增加 segment 散点、lag 对齐 RMSE 与 Full/Disabled 组件摘要。",
        True,
    ),
    ContractChange(
        "csv-v8",
        "实验二 capture-time alignment 主表改用 admission raw 对齐误差，并固定图表按主指标过滤。",
        True,
    ),
    ContractChange("metrics-v1", "固定五场景指标、单位、方向和 TeX 命名。", True),
    ContractChange(
        "metrics-v2",
        "冻结 Task 6 科学公式、jump P99、同域时延和 workbook-v2 物理来源列。",
        True,
    ),
    ContractChange(
        "metrics-v3",
        "补齐实验一运动、时延、遮挡与 StaticLock 必要 guardrail。",
        True,
    ),
    ContractChange(
        "metrics-v4",
        "冻结 VCD mean-risk 右阶梯 AURC、P95 tail-risk 曲线与 cohort 敏感性。",
        True,
    ),
    ContractChange(
        "metrics-v5",
        "增加 lag 补偿 P95、停止后 jitter、运动 hold 和固定重新可见窗口指标。",
        True,
    ),
    ContractChange(
        "metrics-v6",
        "增加 capture-time/arrival-time admission raw 平移和旋转 P95，用于组件近端归因。",
        True,
    ),
    ContractChange(
        "analysis_params-v2",
        "冻结滤波、运动切窗、响应、沉降、lag、恢复、gap 和单调时钟参数。",
        True,
    ),
    ContractChange(
        "analysis_params-v3",
        "冻结 VCD cohort、coverage、tie、AURC、精确随机参考和敏感性语义。",
        True,
    ),
    ContractChange(
        "analysis_params-v4",
        "冻结停止后公共窗、近零保持容差和重新可见公共窗。",
        True,
    ),
    ContractChange(
        "analysis_params-v5",
        "冻结静止中心化波动和遮挡灾难性失败阈值。",
        True,
    ),
    ContractChange(
        "analysis_workbook-v1",
        "冻结 Stage 2 实验审阅工作簿的 sheet、类型、同源行和回读规则。",
        True,
    ),
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

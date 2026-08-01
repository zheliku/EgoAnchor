"""实验三工作簿、计分与分析结果的稳定数据契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import pandas as pd


EGOANCHOR: Final = "EgoAnchor"
"""完整系统在原始工作簿中的稳定内部 ID。"""

ONE_EURO: Final = "One-Euro"
"""One-Euro 对照在原始工作簿中的稳定内部 ID。"""

METHODS: Final = (ONE_EURO, EGOANCHOR)
"""分析和绘图使用的固定方法顺序。"""

METHOD_LABELS: Final = {
    ONE_EURO: "One-Euro Anchor",
    EGOANCHOR: "EgoAnchor",
}
"""内部方法 ID 到论文显示名的映射。"""

OBJECTS: Final = ("blue_mouse", "stapler", "gamepad")
"""三个正式交叉对象的稳定键。"""

OBJECT_LABELS: Final = {
    "blue_mouse": "Mouse",
    "stapler": "Stapler",
    "gamepad": "Gamepad",
}
"""对象键到论文图英文短标签的映射。"""

PARTICIPANT_BACKGROUND_COLUMNS: Final[dict[str, str]] = {
    "Age": "B1_年龄",
    "Gender": "B2_性别",
    "Handedness": "B3_主手",
    "Vision": "B4_视力",
    "VRMR_Experience": "B5_VR/MR经验",
    "PhysicalMR_Experience": "B6_实物MR经验",
}
"""结果工作簿稳定英文键到 Participants 原始列的映射。"""

PARTICIPANT_CATEGORIES: Final[dict[str, tuple[str, ...]]] = {
    "Gender": ("女", "男", "非二元或其他", "不愿透露"),
    "Handedness": ("右手", "左手", "双手均可"),
    "Vision": ("正常", "矫正后正常", "其他"),
    "VRMR_Experience": ("从未", "1–5 次", "6–20 次", "超过 20 次", "经常使用"),
    "PhysicalMR_Experience": ("从未", "1–2 次", "数次", "经常"),
    "Baseline_Discomfort": ("无", "轻微", "中等", "明显", "因不适中止"),
    "End_Discomfort": ("无", "轻微", "中等", "明显", "因不适中止"),
}
"""背景与安全字段的冻结选项及论文汇报顺序。"""

EXCLUSION_REASONS: Final = (
    "参与者退出",
    "身体不适",
    "设备故障",
    "网络故障",
    "追踪异常",
    "问卷中断",
    "协议偏离",
    "其他（见备注）",
)
"""参与者级退出或技术排除的冻结主原因；细节只写备注。"""

WORKBOOK_CONTRACT_ID: Final = "EgoAnchor.Experiment3.RawData.v5.1"
"""正式原始工作簿写入核心属性的稳定契约标识。"""

WORKBOOK_SOURCE_CATEGORY: Final = "formal-participant-data"
"""正式参与者原始数据使用的核心属性类别。"""

BLOCK_ITEMS: Final = {
    "Q1": "Q1",
    "Q2": "Q2",
    "Q9": "Q9",
    "Q10": "Q10_OPT",
    "AQ_IQ2": "AQ_IQ2",
    "AQ_IQ3": "AQ_IQ3",
    "Q3": "Q3",
    "Q8": "Q8",
    "AQ_EQ1": "AQ_EQ1",
    "AQ_EQ2": "AQ_EQ2",
    "AQ_EQ3": "AQ_EQ3",
    "AQ_IQ1": "AQ_IQ1",
    "Q6": "Q6",
    "Q7": "Q7",
}
"""分析条目 ID 到 Records A 段列名的映射。"""

BLOCK_RECORD_COLUMNS: Final = {
    "Q1": "K",
    "Q2": "L",
    "Q9": "M",
    "Q10": "N",
    "AQ_IQ2": "O",
    "AQ_IQ3": "P",
    "Q3": "Q",
    "Q8": "R",
    "AQ_EQ1": "S",
    "AQ_EQ2": "T",
    "AQ_EQ3": "U",
    "AQ_IQ1": "V",
    "Q6": "W",
    "Q7": "X",
}
"""区块条目到 Records A 段 Excel 列的稳定映射。"""

AQ_SCALE_ITEMS: Final[dict[str, dict[str, tuple[str, ...]]]] = {
    "full": {
        "AQ_EQ": ("AQ_EQ1", "AQ_EQ2", "AQ_EQ3"),
        "AQ_IQ": ("AQ_IQ1", "AQ_IQ2", "AQ_IQ3"),
    },
    "reduced": {
        "AQ_EQ": ("AQ_EQ1", "AQ_EQ2"),
        "AQ_IQ": ("AQ_IQ2", "AQ_IQ3"),
    },
}
"""预实验冻结前后两种 AQ 模式的唯一条目契约。"""

PRIMARY_OUTCOMES: Final = ("Q1", "Q8", "Q2", "Q9", "Q3", "Q6", "Q7")
"""主证实家族的冻结顺序。"""

SCALE_OUTCOMES: Final = ("AQ_EQ", "AQ_IQ", "TIA_RC", "TIA_UP", "STIAS")
"""已发表量表家族的冻结顺序。"""

OUTCOME_LABELS: Final = {
    "Q1": "Static stability",
    "Q8": "Position correctness",
    "Q2": "Motion attachment",
    "Q9": "Orientation consistency",
    "Q3": "Recovery consistency",
    "Q6": "Willingness to rely",
    "Q7": "Stability-response balance",
    "Q10": "Post-placement settling",
    "AQ_EQ": "AQ Embedding Quality",
    "AQ_IQ": "AQ Interaction Quality",
    "TIA_RC": "TiA Reliability/Competence",
    "TIA_UP": "TiA Understanding/Predictability",
    "STIAS": "S-TIAS",
}
"""稳定结果键到论文图英文标签的映射。"""

METHOD_ITEM_COLUMNS: Final = (
    "TIA_RC1",
    "TIA_RC2",
    "TIA_RC3_REV",
    "TIA_RC4",
    "TIA_RC5_REV",
    "TIA_RC6",
    "TIA_UP1",
    "TIA_UP2_REV",
    "TIA_UP3",
    "TIA_UP4_REV",
    "STIAS1",
    "STIAS2",
    "STIAS3",
)
"""Records B 段的原始方法级评分列。"""

METHOD_RECORD_COLUMNS: Final = dict(
    zip(METHOD_ITEM_COLUMNS, ("E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P", "Q"), strict=True)
)
"""方法级原始条目到 Records B 段 Excel 列的稳定映射。"""

METHOD_SCALE_ITEMS: Final = {
    "TIA_RC": ("TIA_RC1", "TIA_RC2", "TIA_RC3_REV", "TIA_RC4", "TIA_RC5_REV", "TIA_RC6"),
    "TIA_UP": ("TIA_UP1", "TIA_UP2_REV", "TIA_UP3", "TIA_UP4_REV"),
    "STIAS": ("STIAS1", "STIAS2", "STIAS3"),
}
"""三个方法级已发表量表的唯一条目契约。"""

REVERSED_TIA_ITEMS: Final = frozenset(
    {"TIA_RC3_REV", "TIA_RC5_REV", "TIA_UP2_REV", "TIA_UP4_REV"}
)
"""必须按 ``6 - raw`` 换向的 TiA 原始条目。"""


def aq_scale_items(aq_mode: str) -> dict[str, tuple[str, ...]]:
    """返回指定冻结模式下的 AQ 子量表条目。"""

    try:
        return AQ_SCALE_ITEMS[aq_mode]
    except KeyError as error:
        raise ValueError(f"未知 AQ 模式：{aq_mode}") from error


def required_block_items(aq_mode: str) -> tuple[str, ...]:
    """返回一个有效区块必须填写的全部非可选评分。"""

    aq_items = aq_scale_items(aq_mode)
    return (
        "Q1",
        "Q2",
        "Q9",
        "AQ_IQ2",
        "AQ_IQ3",
        "Q3",
        "Q8",
        *aq_items["AQ_EQ"],
        *tuple(item for item in aq_items["AQ_IQ"] if item not in {"AQ_IQ2", "AQ_IQ3"}),
        "Q6",
        "Q7",
    )


def published_scale_items(scale: str, aq_mode: str) -> tuple[str, ...]:
    """返回一个已发表量表在当前模式下的条目。"""

    if scale in {"AQ_EQ", "AQ_IQ"}:
        return aq_scale_items(aq_mode)[scale]
    try:
        return METHOD_SCALE_ITEMS[scale]
    except KeyError as error:
        raise ValueError(f"未知已发表量表：{scale}") from error


@dataclass(frozen=True, slots=True)
class Exp3Data:
    """保存从原始工作簿严格读取的四张逻辑数据表。"""

    participants: pd.DataFrame
    """Participants 表中的 24 个平衡单元与人工录入字段。"""

    blocks: pd.DataFrame
    """Records A 段的一行一区块原始记录。"""

    methods: pd.DataFrame
    """Records B 段的一行一方法原始记录。"""

    finals: pd.DataFrame
    """Records C 段的一行一参与者最终问卷记录。"""

    source_kind: str
    """输入来源类型：formal、synthetic 或 unknown。"""

    source_path: str
    """本次只读输入工作簿的规范化绝对路径。"""

    source_sha256: str
    """本次输入工作簿的 SHA-256。"""


@dataclass(frozen=True, slots=True)
class ScoreData:
    """保存原始评分派生出的区块、方法与参与者配对长表。"""

    block_scores: pd.DataFrame
    """有效区块的原始条目与 AQ 子量表分。"""

    method_scores: pd.DataFrame
    """方法级 TiA 换向条目、分量表与 S-TIAS 分。"""

    aggregate_scores: pd.DataFrame
    """每位参与者每种方法在三物体上的冻结汇总分。"""

    paired_scores: pd.DataFrame
    """每位参与者各结局的 EgoAnchor、One-Euro 与配对差。"""

    reliability_items: pd.DataFrame
    """已发表量表信度计算使用的参与者级条目长表。"""


MAIN_FAMILY: Final = "Main_Confirmatory"
"""主证实家族在结果表 ``Family`` 列中的稳定取值。"""

SCALE_FAMILY: Final = "Published_Scale"
"""已发表量表家族在结果表 ``Family`` 列中的稳定取值。"""

EXPLORATORY_FAMILY: Final = "Exploratory"
"""探索性条目在结果表 ``Family`` 列中的稳定取值。"""


@dataclass(frozen=True, slots=True)
class AnalysisTables:
    """保存结果工作簿和绘图所需的全部确定性分析表。

    每张表只出现一次，不保留任何重排或裁剪后的副本：结果工作簿直接落盘这些表，
    论文图表也只从同一批表取数，避免同一数字在多张工作表里重复呈现。
    """

    sample: pd.DataFrame
    """样本流程、人口学、经验、安全描述与 24 平衡单元的设计平衡。"""

    participant_audit: pd.DataFrame
    """去除自由文本后的逐参与者流程、完整性、时长与安全审计。"""

    results: pd.DataFrame
    """三个家族（主证实、已发表量表、探索性）的配对推断结果纵向合并表。"""

    objects: pd.DataFrame
    """区块结局按对象拆分的配对结果，含面板内 Holm 的探索性显著性。"""

    reliability: pd.DataFrame
    """五个已发表量表按方法计算的当前样本信度。"""

    manipulation: pd.DataFrame
    """候选、VCD、输出与生命周期操纵检验。"""

    choices: pd.DataFrame
    """最终偏好、信任选择、强度、区分信心摘要与偏好×信任交叉表。"""

    open_coding: pd.DataFrame
    """两道开放题的双编码与裁决工作区。"""


__all__ = [
    "BLOCK_ITEMS",
    "BLOCK_RECORD_COLUMNS",
    "AQ_SCALE_ITEMS",
    "AnalysisTables",
    "EGOANCHOR",
    "EXCLUSION_REASONS",
    "EXPLORATORY_FAMILY",
    "Exp3Data",
    "MAIN_FAMILY",
    "METHODS",
    "METHOD_ITEM_COLUMNS",
    "METHOD_LABELS",
    "METHOD_RECORD_COLUMNS",
    "METHOD_SCALE_ITEMS",
    "OBJECTS",
    "OBJECT_LABELS",
    "ONE_EURO",
    "OUTCOME_LABELS",
    "PARTICIPANT_BACKGROUND_COLUMNS",
    "PARTICIPANT_CATEGORIES",
    "PRIMARY_OUTCOMES",
    "REVERSED_TIA_ITEMS",
    "SCALE_FAMILY",
    "SCALE_OUTCOMES",
    "ScoreData",
    "WORKBOOK_CONTRACT_ID",
    "WORKBOOK_SOURCE_CATEGORY",
    "aq_scale_items",
    "published_scale_items",
    "required_block_items",
]

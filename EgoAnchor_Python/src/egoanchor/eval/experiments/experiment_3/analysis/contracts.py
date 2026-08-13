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

TARGET_PARTICIPANTS: Final = 24
"""正式设计预分配的参与者和平衡单元数。"""

MINIMUM_PARTICIPANTS: Final = 18
"""每项冻结结局进入正式推断所需的最小完整配对人数。"""

METHOD_LABELS: Final = {
    ONE_EURO: "One-Euro",
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

OBJECT_RAW_LABELS: Final = {
    "blue_mouse": "鼠标",
    "stapler": "固定订书机",
    "gamepad": "游戏手柄",
}
"""对象键到正式采集工作簿中文设计标签的映射。"""

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
    "VRMR_Experience": (
        "从未",
        "1–5 次",
        "6–20 次",
        "超过 20 次",
        "经常使用",
        "21 次及以上",
    ),
    "PhysicalMR_Experience": ("从未", "1–2 次", "数次", "经常"),
    "Baseline_Discomfort": ("无", "轻微", "中等", "明显", "因不适中止"),
    "End_Discomfort": ("无", "轻微", "中等", "明显", "因不适中止"),
}
"""背景与安全字段的允许选项；兼容当前工作簿中已经录入的 B5 分档。"""

VRMR_EXPERIENCE_TEMPLATE_OPTIONS: Final = ("从未", "1–5 次", "6–20 次", "21 次及以上")
"""v5.3 模板使用的互斥累计次数选项。"""

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

WORKBOOK_CONTRACT_ID: Final = "EgoAnchor.Experiment3.RawData.v5.3"
"""当前 v5.3 原始工作簿与派生空白模板的稳定契约标识。"""

WORKBOOK_DATA_CATEGORY: Final = "experiment-3-raw-workbook"
"""实验三原始工作簿的通用数据类别，仅用于 provenance。"""

BLOCK_ITEMS: Final = {
    "Q1": "Q1",
    "Q2": "Q2",
    "Q3": "Q3",
    "Q4": "Q4",
    "Q5": "Q5",
    "Q6": "Q6",
    "Q7": "Q7",
    "AQ_EQ1": "AQ_EQ1",
    "AQ_EQ2": "AQ_EQ2",
    "AQ_EQ3": "AQ_EQ3",
    "AQ_IQ1": "AQ_IQ1",
    "AQ_IQ2": "AQ_IQ2",
    "AQ_IQ3": "AQ_IQ3",
}
"""分析条目 ID 到 ``Block`` 工作表列名的映射，顺序与问卷一致。"""

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

PRIMARY_OUTCOMES: Final = ("Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7")
"""七个研究定制条目按问卷出现顺序排列的冻结报告顺序。"""

SCALE_OUTCOMES: Final = ("AQ_EQ", "AQ_IQ", "TIA_RC", "TIA_UP", "STIAS")
"""已发表量表家族的冻结顺序。"""

OUTCOME_LABELS: Final = {
    "Q1": "Static stability",
    "Q2": "Motion attachment",
    "Q3": "Orientation consistency",
    "Q4": "Recovery consistency",
    "Q5": "Position correctness",
    "Q6": "Willingness to rely",
    "Q7": "Stability-response balance",
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
"""``Method`` 工作表的原始方法级评分列。"""

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
        *PRIMARY_OUTCOMES,
        *aq_items["AQ_EQ"],
        *aq_items["AQ_IQ"],
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
    """``Block`` 工作表的一行一区块原始记录。"""

    methods: pd.DataFrame
    """``Method`` 工作表的一行一方法原始记录。"""

    finals: pd.DataFrame
    """``Final`` 工作表的一行一参与者最终问卷记录。"""

    source_path: str
    """本次只读输入工作簿的规范化绝对路径。"""

    source_sha256: str
    """本次输入工作簿的 SHA-256。"""


@dataclass(frozen=True, slots=True)
class ScoreData:
    """保存结果统计和正文单排复合图共同消费的派生长表。"""

    block_scores: pd.DataFrame
    """有效区块的原始条目与 AQ 子量表分。"""

    paired_scores: pd.DataFrame
    """每位参与者各结局的 EgoAnchor、One-Euro 与配对差。"""

    reliability_items: pd.DataFrame
    """已发表量表信度计算使用的参与者级条目长表。"""


MAIN_FAMILY: Final = "Main_Confirmatory"
"""主证实家族在结果表 ``Family`` 列中的稳定取值。"""

SCALE_FAMILY: Final = "Published_Scale"
"""已发表量表家族在结果表 ``Family`` 列中的稳定取值。"""

@dataclass(frozen=True, slots=True)
class AnalysisTables:
    """保存结果工作簿和论文图所需的六类确定性分析表。

    逐参与者审计、开放题编码工作区和派生评分长表不属于论文结果，因此不进入本契约。
    前两者分别留在样本汇总的内部计算过程和独立的人工定性编码流程中；派生评分则由
    ``ScoreData`` 持有，避免在结果工作簿中重复堆放同一数字。
    """

    sample: pd.DataFrame
    """样本流程、人口学、经验、安全描述与 24 平衡单元的设计平衡。"""

    results: pd.DataFrame
    """主证实与已发表量表两个预先固定统计家族共十二项配对推断结果。"""

    objects: pd.DataFrame
    """七个主条目按三个对象拆分的描述统计，不包含任何逐对象推断。"""

    reliability: pd.DataFrame
    """已发表量表家族五项结局按方法计算的当前样本信度。"""

    choices: pd.DataFrame
    """最终偏好、信任选择、强度、区分信心摘要与偏好×信任交叉表。"""

__all__ = [
    "BLOCK_ITEMS",
    "AQ_SCALE_ITEMS",
    "AnalysisTables",
    "EGOANCHOR",
    "EXCLUSION_REASONS",
    "Exp3Data",
    "MAIN_FAMILY",
    "MINIMUM_PARTICIPANTS",
    "METHODS",
    "METHOD_ITEM_COLUMNS",
    "METHOD_LABELS",
    "METHOD_SCALE_ITEMS",
    "OBJECTS",
    "OBJECT_LABELS",
    "OBJECT_RAW_LABELS",
    "ONE_EURO",
    "OUTCOME_LABELS",
    "PARTICIPANT_BACKGROUND_COLUMNS",
    "PARTICIPANT_CATEGORIES",
    "VRMR_EXPERIENCE_TEMPLATE_OPTIONS",
    "PRIMARY_OUTCOMES",
    "REVERSED_TIA_ITEMS",
    "SCALE_FAMILY",
    "SCALE_OUTCOMES",
    "ScoreData",
    "TARGET_PARTICIPANTS",
    "WORKBOOK_CONTRACT_ID",
    "WORKBOOK_DATA_CATEGORY",
    "aq_scale_items",
    "published_scale_items",
    "required_block_items",
]

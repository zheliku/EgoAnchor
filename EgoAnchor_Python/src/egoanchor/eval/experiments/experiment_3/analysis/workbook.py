"""实验三离线分析结果工作簿的写入与回读校验。"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from openpyxl import Workbook, load_workbook  # type: ignore[import-untyped]
from openpyxl.formatting.rule import CellIsRule  # type: ignore[import-untyped]
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side  # type: ignore[import-untyped]
from openpyxl.utils import get_column_letter  # type: ignore[import-untyped]

from .contracts import AnalysisTables, Exp3Data, ScoreData
from .settings import AnalysisSettings


_NAVY = "18324A"
_TEAL = "2F6F73"
_PALE_BLUE = "DCEAF5"
_GREEN = "E2F0D9"
_YELLOW = "FFF2CC"
_RED = "FCE8E6"
_WHITE = "FFFFFF"
_TEXT = "22313F"
_GRID = "C8D1D9"
"""结果工作簿配色。"""

SCORES_BLOCK_SHEET = "Scores_Block"
"""论文主图读取的逐参与者×对象×方法区块评分表名。"""

SCORES_PAIRED_SHEET = "Scores_Paired"
"""论文量表图读取的逐参与者三物体均值配对表名。"""

OBJECT_RESULTS_SHEET = "Results_By_Object"
"""论文主图读取面板内探索性显著性的逐对象结果表名。"""

RESULTS_SHEET = "Results"
"""三家族配对推断结果的唯一结果表名。"""

_SHEET_GUIDE: tuple[tuple[str, str], ...] = (
    ("README", "本页：来源、冻结规则、诚实边界与工作表索引"),
    ("Sample", "样本流程、人口学、经验、安全与 24 平衡单元设计平衡（按 Section 分节）"),
    ("Participant_Audit", "逐参与者流程与完整性核查，一行一人"),
    (RESULTS_SHEET, "唯一结果表：主证实 / 已发表量表 / 探索性三家族按 Family 列纵向排列"),
    (OBJECT_RESULTS_SHEET, "逐对象配对结果；探索性，Holm 只在同一结局的三个对象内校正"),
    ("Reliability", "五个已发表量表按方法的当前样本 α、ω 与 Spearman-Brown"),
    ("Model_CLMM", "次要分析：逐条目累积 logit 固定效应与逐对象对比，按 Row_Kind 区分"),
    ("Manipulation", "候选率、VCD、输出可用性、遮挡生命周期与重获取操纵检验"),
    ("Choices", "最终偏好、信任选择、偏好强度、区分信心与偏好×信任交叉"),
    ("Open_Coding", "两道开放题的双编码与裁决工作区，需人工填写"),
    (SCORES_BLOCK_SHEET, "派生层：一行一区块的条目分与 AQ 子量表，图 4 数据源"),
    ("Scores_Method", "派生层：一行一方法级问卷，含 TiA 换向条目与量表分"),
    (SCORES_PAIRED_SHEET, "派生层：一行一参与者×结局的两方法值与配对差，图 5 数据源"),
)
"""结果工作簿的工作表顺序与一句话用途，同时用于 README 索引和回读校验。"""

_INTEGER_COLUMNS = frozenset(
    {
        "N",
        "Denominator",
        "Missing_N",
        "Valid_Blocks",
        "Completed_Method_Assessments",
        "Valid_Method_Records",
        "Age",
        "Count",
        "Total",
        "N_Pairs",
        "N_Nonzero",
        "Items",
        "N_Responses",
        "N_Participants",
        "Iterations",
        "Block_Index",
        "Rating_Order",
    }
)
"""按整数格式显示的列名。"""


def write_results_workbook(
    destination: Path,
    *,
    data: Exp3Data,
    scores: ScoreData,
    tables: AnalysisTables,
    clmm_coefficients: pd.DataFrame,
    clmm_contrasts: pd.DataFrame,
    settings: AnalysisSettings,
    settings_sha256: str,
    batch_config_path: Path,
    paper_config_path: Path,
    validation: dict[str, Any],
) -> Path:
    """写入结果 XLSX：每个数字只出现一次，且顺序与 README 索引一致。"""

    output = destination.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    workbook.remove(workbook.active)
    _write_readme(
        workbook,
        data,
        settings,
        settings_sha256,
        batch_config_path,
        paper_config_path,
        validation,
    )
    _write_frame(workbook, "Sample", tables.sample)
    _write_frame(workbook, "Participant_Audit", tables.participant_audit)
    _write_frame(workbook, RESULTS_SHEET, tables.results, significant_column="p_Holm")
    _write_frame(workbook, OBJECT_RESULTS_SHEET, tables.objects, significant_column="p_Holm_Panel")
    _write_frame(workbook, "Reliability", tables.reliability)
    _write_frame(
        workbook,
        "Model_CLMM",
        _merge_clmm(clmm_coefficients, clmm_contrasts),
        significant_column="p_raw",
    )
    _write_frame(workbook, "Manipulation", tables.manipulation, significant_column="p_TOST")
    _write_frame(workbook, "Choices", tables.choices)
    _write_frame(workbook, "Open_Coding", tables.open_coding)
    _write_frame(workbook, SCORES_BLOCK_SHEET, _public_scores(scores.block_scores))
    _write_frame(workbook, "Scores_Method", _public_scores(scores.method_scores))
    _write_frame(workbook, SCORES_PAIRED_SHEET, scores.paired_scores)
    workbook.calculation.calcMode = "auto"
    workbook.calculation.fullCalcOnLoad = True
    workbook.save(output)
    workbook.close()
    _verify_results_workbook(output, data.source_sha256, len(validation["included_participants"]))
    return output


def _merge_clmm(coefficients: pd.DataFrame, contrasts: pd.DataFrame) -> pd.DataFrame:
    """把 CLMM 固定效应与逐对象对比堆叠为一张模型表。"""

    frames: list[pd.DataFrame] = []
    if not coefficients.empty:
        fixed = coefficients.rename(columns={"Effect": "Term"}).copy()
        fixed.insert(0, "Row_Kind", "fixed_effect")
        frames.append(fixed)
    if not contrasts.empty:
        contrast = contrasts.copy()
        contrast.insert(0, "Row_Kind", "object_contrast")
        contrast["Term"] = "Method@" + contrast["Object_Key"].astype(str)
        frames.append(contrast)
    if not frames:
        return pd.DataFrame()
    merged = pd.concat(frames, ignore_index=True)
    leading = [column for column in ("Row_Kind", "Outcome", "Term", "Object_Key") if column in merged]
    return merged.loc[:, leading + [column for column in merged.columns if column not in leading]]


def _public_scores(frame: pd.DataFrame) -> pd.DataFrame:
    """去掉派生层的内部保密列名，只保留分析可读的方法列。"""

    return frame.rename(columns={"Condition(保密)": "Condition"})


def _write_readme(
    workbook: Workbook,
    data: Exp3Data,
    settings: AnalysisSettings,
    settings_digest: str,
    batch_config_path: Path,
    paper_config_path: Path,
    validation: dict[str, Any],
) -> None:
    """写入来源、冻结规则、诚实边界与工作表索引的首屏。"""

    warnings = "；".join(validation.get("warnings", ())) or "无"
    rows: list[tuple[str, Any]] = [
        ("EgoAnchor 实验三分析结果", "由原始 Records 独立重算；不读取原始模板的公式缓存"),
        ("── 来源", None),
        ("输入工作簿", data.source_path),
        ("输入 SHA-256", data.source_sha256),
        ("来源类型", data.source_kind),
        ("批处理配置", str(batch_config_path)),
        ("论文参数配置", str(paper_config_path)),
        ("参数 SHA-256", settings_digest),
        ("模板版本", settings.template_version),
        ("纳入参与者", validation["included_count"]),
        ("── 冻结规则", None),
        ("AQ 模式", settings.aq_mode),
        ("Q10", "启用" if settings.q10_enabled else "未启用"),
        ("Wilcoxon", "双侧；零差删除；并列秩精确符号置换；家族内 Holm"),
        ("汇总单位", "每位参与者先在三个对象上取均值，再形成 EgoAnchor−One-Euro 配对差"),
        ("多重比较", f"Results 表按 Family 分族 Holm；{OBJECT_RESULTS_SHEET} 只在结局内三对象间 Holm，属探索性"),
        ("CLMM", "逐条目随机截距累积 logit；报告收敛、梯度和交互 LRT"),
        ("TOST", "仅在预实验冻结正等价界后启用" if settings.equivalence_enabled else "未运行：等价界尚未冻结"),
        ("当前样本信度", "只对 AQ、TiA 与 S-TIAS 报告；不宣称验证改编量表"),
        ("── 边界与警告", None),
        ("警告", warnings),
        ("发布边界", "实验三只报告主观评价和无需真值的自参考日志，不提供客观任务表现证据"),
        ("── 工作表索引", None),
    ]
    rows.extend(_SHEET_GUIDE)
    _write_key_value_sheet(workbook, "README", tuple(rows))


def _write_key_value_sheet(
    workbook: Workbook,
    name: str,
    rows: tuple[tuple[str, Any], ...],
) -> None:
    """写入带深色标题和分节小标题的首屏事实表。"""

    worksheet = workbook.create_sheet(name)
    worksheet.merge_cells("A1:B1")
    worksheet["A1"] = str(rows[0][0])
    worksheet["A1"].fill = PatternFill("solid", fgColor=_NAVY)
    worksheet["A1"].font = Font(color=_WHITE, bold=True, size=15)
    worksheet["A1"].alignment = Alignment(vertical="center")
    worksheet.row_dimensions[1].height = 28
    worksheet["A2"] = "说明"
    worksheet["B2"] = rows[0][1]
    for row_index, (key, value) in enumerate(rows[1:], start=3):
        worksheet.cell(row_index, 1, key)
        worksheet.cell(row_index, 2, _excel_value(value))
    for row in worksheet.iter_rows(min_row=2, max_row=worksheet.max_row, max_col=2):
        is_section = row[1].value is None
        row[0].fill = PatternFill("solid", fgColor=_TEAL if is_section else _PALE_BLUE)
        row[0].font = Font(color=_WHITE if is_section else _TEXT, bold=True, size=10)
        for cell in row:
            cell.border = _border()
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        if is_section:
            row[1].fill = PatternFill("solid", fgColor=_TEAL)
    worksheet.column_dimensions["A"].width = 22
    worksheet.column_dimensions["B"].width = 98
    worksheet.freeze_panes = "A3"
    worksheet.sheet_view.showGridLines = False


def _write_frame(
    workbook: Workbook,
    name: str,
    frame: pd.DataFrame,
    *,
    significant_column: str | None = None,
) -> None:
    """把 DataFrame 写为普通单元格安全表，并应用统一格式。"""

    worksheet = workbook.create_sheet(name)
    columns = [str(column) for column in frame.columns]
    if not columns:
        worksheet["A1"] = "No rows"
        return
    for column_index, column in enumerate(columns, start=1):
        cell = worksheet.cell(1, column_index, column)
        cell.fill = PatternFill("solid", fgColor=_NAVY)
        cell.font = Font(color=_WHITE, bold=True, size=10)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = _border()
    for row_index, values in enumerate(frame.itertuples(index=False, name=None), start=2):
        for column_index, value in enumerate(values, start=1):
            column = columns[column_index - 1]
            cell = worksheet.cell(row_index, column_index, _excel_value(value))
            cell.fill = PatternFill("solid", fgColor=_GREEN if row_index % 2 == 0 else "F4F8F7")
            cell.font = Font(color=_TEXT, size=9)
            cell.border = _border()
            cell.alignment = Alignment(vertical="top", wrap_text=isinstance(value, str) and len(value) > 35)
            if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool):
                cell.number_format = _number_format(column)
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{max(1, len(frame) + 1)}"
    worksheet.row_dimensions[1].height = 32
    for column_index, column in enumerate(columns, start=1):
        sample = [len(column)]
        if not frame.empty:
            sample.extend(len(str(value)) for value in frame.iloc[:100, column_index - 1] if pd.notna(value))
        worksheet.column_dimensions[get_column_letter(column_index)].width = min(42, max(10, max(sample) + 2))
    worksheet.sheet_view.showGridLines = False
    if significant_column in columns and len(frame):
        column_letter = get_column_letter(columns.index(significant_column) + 1)
        cells = f"{column_letter}2:{column_letter}{len(frame) + 1}"
        worksheet.conditional_formatting.add(
            cells,
            CellIsRule(operator="lessThan", formula=["0.05"], fill=PatternFill("solid", fgColor=_YELLOW)),
        )
    if "Converged" in columns and len(frame):
        column_letter = get_column_letter(columns.index("Converged") + 1)
        worksheet.conditional_formatting.add(
            f"{column_letter}2:{column_letter}{len(frame) + 1}",
            CellIsRule(operator="equal", formula=["FALSE"], fill=PatternFill("solid", fgColor=_RED)),
        )


def _excel_value(value: Any) -> Any:
    """把 pandas/numpy 值转换为 openpyxl 可安全写入的标量。"""

    if value is None or (isinstance(value, (float, np.floating)) and not math.isfinite(float(value))):
        return None
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (tuple, list, dict)):
        return str(value)
    return value


def _number_format(column: str) -> str:
    """按列语义选择结果工作簿中的稳定数字格式。"""

    if column == "Proportion" or "Percent" in column:
        return "0.0%"
    if column in _INTEGER_COLUMNS:
        return "0"
    if column == "Session_Duration_Minutes":
        return "0.0"
    return "0.0000"


def _border() -> Border:
    """返回统一浅灰细边框。"""

    side = Side(style="thin", color=_GRID)
    return Border(left=side, right=side, top=side, bottom=side)


def _verify_results_workbook(path: Path, input_sha256: str, included_count: int) -> None:
    """回读工作表清单和来源字段，避免静默写出不完整结果。"""

    workbook = load_workbook(path, read_only=True, data_only=False)
    try:
        expected = [name for name, _ in _SHEET_GUIDE]
        if workbook.sheetnames != expected:
            raise ValueError(
                f"实验三结果工作簿的工作表清单必须与 README 索引一致：{workbook.sheetnames}"
            )
        readme = workbook["README"]
        values = {str(readme.cell(row, 1).value): readme.cell(row, 2).value for row in range(2, readme.max_row + 1)}
        if values.get("输入 SHA-256") != input_sha256:
            raise ValueError("实验三结果工作簿的输入摘要回读不一致")
        if int(values.get("纳入参与者") or 0) != included_count:
            raise ValueError("实验三结果工作簿的纳入人数回读不一致")
        sample = workbook["Sample"]
        headers = [sample.cell(1, column).value for column in range(1, sample.max_column + 1)]
        rows = [dict(zip(headers, values, strict=True)) for values in sample.iter_rows(min_row=2, values_only=True)]
        included_rows = [
            row for row in rows
            if row.get("Section") == "Sample_Flow" and row.get("Variable") == "Included"
        ]
        if len(included_rows) != 1 or int(included_rows[0].get("N") or 0) != included_count:
            raise ValueError("实验三结果工作簿的样本汇总 N 回读不一致")
    finally:
        workbook.close()


__all__ = [
    "OBJECT_RESULTS_SHEET",
    "RESULTS_SHEET",
    "SCORES_BLOCK_SHEET",
    "SCORES_PAIRED_SHEET",
    "write_results_workbook",
]

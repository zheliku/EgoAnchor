"""从 v5.1 美化定稿生成正式空白原始数据模板。"""

from __future__ import annotations

from copy import copy
from pathlib import Path
from typing import Any
from uuid import uuid4

from openpyxl import load_workbook  # type: ignore[import-untyped]
from openpyxl.formatting.rule import FormulaRule  # type: ignore[import-untyped]
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side  # type: ignore[import-untyped]
from openpyxl.utils import get_column_letter  # type: ignore[import-untyped]
from openpyxl.worksheet.datavalidation import DataValidation  # type: ignore[import-untyped]

from .analysis import (
    BLOCK_RECORD_COLUMNS,
    EXCLUSION_REASONS,
    METHOD_RECORD_COLUMNS,
    OBJECT_LABELS,
    OBJECTS,
    OUTCOME_LABELS,
    PARTICIPANT_CATEGORIES,
    PRIMARY_OUTCOMES,
    REVERSED_TIA_ITEMS,
    SCALE_OUTCOMES,
    WORKBOOK_CONTRACT_ID,
    WORKBOOK_DATA_CATEGORY,
    aq_scale_items,
    required_block_items,
)
from .analysis import AnalysisSettings


_NAVY = "18324A"
_TEAL = "2F6F73"
_PALE_BLUE = "DCEAF5"
_GREEN = "E2F0D9"
_YELLOW = "FFF2CC"
_PALE_RED = "FCE8E6"
_TEXT = "22313F"
_WHITE = "FFFFFF"
_GRID = "C8D1D9"
"""正式模板沿用的克制配色。"""


def build_raw_template(
    settings: AnalysisSettings,
    destination: Path,
    *,
    source_template: Path,
) -> Path:
    """复制美化来源，清空采集值并加入实时公式分析区。"""

    source = source_template.expanduser().resolve()
    output = destination.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"原始美化模板不存在：{source}")
    if output == source.resolve():
        raise ValueError("新原始模板不得覆盖美化来源文件")
    if output.exists():
        raise FileExistsError(f"拒绝覆盖已有实验三原始工作簿：{output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.stem}.{uuid4().hex}.tmp.xlsx")
    workbook = load_workbook(source)
    try:
        _clean_front_matter(workbook)
        _clear_collection_fields(workbook)
        _repair_participant_validations(workbook)
        _repair_records_validations(workbook)
        _replace_formula_sheets(workbook, settings)
        _enable_recalculation(workbook)
        workbook.save(temporary)
    finally:
        workbook.close()
    try:
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def _clean_front_matter(workbook: Any) -> None:
    """删除过期过程说明，并把首屏改成正式采集事实。"""

    workbook.properties.identifier = WORKBOOK_CONTRACT_ID
    workbook.properties.category = WORKBOOK_DATA_CATEGORY
    workbook.properties.version = "v5.1"
    readme = workbook["README"]
    readme["A1"] = "EgoAnchor 实验三原始数据工作簿（v5.1）"
    readme["A2"] = (
        "唯一权威规格：2026-EgoAnchor/experiment_3_questionnaire_design_zh.md（v5.1）。"
        "Participants 与 Records 是唯一人工输入；Derived 是只读公式派生层，"
        "Analysis 是现场描述性仪表板。Python 分析另行写出结果工作簿，"
        "不会回填本文件的黄色区域。TiA 反向计分仅在派生层执行。"
    )
    readme["A19"] = (
        "中文施测措辞已于 2026-07-26 冻结为 v5.1 Final wording。正式采集前完成确认性认知访谈；"
        "只有发现理解不良时，才按修订、重测、再冻结的顺序处理。"
    )
    readme["A10"] = "5 现场核对"
    readme["D10"] = "Derived/Analysis 公式实时显示完整性、参与者概况和可计算描述量"
    readme["E10"] = "正式推断由 pixi run eval analyze exp3 另写结果 XLSX"
    readme["A27"] = "工作簿契约"
    readme["B27"] = WORKBOOK_CONTRACT_ID
    readme["A28"] = "数据类别"
    readme["B28"] = WORKBOOK_DATA_CATEGORY
    for row in (27, 28):
        readme.cell(row, 1)._style = copy(readme["A13"]._style)
        readme.cell(row, 2)._style = copy(readme["B13"]._style)
    audit = workbook["Verification_Audit"]
    audit["A1"] = "内容核验记录（v5.1；正式采集前审计）"
    audit["A2"] = (
        "官方原文、对象化改编和当前样本信度必须分开表述；正式采集前剩余前置为确认性认知访谈与预留参数冻结。"
    )
    audit["C18"] = (
        "Q2 已按 v5.1 冻结为“始终附着在真实物体上的同一位置”，用于与 AQ-IQ3 的运动平滑构念区分。"
    )
    questionnaire = workbook["Questionnaire"]
    questionnaire["A2"] = (
        "中文施测版为头显或纸面呈现文本；官方英文原文仅用于核对，对象化英文施测版用于附录与英文施测。"
        "正式中文措辞已经逐条语义审计，预实验继续做确认性认知访谈。"
    )


def _clear_collection_fields(workbook: Any) -> None:
    """保留设计映射，清空所有需要人工或运行时写入的字段。"""

    participants = workbook["Participants"]
    for row in range(3, 27):
        for column in range(12, 25):
            participants.cell(row, column).value = None

    records = workbook["Records"]
    for row in range(5, 149):
        for column in range(11, 42):
            records.cell(row, column).value = None
    for row in range(152, 200):
        for column in range(5, 26):
            records.cell(row, column).value = None
    for row in range(203, 227):
        for column in range(2, 12):
            records.cell(row, column).value = None

    # v5.1 预实验要求的方法归属回忆与记录有效性审核补在 B 段末尾。
    records["X151"] = "A/B归属回忆确认"
    records["Y151"] = "方法级记录有效"
    for column in (24, 25):
        records.cell(151, column)._style = copy(records["W151"]._style)
        records.cell(151, column).alignment = copy(records["W151"].alignment)
        records.column_dimensions[get_column_letter(column)].width = 16
        for row in range(152, 200):
            records.cell(row, column)._style = copy(records["W152"]._style)

    # 原版 P024 最终问卷行缺少完整样式，这里与前一行对齐。
    for column in range(2, 12):
        records.cell(226, column)._style = copy(records.cell(225, column)._style)


def _repair_participant_validations(workbook: Any) -> None:
    """重建参与者背景、同意、安全与纳入字段的输入校验。"""

    participants = workbook["Participants"]
    participants.data_validations.dataValidation = []
    _add_whole_number_validation(participants, "L3:L26", 1, 120, allow_blank=True)
    _add_list_validation(participants, "M3:M26", '"女,男,非二元或其他,不愿透露"', allow_blank=True)
    _add_list_validation(participants, "N3:N26", '"右手,左手,双手均可"', allow_blank=True)
    _add_list_validation(participants, "O3:O26", '"正常,矫正后正常,其他"', allow_blank=True)
    _add_list_validation(participants, "P3:P26", '"从未,1–5 次,6–20 次,超过 20 次,经常使用"', allow_blank=True)
    _add_list_validation(participants, "Q3:Q26", '"从未,1–2 次,数次,经常"', allow_blank=True)
    for reference in ("R3:R26", "V3:V26"):
        _add_list_validation(participants, reference, '"是,否"', allow_blank=True)
    _add_list_validation(
        participants,
        "S3:S26",
        '"无,轻微,中等,明显,因不适中止"',
        allow_blank=True,
    )
    _add_list_validation(
        participants,
        "W3:W26",
        '"' + ",".join(EXCLUSION_REASONS) + '"',
        allow_blank=True,
    )


def _repair_records_validations(workbook: Any) -> None:
    """重建原始记录的输入校验，并允许冻结规则中的合法缺失。"""

    records = workbook["Records"]
    records.data_validations.dataValidation = []
    _add_whole_number_validation(records, "K5:M148", 1, 7, allow_blank=False)
    _add_whole_number_validation(records, "O5:X148", 1, 7, allow_blank=False)
    _add_whole_number_validation(records, "N5:N148", 1, 7, allow_blank=True)
    for range_reference in ("AB5:AD148", "AL5:AL148", "R152:R199", "X152:Y199"):
        _add_list_validation(records, range_reference, '"是,否"', allow_blank=False)
    _add_list_validation(
        records,
        "AE5:AE148",
        '"无,设备故障,网络故障,追踪异常,问卷中断,其他"',
        allow_blank=True,
    )
    _add_list_validation(
        records,
        "AK5:AK148",
        '"Coasting,FrozenUncertain,Lost,不适用"',
        allow_blank=True,
    )
    _add_list_validation(
        records,
        "V152:V199",
        '"无,设备故障,问卷中断,尺度误用,其他"',
        allow_blank=True,
    )
    _add_custom_scale_validation(records, "E152:N199", 1, 5)
    _add_custom_scale_validation(records, "O152:Q199", 1, 7)
    _add_list_validation(records, "B203:B226", '"方法A,方法B,无明显偏好"', allow_blank=False)
    _add_list_validation(records, "D203:D226", '"方法A,方法B,无明显偏好"', allow_blank=False)
    _add_list_validation(
        records,
        "H203:H226",
        '"无,轻微,中等,明显,因不适中止"',
        allow_blank=True,
    )
    _add_custom_na_validation(records, "C203:C226")
    _add_whole_number_validation(records, "E203:E226", 1, 7, allow_blank=False)
    _add_decimal_validation(records, "AF5:AF148", minimum=0.0, strict_minimum=True)
    for range_reference in ("AG5:AG148", "AH5:AH148", "AI5:AI148"):
        _add_decimal_validation(records, range_reference, minimum=0.0, maximum=1.0)
    _add_decimal_validation(records, "AJ5:AJ148", minimum=0.0, strict_minimum=True)
    for range_reference in ("AM5:AM148", "AN5:AN148"):
        _add_whole_number_validation(records, range_reference, 0, 1_000_000, allow_blank=True)


def _replace_formula_sheets(workbook: Any, settings: AnalysisSettings) -> None:
    """用正式实时派生表和分析面板替换旧的空回填壳。"""

    if "Derived" in workbook.sheetnames:
        workbook.remove(workbook["Derived"])
    analysis_index = workbook.sheetnames.index("Analysis")
    workbook.remove(workbook["Analysis"])
    derived = workbook.create_sheet("Derived", analysis_index)
    analysis = workbook.create_sheet("Analysis", analysis_index + 1)
    _build_derived_sheet(derived, settings)
    _build_analysis_sheet(analysis)


def _build_derived_sheet(worksheet: Any, settings: AnalysisSettings) -> None:
    """构建原始值到小分、参与者均值与配对差的透明公式链。"""

    _title_row(
        worksheet,
        1,
        26,
        "实时派生（仅公式）：区块与量表小分 → 三物体均值 → 跨物体与逐物体配对",
    )
    worksheet.merge_cells("A2:Z2")
    worksheet["A2"] = (
        "本表无需填写，也不是实施检查表。D1 计算区块与 AQ；D2 换向 TiA 并计算方法级小分；"
        "D3 形成每人每方法的三物体均值；D4 计算 EgoAnchor-One-Euro 配对差；"
        "D5 审计最终问卷；D6 派生论文参与者概况；D7 形成逐物体完整配对描述。"
        "正式分析不读取这些公式缓存。"
    )
    worksheet["A2"].font = Font(color="5B6570", italic=True, size=10)
    worksheet["A2"].alignment = Alignment(wrap_text=True, vertical="center")
    worksheet.row_dimensions[2].height = 34
    _section_row(worksheet, 3, 26, "D1. 区块级派生：144 行与 Records A 段逐行对应")
    d1_headers = (
        "Participant_ID", "Block_Index", "Condition", "Object_Key", "Valid_Block",
        "Q1", "Q8", "Q2", "Q9", "Q3", "Q6", "Q7", "AQ_EQ", "AQ_IQ", "Q10",
        "Duration_Over_150s", "Straightline_5Plus", "Candidate_Rate_Hz", "VCD_Median",
        "VCD_Admission_Rate", "Output_Availability", "Occlusion_Seconds", "Lifecycle_State",
        "Entered_Lost", "Reacquisition_Count", "StaticLock_Count",
    )
    _header_row(worksheet, 4, d1_headers)
    source_columns = {
        "Participant_ID": "A", "Block_Index": "B", "Condition": "H", "Object_Key": "F",
        **BLOCK_RECORD_COLUMNS,
        "Candidate_Rate_Hz": "AF", "VCD_Median": "AG",
        "VCD_Admission_Rate": "AH", "Output_Availability": "AI", "Occlusion_Seconds": "AJ",
        "Lifecycle_State": "AK", "Entered_Lost": "AL", "Reacquisition_Count": "AM", "StaticLock_Count": "AN",
    }
    required_items = required_block_items(settings.aq_mode)
    aq_items = aq_scale_items(settings.aq_mode)
    for derived_row, source_row in zip(range(5, 149), range(5, 149), strict=True):
        for column_index, header in enumerate(d1_headers, start=1):
            cell = worksheet.cell(derived_row, column_index)
            if header in source_columns:
                source_column = source_columns[header]
                cell.value = f'=IF(Records!{source_column}{source_row}="","",Records!{source_column}{source_row})'
            elif header == "Valid_Block":
                required_references = ",".join(
                    f"Records!{BLOCK_RECORD_COLUMNS[item]}{source_row}"
                    for item in required_items
                )
                cell.value = (
                    f'=IF(AND(COUNTIFS(Participants!$A$3:$A$26,Records!A{source_row},Participants!$V$3:$V$26,"是")=1,'
                    f'Records!AB{source_row}="是",Records!AC{source_row}="是",'
                    f'Records!AD{source_row}="是",'
                    f'COUNT({required_references})={len(required_items)}),"是","否")'
                )
            elif header in aq_items:
                references = tuple(
                    f"Records!{BLOCK_RECORD_COLUMNS[item]}{source_row}"
                    for item in aq_items[header]
                )
                cell.value = _complete_average_formula(references)
            elif header == "Duration_Over_150s":
                cell.value = f'=IF(Records!AA{source_row}="","",IF(Records!AA{source_row}>150,"是","否"))'
            elif header == "Straightline_5Plus":
                cell.value = _straightline_formula(source_row, required_items)
            _formula_style(cell)
            if header in {"Valid_Block", "Duration_Over_150s", "Straightline_5Plus"}:
                _status_formula_style(cell)

    _section_row(worksheet, 150, 21, "D2. 方法级派生：区分作答完成、记录有效与各分量表可计分")
    d2_headers = (
        "Participant_ID", "Condition", "Assessment_Complete", "Valid_Record",
        "TIA_RC1", "TIA_RC2", "TIA_RC3",
        "TIA_RC4", "TIA_RC5", "TIA_RC6", "TIA_UP1", "TIA_UP2", "TIA_UP3", "TIA_UP4",
        "STIAS1", "STIAS2", "STIAS3", "TIA_RC", "TIA_UP", "STIAS", "Duration_Seconds",
    )
    _header_row(worksheet, 151, d2_headers)
    for derived_row, source_row in zip(range(152, 200), range(152, 200), strict=True):
        worksheet.cell(derived_row, 1).value = f'=Records!A{source_row}'
        worksheet.cell(derived_row, 2).value = f'=Records!D{source_row}'
        worksheet.cell(derived_row, 3).value = (
            f'=IF(AND(COUNTA(Records!E{source_row}:Q{source_row})=13,'
            f'Records!R{source_row}="是"),"是","否")'
        )
        worksheet.cell(derived_row, 4).value = (
            f'=IF(AND(COUNTIFS(Participants!$A$3:$A$26,Records!A{source_row},Participants!$V$3:$V$26,"是")=1,'
            f'Records!R{source_row}="是",OR(Records!V{source_row}="",Records!V{source_row}="无"),'
            f'Records!X{source_row}="是",Records!Y{source_row}="是"),"是","否")'
        )
        for offset, (item, source_column) in enumerate(METHOD_RECORD_COLUMNS.items()):
            target = worksheet.cell(derived_row, 5 + offset)
            if item in REVERSED_TIA_ITEMS:
                target.value = f'=IF(ISNUMBER(Records!{source_column}{source_row}),6-Records!{source_column}{source_row},"")'
            else:
                target.value = f'=IF(ISNUMBER(Records!{source_column}{source_row}),Records!{source_column}{source_row},"")'
        worksheet.cell(derived_row, 18).value = f'=IF(COUNT(E{derived_row}:J{derived_row})>={settings.tia_rc_min_items},AVERAGE(E{derived_row}:J{derived_row}),"")'
        worksheet.cell(derived_row, 19).value = f'=IF(COUNT(K{derived_row}:N{derived_row})>={settings.tia_up_min_items},AVERAGE(K{derived_row}:N{derived_row}),"")'
        worksheet.cell(derived_row, 20).value = f'=IF(COUNT(O{derived_row}:Q{derived_row})>={settings.stias_min_items},AVERAGE(O{derived_row}:Q{derived_row}),"")'
        worksheet.cell(derived_row, 21).value = f'=IF(Records!U{source_row}="","",Records!U{source_row})'
        for column in range(1, 22):
            _formula_style(worksheet.cell(derived_row, column))
        _status_formula_style(worksheet.cell(derived_row, 3))
        _status_formula_style(worksheet.cell(derived_row, 4))

    _section_row(worksheet, 201, 21, "D3. 每人每方法：三个对象取均值；前 24 行 EgoAnchor，后 24 行 One-Euro")
    d3_headers = (
        "Participant_ID", "Condition", "Q1", "Q8", "Q2", "Q9", "Q3", "Q6", "Q7", "AQ_EQ",
        "AQ_IQ", "TIA_RC", "TIA_UP", "STIAS", "Q10", "Candidate_Rate_Hz", "VCD_Median",
        "VCD_Admission_Rate", "Output_Availability", "Occlusion_Seconds", "Valid_Objects",
    )
    _header_row(worksheet, 202, d3_headers)
    d1_columns = {
        "Q1": "F", "Q8": "G", "Q2": "H", "Q9": "I", "Q3": "J", "Q6": "K", "Q7": "L",
        "AQ_EQ": "M", "AQ_IQ": "N", "Q10": "O", "Candidate_Rate_Hz": "R", "VCD_Median": "S",
        "VCD_Admission_Rate": "T", "Output_Availability": "U", "Occlusion_Seconds": "V",
    }
    d2_columns = {"TIA_RC": "R", "TIA_UP": "S", "STIAS": "T"}
    for method_index, method in enumerate(("EgoAnchor", "One-Euro")):
        for participant_index in range(24):
            row = 203 + method_index * 24 + participant_index
            participant_row = 3 + participant_index
            worksheet.cell(row, 1).value = f'=Participants!A{participant_row}'
            worksheet.cell(row, 2).value = method
            for column_index, outcome in enumerate(d3_headers[2:20], start=3):
                if outcome in d1_columns:
                    source_column = d1_columns[outcome]
                    worksheet.cell(row, column_index).value = (
                        f'=IF(COUNTIFS($A$5:$A$148,$A{row},$C$5:$C$148,$B{row},$E$5:$E$148,"是",'
                        f'${source_column}$5:${source_column}$148,">=0")=3,AVERAGEIFS(${source_column}$5:${source_column}$148,'
                        f'$A$5:$A$148,$A{row},$C$5:$C$148,$B{row},$E$5:$E$148,"是"),"")'
                    )
                else:
                    source_column = d2_columns[outcome]
                    worksheet.cell(row, column_index).value = (
                        f'=IF(COUNTIFS($A$152:$A$199,$A{row},$B$152:$B$199,$B{row},$D$152:$D$199,"是",'
                        f'${source_column}$152:${source_column}$199,">=0")=1,AVERAGEIFS(${source_column}$152:${source_column}$199,'
                        f'$A$152:$A$199,$A{row},$B$152:$B$199,$B{row},$D$152:$D$199,"是"),"")'
                    )
            worksheet.cell(row, 21).value = f'=COUNTIFS($A$5:$A$148,$A{row},$C$5:$C$148,$B{row},$E$5:$E$148,"是")'
            for column in range(1, 22):
                _formula_style(worksheet.cell(row, column))

    _section_row(worksheet, 252, 13, "D4. 每人配对差：EgoAnchor − One-Euro；Participant_ID 校验应全部为 OK")
    d4_outcomes = (*PRIMARY_OUTCOMES, *SCALE_OUTCOMES)
    _header_row(worksheet, 253, ("Participant_ID", *d4_outcomes, "Pair_Check"))
    d3_outcome_columns = {header: get_column_letter(index) for index, header in enumerate(d3_headers, start=1)}
    for participant_index in range(24):
        row = 254 + participant_index
        ea_row = 203 + participant_index
        oe_row = 227 + participant_index
        worksheet.cell(row, 1).value = f'=A{ea_row}'
        for column_index, outcome in enumerate(d4_outcomes, start=2):
            source_column = d3_outcome_columns[outcome]
            worksheet.cell(row, column_index).value = (
                f'=IF(OR({source_column}{ea_row}="",{source_column}{oe_row}=""),"",{source_column}{ea_row}-{source_column}{oe_row})'
            )
        worksheet.cell(row, 14).value = f'=IF(A{ea_row}=A{oe_row},"OK","ERROR")'
        for column in range(1, 15):
            _formula_style(worksheet.cell(row, column))
        _status_formula_style(worksheet.cell(row, 14))

    _section_row(worksheet, 279, 5, "D5. 最终问卷派生：按 Participants 的纳入状态过滤")
    _header_row(
        worksheet,
        280,
        ("Participant_ID", "Included", "Preference_Strength", "Discrimination_Confidence", "Final_Complete"),
    )
    for participant_index in range(24):
        row = 281 + participant_index
        participant_row = 3 + participant_index
        final_row = 203 + participant_index
        worksheet.cell(row, 1).value = f'=Participants!A{participant_row}'
        worksheet.cell(row, 2).value = f'=IF(Participants!V{participant_row}="","",Participants!V{participant_row})'
        worksheet.cell(row, 3).value = (
            f'=IF(AND(B{row}="是",ISNUMBER(Records!C{final_row})),Records!C{final_row},"")'
        )
        worksheet.cell(row, 4).value = (
            f'=IF(AND(B{row}="是",ISNUMBER(Records!E{final_row})),Records!E{final_row},"")'
        )
        worksheet.cell(row, 5).value = _final_complete_formula(final_row, included_cell=f"B{row}")
        for column in range(1, 6):
            _formula_style(worksheet.cell(row, column))
        _status_formula_style(worksheet.cell(row, 2))
        _status_formula_style(worksheet.cell(row, 5))

    _section_row(worksheet, 307, 26, "D6. 参与者审计派生：分开记录施测完成与分析完整；不复制自由备注")
    d6_headers = (
        "Participant_ID", "Consented", "Started", "Completed_Session", "Analysis_Complete",
        "Included", "Age", "Gender", "Handedness", "Vision", "VRMR_Experience",
        "PhysicalMR_Experience", "Session_Duration_Min", "Valid_Blocks",
        "Completed_Method_Assessments", "Valid_Method_Records", "Final_Complete",
        "Exclusion_Reason", "Baseline_Discomfort", "End_Discomfort", "Object_Order",
        "Method_Sequence", "A_Mapping", "First_Method", "Discomfort_Change", "Audit_Status",
    )
    _header_row(worksheet, 308, d6_headers)
    severity_values = PARTICIPANT_CATEGORIES["End_Discomfort"]
    severity_array = "{" + ",".join(f'"{value}"' for value in severity_values) + "}"
    for participant_index in range(24):
        row = 309 + participant_index
        participant_row = 3 + participant_index
        final_row = 203 + participant_index
        worksheet.cell(row, 1).value = f'=Participants!A{participant_row}'
        worksheet.cell(row, 2).value = f'=IF(Participants!R{participant_row}="","",Participants!R{participant_row})'
        worksheet.cell(row, 3).value = f'=IF(Participants!T{participant_row}<>"","是","否")'
        worksheet.cell(row, 4).value = (
            f'=IF(AND(Participants!T{participant_row}<>"",Participants!U{participant_row}<>""),"是","否")'
        )
        worksheet.cell(row, 6).value = f'=IF(Participants!V{participant_row}="","",Participants!V{participant_row})'
        for column, source_column in enumerate(("L", "M", "N", "O", "P", "Q"), start=7):
            worksheet.cell(row, column).value = (
                f'=IF($F{row}="是",IF(Participants!{source_column}{participant_row}="","",'
                f'Participants!{source_column}{participant_row}),"")'
            )
        worksheet.cell(row, 13).value = (
            f'=IF(AND($F{row}="是",Participants!T{participant_row}<>"",Participants!U{participant_row}<>""),'
            f'IFERROR(MOD(Participants!U{participant_row}-Participants!T{participant_row},1)*1440,'
            f'IFERROR(MOD(TIMEVALUE(Participants!U{participant_row})-TIMEVALUE(Participants!T{participant_row}),1)*1440,"")),"")'
        )
        worksheet.cell(row, 14).value = f'=COUNTIFS($A$5:$A$148,$A{row},$E$5:$E$148,"是")'
        worksheet.cell(row, 15).value = f'=COUNTIFS($A$152:$A$199,$A{row},$C$152:$C$199,"是")'
        worksheet.cell(row, 16).value = f'=COUNTIFS($A$152:$A$199,$A{row},$D$152:$D$199,"是")'
        worksheet.cell(row, 17).value = _final_complete_formula(final_row)
        worksheet.cell(row, 5).value = (
            f'=IF(AND(F{row}="是",N{row}=6,O{row}=2,P{row}=2,Q{row}="是"),"是","否")'
        )
        worksheet.cell(row, 18).value = f'=IF(Participants!W{participant_row}="","",Participants!W{participant_row})'
        worksheet.cell(row, 19).value = (
            f'=IF(AND($B{row}="是",$C{row}="是"),'
            f'IF(Participants!S{participant_row}="","",Participants!S{participant_row}),"")'
        )
        worksheet.cell(row, 20).value = (
            f'=IF(AND($B{row}="是",$C{row}="是"),'
            f'IF(Records!H{final_row}="","",Records!H{final_row}),"")'
        )
        worksheet.cell(row, 21).value = f'=IF($F{row}="是",Participants!C{participant_row},"")'
        worksheet.cell(row, 22).value = f'=IF($F{row}="是",Participants!D{participant_row},"")'
        worksheet.cell(row, 23).value = f'=IF($F{row}="是",Participants!I{participant_row},"")'
        worksheet.cell(row, 24).value = f'=IF($F{row}="是",Participants!K{participant_row},"")'
        worksheet.cell(row, 25).value = (
            f'=IF(OR(S{row}="",T{row}=""),"",IF(MATCH(T{row},{severity_array},0)>'
            f'MATCH(S{row},{severity_array},0),"Worsened",IF(MATCH(T{row},{severity_array},0)<'
            f'MATCH(S{row},{severity_array},0),"Improved","Unchanged")))'
        )
        worksheet.cell(row, 26).value = (
            f'=IF(AND(B{row}="",COUNTA(Participants!L{participant_row}:X{participant_row})=0),"unused_slot",'
            f'IF(B{row}<>"是","not_consented",IF(F{row}="是",'
            f'IF(E{row}="是","included_complete","included_but_incomplete"),'
            f'IF(F{row}="否",IF(R{row}="","excluded_reason_missing","excluded"),"pending_review"))))'
        )
        for column in range(1, 27):
            _formula_style(worksheet.cell(row, column))
        for column in (2, 3, 4, 5, 6, 15, 16, 17, 25, 26):
            _status_formula_style(worksheet.cell(row, column))
        worksheet.cell(row, 7).number_format = "0"
        worksheet.cell(row, 13).number_format = "0.0"
        for column in (14, 15, 16):
            worksheet.cell(row, column).number_format = "0"

    _section_row(
        worksheet,
        334,
        24,
        "D7. 逐物体完整配对 helper：同一参与者在同一物体上的两方法均有效",
    )
    d7_value_headers = tuple(
        header
        for outcome in PRIMARY_OUTCOMES
        for header in (f"OE_{outcome}", f"EA_{outcome}", f"Diff_{outcome}")
    )
    _header_row(
        worksheet,
        335,
        ("Participant_ID", "Object_Key", "Pair_Valid", *d7_value_headers),
    )
    for object_index, object_key in enumerate(OBJECTS):
        for participant_index in range(24):
            row = 336 + object_index * 24 + participant_index
            participant_row = 3 + participant_index
            worksheet.cell(row, 1).value = f'=Participants!A{participant_row}'
            worksheet.cell(row, 2).value = object_key
            shared_criteria = (
                f'$A$5:$A$148,$A{row},$D$5:$D$148,$B{row},$E$5:$E$148,"是"'
            )
            worksheet.cell(row, 3).value = (
                f'=IF(AND(COUNTIFS({shared_criteria},$C$5:$C$148,"One-Euro")=1,'
                f'COUNTIFS({shared_criteria},$C$5:$C$148,"EgoAnchor")=1),"是","否")'
            )
            for outcome_index, outcome in enumerate(PRIMARY_OUTCOMES):
                source_column = d1_columns[outcome]
                oe_column = 4 + outcome_index * 3
                ea_column = oe_column + 1
                diff_column = oe_column + 2
                for method, target_column in (("One-Euro", oe_column), ("EgoAnchor", ea_column)):
                    worksheet.cell(row, target_column).value = (
                        f'=IF($C{row}<>"是","",AVERAGEIFS(${source_column}$5:${source_column}$148,'
                        f'{shared_criteria},$C$5:$C$148,"{method}"))'
                    )
                oe_cell = f"{get_column_letter(oe_column)}{row}"
                ea_cell = f"{get_column_letter(ea_column)}{row}"
                worksheet.cell(row, diff_column).value = (
                    f'=IF(OR({oe_cell}="",{ea_cell}=""),"",{ea_cell}-{oe_cell})'
                )
            for column in range(1, 25):
                _formula_style(worksheet.cell(row, column))
            _status_formula_style(worksheet.cell(row, 3))

    worksheet.freeze_panes = "A5"
    worksheet.auto_filter.ref = "A4:Z148"
    widths = {1: 15, 2: 13, 3: 13, 4: 15, 5: 12}
    for column in range(1, 27):
        worksheet.column_dimensions[get_column_letter(column)].width = widths.get(column, 14)
    worksheet.sheet_view.showGridLines = False
    worksheet.protection.sheet = True


def _build_analysis_sheet(worksheet: Any) -> None:
    """构建参与者汇报、完整性、实时描述与离线推断边界面板。"""

    _title_row(worksheet, 1, 20, "实验三实时数据检查与论文汇报概览")
    worksheet["A2"] = (
        "数据流：人工只填 Participants + Records → Derived 只读公式派生 → "
        "Analysis 绿色区现场描述 → pixi run eval analyze exp3 另写正式结果 XLSX。"
        "黄色区仅标识离线统计，本原始文件不会被 Python 回填。"
    )
    worksheet.merge_cells("A2:T2")
    worksheet["A2"].alignment = Alignment(wrap_text=True, vertical="center")
    worksheet["A2"].font = Font(color="5B6570", italic=True, size=10)
    worksheet.row_dimensions[2].height = 34
    _section_row(worksheet, 4, 20, "A. 样本流程、采集完整性与问卷负担")
    _header_row(worksheet, 5, ("检查项", "实时值", "目标/规则", "状态"))
    qc_rows = (
        ("已签署同意", '=COUNTIF(Derived!B309:B332,"是")', "样本流分母", '=IF(B6=0,"待招募","已记录")'),
        ("已开始会话", '=COUNTIFS(Derived!B309:B332,"是",Derived!C309:C332,"是")', "已同意者中的开始人数", '=IF(B7<=B6,"通过","检查")'),
        ("已完成会话", '=COUNTIFS(Derived!B309:B332,"是",Derived!D309:D332,"是")', "有开始和结束时间；不等同分析纳入", '=IF(B8<=B7,"通过","检查")'),
        ("确认纳入参与者", '=COUNTIFS(Derived!B309:B332,"是",Derived!F309:F332,"是")', "目标 24；硬下限 18", '=IF(B9>=24,"完成",IF(B9>=18,"可分析但未达目标","未达下限"))'),
        ("已排除/退出", '=COUNTIFS(Derived!B309:B332,"是",Derived!F309:F332,"否")', "必须记录冻结主原因", '=IF(COUNTIFS(Derived!F309:F332,"否",Derived!R309:R332,"")=0,"通过","原因缺失")'),
        ("待审核", '=COUNTIFS(Derived!B309:B332,"是",Derived!F309:F332,"")', "分析前必须清零", '=IF(B11=0,"通过","待处理")'),
        ("纳入者分析记录完整", '=COUNTIFS(Derived!F309:F332,"是",Derived!E309:E332,"是")', "每位纳入者均完整", '=IF(B12=B9,"通过","检查缺失或审核")'),
        ("有效区块", '=COUNTIF(Derived!E5:E148,"是")', "每位纳入者 6 个", '=IF(B13=B9*6,"通过","检查缺失或审核")'),
        ("有效方法级记录", '=COUNTIF(Derived!D152:D199,"是")', "每位纳入者 2 个；量表按各自阈值计分", '=IF(B14=B9*2,"通过","检查缺失或审核")'),
        ("最终问卷完整", '=COUNTIF(Derived!E281:E304,"是")', "含选择、跳题、开放题与安全检查", '=IF(B15=B9,"通过","检查缺失")'),
        ("有效区块中问卷 >150 s", '=IFERROR(COUNTIFS(Derived!E5:E148,"是",Derived!P5:P148,"是")/COUNTIF(Derived!E5:E148,"是"),"")', "预实验负担诊断", '=IF(B16="","待填",IF(B16>=0.2,"触发复核","未触发"))'),
        ("有效区块中 >=5 连续同分", '=IFERROR(COUNTIFS(Derived!E5:E148,"是",Derived!Q5:Q148,"是")/COUNTIF(Derived!E5:E148,"是"),"")', "预实验负担诊断", '=IF(B17="","待填",IF(B17>=0.05,"触发复核","未触发"))'),
    )
    for row_index, values in enumerate(qc_rows, start=6):
        for column_index, value in enumerate(values, start=1):
            worksheet.cell(row_index, column_index).value = value
            _formula_style(worksheet.cell(row_index, column_index))
    worksheet["B16"].number_format = "0.0%"
    worksheet["B17"].number_format = "0.0%"

    _section_row(worksheet, 19, 20, "B1. 参与者连续变量：仅纳入样本；论文数字以 Python 结果为准")
    _header_row(worksheet, 20, ("Metric", "N", "Missing", "Mean", "SD", "Median", "Q1", "Q3", "Min", "Max", "论文用途"))
    for row, (metric, column, role) in enumerate(
        (("Age", "G", "主文样本描述"), ("Session_Duration_Min", "M", "流程审计/补充材料")),
        start=21,
    ):
        value_range = f'Derived!{column}309:{column}332'
        formulas = (
            metric,
            f'=COUNT({value_range})',
            f'=$B$9-B{row}',
            f'=IF(B{row}=0,"",AVERAGE({value_range}))',
            f'=IF(B{row}<2,"",STDEV.S({value_range}))',
            f'=IF(B{row}=0,"",MEDIAN({value_range}))',
            _quartile_formula(f"B{row}", value_range, 1),
            _quartile_formula(f"B{row}", value_range, 3),
            f'=IF(B{row}=0,"",MIN({value_range}))',
            f'=IF(B{row}=0,"",MAX({value_range}))',
            role,
        )
        for column_index, value in enumerate(formulas, start=1):
            worksheet.cell(row, column_index).value = value
            _formula_style(worksheet.cell(row, column_index))

    _section_row(
        worksheet,
        25,
        20,
        "B2. 参与者与安全分类分布：人口学分母为纳入 N，安全分母为已同意且已开始 N",
    )
    _header_row(worksheet, 26, ("Variable", "Category", "Count", "Percent", "Missing_N", "Denominator"))
    category_columns = {
        "Gender": "H", "Handedness": "I", "Vision": "J", "VRMR_Experience": "K",
        "PhysicalMR_Experience": "L", "Baseline_Discomfort": "S", "End_Discomfort": "T",
    }
    category_row = 27
    for variable, column in category_columns.items():
        first_category_row = category_row
        denominator = "$B$7" if "Discomfort" in variable else "$B$9"
        for category in PARTICIPANT_CATEGORIES[variable]:
            value_range = f'Derived!${column}$309:${column}$332'
            worksheet.cell(category_row, 1).value = variable
            worksheet.cell(category_row, 2).value = category
            worksheet.cell(category_row, 3).value = f'=COUNTIF({value_range},B{category_row})'
            worksheet.cell(category_row, 4).value = f'=IF({denominator}=0,"",C{category_row}/{denominator})'
            worksheet.cell(category_row, 6).value = f'={denominator}'
            for column_index in range(1, 7):
                _formula_style(worksheet.cell(category_row, column_index))
            worksheet.cell(category_row, 4).number_format = "0.0%"
            category_row += 1
        last_category_row = category_row - 1
        for row in range(first_category_row, category_row):
            worksheet.cell(row, 5).value = (
                f'={denominator}-SUM($C${first_category_row}:$C${last_category_row})'
            )
    worksheet.cell(56, 1).value = "Discomfort_Change"
    worksheet.cell(56, 2).value = "Worsened"
    worksheet.cell(56, 3).value = '=COUNTIF(Derived!$Y$309:$Y$332,"Worsened")'
    worksheet.cell(56, 6).value = (
        '=COUNTIF(Derived!$Y$309:$Y$332,"Worsened")+'
        'COUNTIF(Derived!$Y$309:$Y$332,"Improved")+'
        'COUNTIF(Derived!$Y$309:$Y$332,"Unchanged")'
    )
    worksheet.cell(56, 4).value = '=IF(F56=0,"",C56/F56)'
    worksheet.cell(56, 5).value = '=$B$7-F56'
    for column_index in range(1, 7):
        _formula_style(worksheet.cell(56, column_index))
    worksheet.cell(56, 4).number_format = "0.0%"

    _section_row(worksheet, 58, 20, "B3. 顺序与标签平衡：只计算纳入样本")
    _header_row(
        worksheet,
        59,
        (
            "Factor", "Level", "N", "Expected_at_N24", "Expected_at_Actual_N",
            "Deviation_From_Actual_Balance", "Status",
        ),
    )
    balance_factors = (
        ("Object_Order", "U", (1, 2, 3, 4, 5, 6), 4),
        ("Method_Sequence", "V", ("S1", "S2"), 12),
        ("A_Mapping", "W", ("EgoAnchor", "One-Euro"), 12),
        ("First_Method", "X", ("EgoAnchor", "One-Euro"), 12),
    )
    balance_row = 60
    for factor, column, levels, expected in balance_factors:
        for level in levels:
            worksheet.cell(balance_row, 1).value = factor
            worksheet.cell(balance_row, 2).value = level
            worksheet.cell(balance_row, 3).value = f'=COUNTIF(Derived!${column}$309:${column}$332,B{balance_row})'
            worksheet.cell(balance_row, 4).value = expected
            worksheet.cell(balance_row, 5).value = f'=IF($B$9=0,"",$B$9/{len(levels)})'
            worksheet.cell(balance_row, 6).value = f'=IF(E{balance_row}="","",C{balance_row}-E{balance_row})'
            worksheet.cell(balance_row, 7).value = (
                f'=IF(E{balance_row}="","待填",IF(ABS(F{balance_row})<0.000000001,"平衡","检查"))'
            )
            for column_index in range(1, 8):
                _formula_style(worksheet.cell(balance_row, column_index))
            balance_row += 1

    main_start = 75
    _section_row(worksheet, main_start, 20, "C1. 主证实家族：三物体均值后的完整配对统计")
    result_headers = (
        "Outcome", "简称", "N", "OE_Q1", "OE_Median", "OE_Q3", "EA_Q1", "EA_Median", "EA_Q3",
        "Diff_Median", "Diff_Mean", "Diff_SD", "dz", "W", "p_raw", "p_Holm", "r_rb", "r_CI_Low",
        "r_CI_High", "结论",
    )
    _header_row(worksheet, main_start + 1, result_headers)
    d3_columns = {
        "Q1": "C", "Q8": "D", "Q2": "E", "Q9": "F", "Q3": "G", "Q6": "H", "Q7": "I",
        "AQ_EQ": "J", "AQ_IQ": "K", "TIA_RC": "L", "TIA_UP": "M", "STIAS": "N",
    }
    d4_columns = {
        outcome: get_column_letter(index)
        for index, outcome in enumerate((*PRIMARY_OUTCOMES, *SCALE_OUTCOMES), start=2)
    }
    for row, outcome in enumerate(PRIMARY_OUTCOMES, start=main_start + 2):
        _analysis_result_row(worksheet, row, outcome, d3_columns[outcome], d4_columns[outcome])

    object_start = 86
    _section_row(
        worksheet,
        object_start,
        20,
        "C2. 主证实家族的逐物体完整配对描述：供论文分面图和方向核查使用；主检验见 C1",
    )
    object_headers = (
        "Outcome", "简称", "Object", "N_pair", "OE_Q1", "OE_Median", "OE_Q3",
        "EA_Q1", "EA_Median", "EA_Q3", "Diff_Median", "Diff_Mean", "Diff_SD",
        "dz（描述性）",
    )
    _header_row(worksheet, object_start + 1, object_headers)
    d7_columns = {
        outcome: (
            get_column_letter(4 + outcome_index * 3),
            get_column_letter(5 + outcome_index * 3),
            get_column_letter(6 + outcome_index * 3),
        )
        for outcome_index, outcome in enumerate(PRIMARY_OUTCOMES)
    }
    object_ranges = {
        object_key: (336 + object_index * 24, 359 + object_index * 24)
        for object_index, object_key in enumerate(OBJECTS)
    }
    object_row = object_start + 2
    for outcome in PRIMARY_OUTCOMES:
        for object_key in OBJECTS:
            _analysis_object_result_row(
                worksheet,
                object_row,
                outcome,
                OBJECT_LABELS[object_key],
                d7_columns[outcome],
                object_ranges[object_key],
            )
            object_row += 1

    scale_start = 111
    _section_row(worksheet, scale_start, 20, "D. 已发表量表家族：当前样本信度由 Python 另行报告")
    _header_row(worksheet, scale_start + 1, result_headers)
    for row, outcome in enumerate(SCALE_OUTCOMES, start=scale_start + 2):
        _analysis_result_row(worksheet, row, outcome, d3_columns[outcome], d4_columns[outcome])

    manipulation_start = 120
    _section_row(worksheet, manipulation_start, 20, "E. 操纵与运行时描述：每位参与者先在三个物体上取均值")
    _header_row(worksheet, manipulation_start + 1, ("Metric", "N", "One-Euro Mean", "EgoAnchor Mean", "Difference Mean", "TOST Margin", "p_TOST", "Status"))
    manipulation_columns = {
        "Candidate_Rate_Hz": "P", "VCD_Median": "Q", "VCD_Admission_Rate": "R",
        "Output_Availability": "S", "Occlusion_Seconds": "T",
    }
    for row, (metric, column) in enumerate(manipulation_columns.items(), start=manipulation_start + 2):
        ea_range = f'Derived!{column}203:{column}226'
        oe_range = f'Derived!{column}227:{column}250'
        pair_mask = f'({ea_range}<>"")*({oe_range}<>"")'
        worksheet.cell(row, 1).value = metric
        worksheet.cell(row, 2).value = f'=SUMPRODUCT(--({ea_range}<>""),--({oe_range}<>""))'
        worksheet.cell(row, 3).value = f'=IF(B{row}=0,"",AVERAGE(FILTER({oe_range},{pair_mask})))'
        worksheet.cell(row, 4).value = f'=IF(B{row}=0,"",AVERAGE(FILTER({ea_range},{pair_mask})))'
        worksheet.cell(row, 5).value = f'=IF(B{row}=0,"",D{row}-C{row})'
        for column_index in range(1, 6):
            _formula_style(worksheet.cell(row, column_index))
        for column_index in range(6, 9):
            _offline_style(worksheet.cell(row, column_index))

    choice_start = 129
    _section_row(worksheet, choice_start, 20, "F. 最终描述测量")
    _header_row(worksheet, choice_start + 1, ("Measure", "Count", "Median", "Q1", "Q3", "Mean", "SD"))
    final_metrics = (
        ("Preference_Strength", "C"),
        ("Discrimination_Confidence", "D"),
    )
    for row, (metric, column) in enumerate(final_metrics, start=choice_start + 2):
        value_range = f'Derived!{column}281:{column}304'
        worksheet.cell(row, 1).value = metric
        worksheet.cell(row, 2).value = f'=COUNT({value_range})'
        worksheet.cell(row, 3).value = f'=IF(B{row}=0,"",MEDIAN({value_range}))'
        worksheet.cell(row, 4).value = _quartile_formula(f"B{row}", value_range, 1)
        worksheet.cell(row, 5).value = _quartile_formula(f"B{row}", value_range, 3)
        worksheet.cell(row, 6).value = f'=IF(B{row}=0,"",AVERAGE({value_range}))'
        worksheet.cell(row, 7).value = f'=IF(B{row}<2,"",STDEV.S({value_range}))'
        for column_index in range(1, 8):
            _formula_style(worksheet.cell(row, column_index))

    worksheet.freeze_panes = "C21"
    worksheet.sheet_view.showGridLines = False
    widths = (18, 28, 10, 11, 12, 11, 11, 12, 11, 13, 12, 11, 10, 10, 11, 11, 10, 11, 12, 20)
    for index, width in enumerate(widths, start=1):
        worksheet.column_dimensions[get_column_letter(index)].width = width
    worksheet.auto_filter.ref = "A76:T83"
    worksheet.conditional_formatting.add(
        "D6:D17",
        FormulaRule(
            formula=['OR(D6="未达下限",D6="检查缺失或审核",D6="检查缺失",D6="检查",D6="原因缺失",D6="待处理")'],
            fill=PatternFill("solid", fgColor=_PALE_RED),
        ),
    )
    worksheet.protection.sheet = True


def _analysis_result_row(
    worksheet: Any,
    row: int,
    outcome: str,
    d3_column: str,
    d4_column: str,
) -> None:
    """写一行与 Python ``paired_result`` 定义完全一致的实时公式。"""

    ea_range = f'Derived!${d3_column}$203:${d3_column}$226'
    oe_range = f'Derived!${d3_column}$227:${d3_column}$250'
    diff_range = f'Derived!${d4_column}$254:${d4_column}$277'
    paired_ea = f'FILTER({ea_range},{diff_range}<>"")'
    paired_oe = f'FILTER({oe_range},{diff_range}<>"")'
    formulas = (
        outcome,
        OUTCOME_LABELS[outcome],
        f'=COUNT({diff_range})',
        _quartile_formula(f"C{row}", paired_oe, 1),
        f'=IF(C{row}=0,"",MEDIAN({paired_oe}))',
        _quartile_formula(f"C{row}", paired_oe, 3),
        _quartile_formula(f"C{row}", paired_ea, 1),
        f'=IF(C{row}=0,"",MEDIAN({paired_ea}))',
        _quartile_formula(f"C{row}", paired_ea, 3),
        f'=IF(C{row}=0,"",MEDIAN({diff_range}))',
        f'=IF(C{row}=0,"",AVERAGE({diff_range}))',
        f'=IF(C{row}<2,"",STDEV.S({diff_range}))',
        f'=IF(OR(C{row}<2,L{row}=0),"",K{row}/L{row})',
    )
    for column_index, value in enumerate(formulas, start=1):
        worksheet.cell(row, column_index).value = value
        _formula_style(worksheet.cell(row, column_index))
    for column_index in range(14, 21):
        _offline_style(worksheet.cell(row, column_index))


def _analysis_object_result_row(
    worksheet: Any,
    row: int,
    outcome: str,
    object_label: str,
    d7_columns: tuple[str, str, str],
    d7_rows: tuple[int, int],
) -> None:
    """写一行逐物体完整配对描述，不生成额外证实检验。"""

    start_row, end_row = d7_rows
    oe_column, ea_column, diff_column = d7_columns
    oe_range = f'Derived!${oe_column}${start_row}:${oe_column}${end_row}'
    ea_range = f'Derived!${ea_column}${start_row}:${ea_column}${end_row}'
    diff_range = f'Derived!${diff_column}${start_row}:${diff_column}${end_row}'
    formulas = (
        outcome,
        OUTCOME_LABELS[outcome],
        object_label,
        f'=COUNT({diff_range})',
        _quartile_formula(f"D{row}", oe_range, 1),
        f'=IF(D{row}=0,"",MEDIAN({oe_range}))',
        _quartile_formula(f"D{row}", oe_range, 3),
        _quartile_formula(f"D{row}", ea_range, 1),
        f'=IF(D{row}=0,"",MEDIAN({ea_range}))',
        _quartile_formula(f"D{row}", ea_range, 3),
        f'=IF(D{row}=0,"",MEDIAN({diff_range}))',
        f'=IF(D{row}=0,"",AVERAGE({diff_range}))',
        f'=IF(D{row}<2,"",STDEV.S({diff_range}))',
        f'=IF(OR(D{row}<2,M{row}=0),"",L{row}/M{row})',
    )
    for column_index, value in enumerate(formulas, start=1):
        worksheet.cell(row, column_index).value = value
        _formula_style(worksheet.cell(row, column_index))


def _final_complete_formula(final_row: int, *, included_cell: str | None = None) -> str:
    """返回最终问卷完整性公式，可选按纳入状态隐藏结果。"""

    complete = (
        f'IF(AND(Records!B{final_row}<>"",Records!D{final_row}<>"",'
        f'ISNUMBER(Records!E{final_row}),Records!F{final_row}<>"",Records!G{final_row}<>"",'
        f'Records!H{final_row}<>"",OR(AND(Records!B{final_row}="无明显偏好",'
        f'OR(Records!C{final_row}="",Records!C{final_row}="N/A")),AND(Records!B{final_row}<>"无明显偏好",'
        f'ISNUMBER(Records!C{final_row}),Records!C{final_row}>=1,Records!C{final_row}<=7))),"是","否")'
    )
    if included_cell is None:
        return f"={complete}"
    return f'=IF({included_cell}<>"是","",{complete})'


def _complete_average_formula(references: tuple[str, ...]) -> str:
    """返回只有全部条目有数值时才计算均值的公式。"""

    arguments = ",".join(references)
    return f'=IF(COUNT({arguments})={len(references)},AVERAGE({arguments}),"")'


def _quartile_formula(count_cell: str, value_range: str, quartile: int) -> str:
    """生成 Excel/WPS 通用的 inclusive 四分位数公式。"""

    # 兼容函数 QUARTILE 与 QUARTILE.INC 的算法相同；WPS 不识别后者。
    return f'=IF({count_cell}=0,"",QUARTILE({value_range},{quartile}))'


def _straightline_formula(source_row: int, items: tuple[str, ...]) -> str:
    """返回当前冻结问卷条目上的五项连续同分门禁公式。"""

    columns = tuple(BLOCK_RECORD_COLUMNS[item] for item in items)
    windows = []
    for start in range(len(columns) - 4):
        window = columns[start : start + 5]
        equality = ",".join(
            f'Records!{left}{source_row}=Records!{right}{source_row}'
            for left, right in zip(window, window[1:])
        )
        windows.append(f"AND({equality})")
    return (
        f'=IF(COUNT({",".join(f"Records!{column}{source_row}" for column in columns)})<{len(columns)},"",'
        f'IF(OR({",".join(windows)}),"是","否"))'
    )


def _title_row(worksheet: Any, row: int, last_column: int, text: str) -> None:
    """写深色首行标题。"""

    worksheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=last_column)
    cell = worksheet.cell(row, 1, text)
    cell.fill = PatternFill("solid", fgColor=_NAVY)
    cell.font = Font(color=_WHITE, bold=True, size=15)
    cell.alignment = Alignment(vertical="center")
    worksheet.row_dimensions[row].height = 28


def _section_row(worksheet: Any, row: int, last_column: int, text: str) -> None:
    """写青绿色分节标题。"""

    worksheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=last_column)
    cell = worksheet.cell(row, 1, text)
    cell.fill = PatternFill("solid", fgColor=_TEAL)
    cell.font = Font(color=_WHITE, bold=True, size=11)
    cell.alignment = Alignment(vertical="center")
    worksheet.row_dimensions[row].height = 23


def _header_row(worksheet: Any, row: int, headers: tuple[str, ...]) -> None:
    """写浅蓝色表头并设置自动换行。"""

    for column, header in enumerate(headers, start=1):
        cell = worksheet.cell(row, column, header)
        cell.fill = PatternFill("solid", fgColor=_PALE_BLUE)
        cell.font = Font(color=_TEXT, bold=True, size=10)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = _thin_border()
    worksheet.row_dimensions[row].height = 30


def _formula_style(cell: Any) -> None:
    """设置实时公式区域的绿色底纹。"""

    cell.fill = PatternFill("solid", fgColor=_GREEN)
    cell.font = Font(color=_TEXT, size=10)
    cell.alignment = Alignment(vertical="center", wrap_text=False)
    cell.border = _thin_border()
    if cell.column >= 3:
        cell.number_format = "0.000"


def _status_formula_style(cell: Any) -> None:
    """用浅黄将完整性和审计状态与数值派生分开。"""

    cell.fill = PatternFill("solid", fgColor=_YELLOW)
    cell.font = Font(color=_TEXT, size=10)
    cell.alignment = Alignment(vertical="center", wrap_text=True)
    cell.border = _thin_border()
    cell.number_format = "General"


def _offline_style(cell: Any) -> None:
    """设置 Python 离线推断列的黄色占位底纹。"""

    cell.fill = PatternFill("solid", fgColor=_YELLOW)
    cell.font = Font(color=_TEXT, size=10)
    cell.alignment = Alignment(vertical="center", wrap_text=True)
    cell.border = _thin_border()
    cell.number_format = "0.0000"


def _thin_border() -> Border:
    """返回统一的浅灰细边框。"""

    side = Side(style="thin", color=_GRID)
    return Border(left=side, right=side, top=side, bottom=side)


def _add_whole_number_validation(
    worksheet: Any,
    range_reference: str,
    minimum: int,
    maximum: int,
    *,
    allow_blank: bool,
) -> None:
    """添加整数刻度输入校验。"""

    validation = DataValidation(
        type="whole",
        operator="between",
        formula1=str(minimum),
        formula2=str(maximum),
        allow_blank=allow_blank,
    )
    validation.error = f"请输入 {minimum}–{maximum} 的整数" + ("，或留空" if allow_blank else "")
    validation.errorTitle = "评分范围错误"
    validation.showErrorMessage = True
    worksheet.add_data_validation(validation)
    validation.add(range_reference)


def _add_list_validation(
    worksheet: Any,
    range_reference: str,
    formula: str,
    *,
    allow_blank: bool,
) -> None:
    """添加有限选项下拉校验。"""

    validation = DataValidation(type="list", formula1=formula, allow_blank=allow_blank)
    validation.error = "请从下拉列表中选择"
    validation.errorTitle = "选项错误"
    validation.showErrorMessage = True
    worksheet.add_data_validation(validation)
    validation.add(range_reference)


def _add_decimal_validation(
    worksheet: Any,
    range_reference: str,
    *,
    minimum: float,
    maximum: float | None = None,
    strict_minimum: bool = False,
) -> None:
    """添加允许暂时留空的有限小数范围校验。"""

    first = range_reference.split(":", maxsplit=1)[0]
    lower = ">" if strict_minimum else ">="
    conditions = [f"ISNUMBER({first})", f"{first}{lower}{minimum:g}"]
    if maximum is not None:
        conditions.append(f"{first}<={maximum:g}")
    formula = f'=OR({first}="",AND({",".join(conditions)}))'
    validation = DataValidation(type="custom", formula1=formula, allow_blank=True)
    upper_text = f" 且不超过 {maximum:g}" if maximum is not None else ""
    validation.error = f"请输入大于{' ' if strict_minimum else '等于 '} {minimum:g}{upper_text} 的数值，或暂时留空"
    validation.errorTitle = "数值范围错误"
    validation.showErrorMessage = True
    worksheet.add_data_validation(validation)
    validation.add(range_reference)


def _add_custom_scale_validation(
    worksheet: Any,
    range_reference: str,
    minimum: int,
    maximum: int,
) -> None:
    """允许整数评分、空白或“无法回答”。"""

    first = range_reference.split(":", maxsplit=1)[0]
    formula = f'=OR({first}="",{first}="无法回答",AND(ISNUMBER({first}),{first}>={minimum},{first}<={maximum},MOD({first},1)=0))'
    validation = DataValidation(type="custom", formula1=formula, allow_blank=True)
    validation.error = f"请输入 {minimum}–{maximum} 的整数、无法回答，或留空"
    validation.errorTitle = "评分范围错误"
    validation.showErrorMessage = True
    worksheet.add_data_validation(validation)
    validation.add(range_reference)


def _add_custom_na_validation(worksheet: Any, range_reference: str) -> None:
    """允许偏好强度 1–7、N/A 或空白。"""

    first = range_reference.split(":", maxsplit=1)[0]
    formula = f'=OR({first}="",{first}="N/A",AND(ISNUMBER({first}),{first}>=1,{first}<=7,MOD({first},1)=0))'
    validation = DataValidation(type="custom", formula1=formula, allow_blank=True)
    validation.error = "请输入 1–7 的整数；无明显偏好时填 N/A 或留空"
    validation.errorTitle = "偏好强度错误"
    validation.showErrorMessage = True
    worksheet.add_data_validation(validation)
    validation.add(range_reference)


def _enable_recalculation(workbook: Any) -> None:
    """要求 Excel 打开时完整重算所有实时公式。"""

    workbook.calculation.calcMode = "auto"
    workbook.calculation.fullCalcOnLoad = True
    workbook.calculation.forceFullCalc = True


__all__ = ["build_raw_template"]

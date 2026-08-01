"""实验三三段堆叠原始工作簿的严格只读 reader。"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable
from datetime import datetime, time
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl import load_workbook  # type: ignore[import-untyped]
from openpyxl.cell.cell import Cell  # type: ignore[import-untyped]

from .contracts import (
    BLOCK_ITEMS,
    EGOANCHOR,
    EXCLUSION_REASONS,
    Exp3Data,
    METHOD_ITEM_COLUMNS,
    METHODS,
    OBJECTS,
    ONE_EURO,
    PARTICIPANT_BACKGROUND_COLUMNS,
    PARTICIPANT_CATEGORIES,
    WORKBOOK_CONTRACT_ID,
    WORKBOOK_SOURCE_CATEGORY,
    required_block_items,
)


_REQUIRED_SHEETS = frozenset({"README", "Participants", "Records"})
"""分析输入必须包含的最小工作表集合。"""

_KNOWN_SYNTHETIC_RESPONSE_FINGERPRINTS = frozenset(
    {"5993ef77a827eb89c99fb9c1db85f29ae09d1a2f423f88f2713b6fa3789fe84a"}
)
"""已逐格审计并确认的合成身份与核心响应指纹。"""

_PARTICIPANT_DESIGN_COLUMNS = (
    "Participant_ID",
    "平衡单元",
    "物体排列ID",
    "标签序列",
    "物体1",
    "物体2",
    "物体3",
    "区块内标签顺序",
    "方法A=（保密）",
    "方法B=（保密）",
    "先行实际方法",
)
"""24 平衡单元不得缺失或被公式替换的设计列。"""

_BLOCK_DESIGN_COLUMNS = (
    "Participant_ID",
    "Block_Index",
    "平衡单元",
    "物体位置",
    "物体",
    "Object_Key",
    "Shown_Label",
    "Condition(保密)",
    "物体内先后",
    "该方法第几次",
)
"""Records A 段的固定设计列。"""

_METHOD_DESIGN_COLUMNS = (
    "Participant_ID",
    "Rating_Order",
    "Shown_Label",
    "Condition(保密)",
)
"""Records B 段的固定设计列。"""

_BLOCK_FINGERPRINT_COLUMNS = _BLOCK_DESIGN_COLUMNS + tuple(BLOCK_ITEMS.values())
"""区块段参与者/条件身份与十四个核心评分，共 144×24 个单元格。"""

_METHOD_FINGERPRINT_COLUMNS = (
    _METHOD_DESIGN_COLUMNS + tuple(METHOD_ITEM_COLUMNS) + ("尺度切换确认",)
)
"""方法段参与者/条件身份、十三个量表响应与尺度确认，共 48×18 个单元格。"""

_FINAL_FINGERPRINT_COLUMNS = (
    "Participant_ID",
    "方法选择(标签)",
    "偏好强度(1-7/NA)",
    "信任选择(标签)",
    "区分信心(1-7)",
    "开放:最明显区别",
    "开放:最破坏信任的现象",
    "结束不适",
    "方法选择(解码)",
    "信任选择(解码)",
)
"""最终段除访谈备注外的身份与核心响应，共 24×10 个单元格。"""


def workbook_sha256(path: Path) -> str:
    """返回原始工作簿的 SHA-256。"""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def read_workbook(path: Path) -> Exp3Data:
    """按值读取 Participants 与 Records 三段，并验证结构身份。"""

    source = path.expanduser().resolve()
    if source.suffix.lower() != ".xlsx" or not source.is_file():
        raise FileNotFoundError(f"实验三输入必须是现存 XLSX：{source}")
    workbook = load_workbook(source, read_only=True, data_only=False)
    try:
        missing = _REQUIRED_SHEETS.difference(workbook.sheetnames)
        if missing:
            raise ValueError(f"实验三工作簿缺少工作表：{sorted(missing)}")
        participants = _read_table(workbook["Participants"], 2, 3, 26)
        records = workbook["Records"]
        block_header = _find_header_after(records, "A. 区块记录")
        method_header = _find_header_after(records, "B. 方法级记录")
        final_header = _find_header_after(records, "C. 最终问卷记录")
        blocks = _read_table(records, block_header, block_header + 1, method_header - 2)
        methods = _read_table(records, method_header, method_header + 1, final_header - 2)
        finals = _read_table(records, final_header, final_header + 1, final_header + 24)
        source_kind = _source_kind(workbook, source.name)
    finally:
        workbook.close()
    data = Exp3Data(
        participants=participants,
        blocks=blocks,
        methods=methods,
        finals=finals,
        source_kind=source_kind,
        source_path=str(source),
        source_sha256=workbook_sha256(source),
    )
    _validate_structure(data)
    return data


def validate_for_analysis(
    data: Exp3Data,
    *,
    minimum_participants: int,
    aq_mode: str,
    q10_enabled: bool,
    approved_response_fingerprints: frozenset[str],
    allow_synthetic: bool = False,
) -> dict[str, Any]:
    """检查采集完成状态、合法值和正式来源边界。"""

    if data.source_kind != "formal":
        if data.source_kind != "synthetic" or not allow_synthetic:
            raise ValueError("输入缺少正式工作簿契约标识，或属于合成/模拟数据")
    participants = data.participants.copy()
    included = participants[participants["纳入分析"].map(_is_yes)]
    included_ids = frozenset(included["Participant_ID"].astype(str))
    safety_ids = frozenset(
        participants.loc[
            participants["签署同意"].map(_is_yes)
            & ~participants["开始时间"].map(_is_missing_or_na),
            "Participant_ID",
        ].astype(str)
    )
    warnings: list[str] = []
    response_fingerprint = _response_fingerprint(data)
    paper_eligible, source_gate_reason = _source_gate_result(
        source_kind=data.source_kind,
        response_fingerprint=response_fingerprint,
        approved_response_fingerprints=approved_response_fingerprints,
    )
    if not paper_eligible:
        warnings.append(source_gate_reason)
    if len(included_ids) < minimum_participants:
        raise ValueError(
            f"纳入分析且已确认的参与者只有 {len(included_ids)} 人，少于冻结下限 {minimum_participants}"
        )
    _validate_participant_values(
        data.participants,
        included_ids,
        require_complete=data.source_kind == "formal",
    )
    _validate_block_values(
        data.blocks,
        included_ids,
        aq_mode=aq_mode,
        q10_enabled=q10_enabled,
    )
    _validate_method_values(
        data.methods,
        included_ids,
        require_complete=data.source_kind == "formal",
    )
    _validate_final_values(
        data.finals,
        included_ids,
        safety_ids,
        require_complete=data.source_kind == "formal",
    )
    if len(included_ids) < 24:
        warnings.append(f"当前纳入 {len(included_ids)} 人，少于目标 N=24；结果按实际配对 N 报告")
    return {
        "included_participants": tuple(sorted(included_ids)),
        "included_count": len(included_ids),
        "warnings": tuple(warnings),
        "source_kind": data.source_kind,
        "response_fingerprint": response_fingerprint,
        "paper_eligible": paper_eligible,
        "source_gate_reason": source_gate_reason,
    }


def describe_workbook(data: Exp3Data) -> dict[str, Any]:
    """返回不要求采集完成的结构与填表进度摘要。"""

    participants = data.participants
    blocks = data.blocks
    methods = data.methods
    finals = data.finals
    return {
        "passed": True,
        "source": data.source_path,
        "source_sha256": data.source_sha256,
        "source_kind": data.source_kind,
        "participant_rows": len(participants),
        "included_confirmed": int(participants["纳入分析"].map(_is_yes).sum()),
        "block_rows": len(blocks),
        "block_scores_filled": int(blocks[list(BLOCK_ITEMS.values())].notna().sum().sum()),
        "method_rows": len(methods),
        "method_scores_filled": int(methods[list(METHOD_ITEM_COLUMNS)].notna().sum().sum()),
        "final_rows": len(finals),
        "final_choices_filled": int(finals["方法选择(标签)"].notna().sum()),
    }


def _read_table(worksheet: Any, header_row: int, first_row: int, last_row: int) -> pd.DataFrame:
    """按指定表头和行边界读取一张普通值表。"""

    header_cells = next(
        worksheet.iter_rows(
            min_row=header_row,
            max_row=header_row,
            min_col=1,
            max_col=worksheet.max_column,
        )
    )
    headers = [cell.value for cell in header_cells]
    while headers and headers[-1] is None:
        headers.pop()
    if not headers or any(value is None for value in headers):
        raise ValueError(f"{worksheet.title}!{header_row} 表头包含空列")
    rows: list[dict[str, Any]] = []
    for row_number, cells in enumerate(
        worksheet.iter_rows(
            min_row=first_row,
            max_row=last_row,
            min_col=1,
            max_col=len(headers),
        ),
        start=first_row,
    ):
        if all(cell.value is None for cell in cells):
            continue
        _reject_formulas(worksheet.title, row_number, cells)
        rows.append({str(header): cell.value for header, cell in zip(headers, cells, strict=True)})
    return pd.DataFrame(rows, columns=[str(value) for value in headers])


def _reject_formulas(sheet_name: str, row_number: int, cells: Iterable[Cell]) -> None:
    """拒绝在原始值区域放入公式，避免评分来源被派生值覆盖。"""

    for cell in cells:
        if cell.data_type == "f":
            raise ValueError(f"原始数据区域不得含公式：{sheet_name}!{cell.coordinate}（第 {row_number} 行）")


def _find_header_after(worksheet: Any, marker: str) -> int:
    """按 A 列节标题定位其下一行表头。"""

    for row_number, (cell,) in enumerate(
        worksheet.iter_rows(min_col=1, max_col=1),
        start=1,
    ):
        value = cell.value
        if isinstance(value, str) and value.startswith(marker):
            return row_number + 1
    raise ValueError(f"Records 缺少节标题：{marker}")


def _source_kind(workbook: Any, filename: str) -> str:
    """优先按工作表契约识别正式输入，兼容 Excel 丢弃核心属性。"""

    readme = workbook["README"]
    rows = tuple(
        readme.iter_rows(
            min_row=1,
            max_row=min(readme.max_row, 40),
            min_col=1,
            max_col=min(readme.max_column, 5),
        )
    )
    markers = {
        str(row[0].value or "").strip(): str(row[1].value or "").strip()
        for row in rows
        if len(row) >= 2
    }
    if (
        (
            workbook.properties.identifier == WORKBOOK_CONTRACT_ID
            and workbook.properties.category == WORKBOOK_SOURCE_CATEGORY
        )
        or (
            markers.get("工作簿契约") == WORKBOOK_CONTRACT_ID
            and markers.get("数据类别") == WORKBOOK_SOURCE_CATEGORY
        )
    ):
        return "formal"

    text = " ".join(
        str(cell.value or "")
        for row in rows[:12]
        for cell in row[:5]
    ).lower()
    combined = f"{filename} {text}".lower()
    synthetic_terms = ("合成数据", "模拟演练", "synthetic", "simulated", "claude-opus")
    if any(term in combined for term in synthetic_terms):
        return "synthetic"
    return "unknown"


def _response_fingerprint(data: Exp3Data) -> str:
    """计算三段身份与核心响应的稳定内容指纹。

    冻结列正好覆盖已逐格审计的 4560 个身份/问卷单元格；人口学、计时、运行时日志、技术
    有效性字段、访谈备注和样式均不参与。已知合成指纹总是拒绝；其他正式输入只有在来源
    核验后把该指纹登记到批准列表，才能作为论文证据。
    """

    payload: list[dict[str, Any]] = []
    fingerprint_tables = (
        (
            data.blocks,
            _BLOCK_FINGERPRINT_COLUMNS,
            ("Participant_ID", "Block_Index"),
        ),
        (
            data.methods,
            _METHOD_FINGERPRINT_COLUMNS,
            ("Participant_ID", "Rating_Order"),
        ),
        (
            data.finals,
            _FINAL_FINGERPRINT_COLUMNS,
            ("Participant_ID",),
        ),
    )
    for frame, columns, sort_columns in fingerprint_tables:
        payload.append(
            {
                "columns": [str(column) for column in columns],
                "rows": _canonical_fingerprint_rows(
                    frame,
                    columns=columns,
                    sort_columns=sort_columns,
                ),
            }
        )
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _source_gate_result(
    *,
    source_kind: str,
    response_fingerprint: str,
    approved_response_fingerprints: frozenset[str],
) -> tuple[bool, str]:
    """按“已知合成拒绝→正式标记→正向批准”的固定顺序判定论文资格。"""

    if response_fingerprint in _KNOWN_SYNTHETIC_RESPONSE_FINGERPRINTS:
        return (
            False,
            "来源完整性门禁：核心响应与已知 GPT 合成参考逐格一致；即使工作簿"
            "标记为 formal 或该指纹误入批准列表，也只能用于流程演练",
        )
    if source_kind != "formal":
        return (
            False,
            "来源完整性门禁：输入没有正式参与者工作簿标记，不得用于论文",
        )
    if response_fingerprint not in approved_response_fingerprints:
        return (
            False,
            "来源完整性门禁：工作簿虽标记为 formal，但核心响应指纹 "
            f"{response_fingerprint} 尚未经来源核验并登记到批准列表；本次输出仅供流程演练",
        )
    return True, "来源完整性门禁：formal 标记与已批准核心响应指纹一致"


def _canonical_fingerprint_rows(
    frame: pd.DataFrame,
    *,
    columns: tuple[str, ...],
    sort_columns: tuple[str, ...],
) -> list[list[str | None]]:
    """按稳定身份键排序核心响应，使工作表行重排不改变来源指纹。"""

    selected = frame.loc[:, columns]
    rows = [
        [_fingerprint_value(value) for value in row]
        for row in selected.itertuples(index=False, name=None)
    ]
    sort_positions = tuple(columns.index(column) for column in sort_columns)

    def canonical_key(row: list[str | None]) -> tuple[tuple[bool, str], ...]:
        """先按身份键、再按整行稳定排序；缺失值使用显式次序。"""

        positions = (*sort_positions, *range(len(row)))
        return tuple((row[position] is None, row[position] or "") for position in positions)

    return sorted(rows, key=canonical_key)


def _fingerprint_value(value: Any) -> str | None:
    """把原始单元格值规范化为响应指纹使用的稳定文本。"""

    if value is None or _is_missing_or_na(value):
        return None
    if isinstance(value, (datetime, time)):
        return value.isoformat()
    if isinstance(value, float):
        return format(value, ".15g")
    return str(value)


def _validate_structure(data: Exp3Data) -> None:
    """验证 24 平衡单元和三段记录的固定身份。"""

    _require_columns(
        data.participants,
        _PARTICIPANT_DESIGN_COLUMNS
        + tuple(PARTICIPANT_BACKGROUND_COLUMNS.values())
        + ("签署同意", "基线不适", "开始时间", "结束时间", "纳入分析", "退出/技术问题"),
        "Participants",
    )
    _require_columns(
        data.blocks,
        _BLOCK_DESIGN_COLUMNS + tuple(BLOCK_ITEMS.values()) + (
            "任务完成",
            "问卷完成",
            "区块有效",
            "技术问题",
        ),
        "Records A",
    )
    _require_columns(
        data.methods,
        _METHOD_DESIGN_COLUMNS + METHOD_ITEM_COLUMNS + ("尺度切换确认", "技术问题"),
        "Records B",
    )
    _require_columns(
        data.finals,
        (
            "Participant_ID",
            "方法选择(标签)",
            "偏好强度(1-7/NA)",
            "信任选择(标签)",
            "区分信心(1-7)",
            "开放:最明显区别",
            "开放:最破坏信任的现象",
            "结束不适",
        ),
        "Records C",
    )
    if len(data.participants) != 24 or len(data.blocks) != 144 or len(data.methods) != 48 or len(data.finals) != 24:
        raise ValueError(
            "实验三固定结构必须是 Participants=24、Records A=144、B=48、C=24"
        )
    participant_ids = tuple(data.participants["Participant_ID"].astype(str))
    if len(set(participant_ids)) != 24:
        raise ValueError("Participants 的 Participant_ID 必须唯一")
    expected = frozenset(participant_ids)
    for name, table, repetitions in (
        ("Records A", data.blocks, 6),
        ("Records B", data.methods, 2),
        ("Records C", data.finals, 1),
    ):
        counts = table["Participant_ID"].astype(str).value_counts()
        if frozenset(counts.index) != expected or not (counts == repetitions).all():
            raise ValueError(f"{name} 必须为每位参与者恰好保留 {repetitions} 行")
    _validate_design_mapping(data)


def _validate_design_mapping(data: Exp3Data) -> None:
    """核对标签映射、对象覆盖和方法级评分顺序。"""

    design = data.participants.copy()
    if design["平衡单元"].astype(str).duplicated().any():
        raise ValueError("Participants 的 24 个平衡单元必须唯一")
    order_ids = pd.to_numeric(design["物体排列ID"], errors="coerce")
    if order_ids.isna().any() or not set(order_ids.astype(int)) == set(range(1, 7)):
        raise ValueError("Participants 的物体排列ID必须覆盖 1--6")
    actual_cells = {
        (int(order_id), str(sequence), str(mapping))
        for order_id, sequence, mapping in zip(
            order_ids,
            design["标签序列"],
            design["方法A=（保密）"],
            strict=True,
        )
    }
    expected_cells = {
        (order_id, sequence, mapping)
        for order_id in range(1, 7)
        for sequence in ("S1", "S2")
        for mapping in METHODS
    }
    if actual_cells != expected_cells:
        raise ValueError("Participants 必须恰好覆盖 6 物体排列 × S1/S2 × A 标签映射的 24 单元")
    expected_label_order = {
        "S1": "A-B / B-A / A-B",
        "S2": "B-A / A-B / B-A",
    }
    for _, row in design.iterrows():
        sequence = str(row["标签序列"])
        if str(row["区块内标签顺序"]) != expected_label_order.get(sequence):
            raise ValueError(f"{row['Participant_ID']} 的区块内标签顺序与 {sequence} 不一致")
        first_label = "方法A" if sequence == "S1" else "方法B"
        first_method = row["方法A=（保密）"] if first_label == "方法A" else row["方法B=（保密）"]
        if str(row["先行实际方法"]) != str(first_method):
            raise ValueError(f"{row['Participant_ID']} 的先行实际方法与标签序列不一致")

    participants = design.set_index("Participant_ID")
    for participant_id, rows in data.blocks.groupby("Participant_ID", sort=False):
        if frozenset(rows["Condition(保密)"].astype(str)) != frozenset(METHODS):
            raise ValueError(f"{participant_id} 的区块未覆盖两种方法")
        if frozenset(rows["Object_Key"].astype(str)) != frozenset(OBJECTS):
            raise ValueError(f"{participant_id} 的区块未覆盖三个正式对象")
        if len(rows.groupby(["Object_Key", "Condition(保密)"], dropna=False)) != 6:
            raise ValueError(f"{participant_id} 的对象×方法区块不唯一")
        mapping = participants.loc[participant_id]
        expected_label = {
            "方法A": str(mapping["方法A=（保密）"]),
            "方法B": str(mapping["方法B=（保密）"]),
        }
        for _, row in rows.iterrows():
            label = str(row["Shown_Label"])
            condition = str(row["Condition(保密)"])
            if expected_label.get(label) != condition:
                raise ValueError(f"{participant_id} 的 {label} 映射与 Participants 不一致")
    for participant_id, rows in data.methods.groupby("Participant_ID", sort=False):
        if frozenset(rows["Condition(保密)"].astype(str)) != frozenset(METHODS):
            raise ValueError(f"{participant_id} 的方法级记录未覆盖两种方法")
        mapping = participants.loc[participant_id]
        expected_conditions = {
            "方法A": str(mapping["方法A=（保密）"]),
            "方法B": str(mapping["方法B=（保密）"]),
        }
        sequence = str(mapping["标签序列"])
        expected_labels = ("方法A", "方法B") if sequence == "S1" else ("方法B", "方法A")
        ordered = rows.sort_values("Rating_Order")
        if tuple(pd.to_numeric(ordered["Rating_Order"], errors="coerce")) != (1, 2):
            raise ValueError(f"{participant_id} 的方法级 Rating_Order 必须为 1、2")
        if tuple(ordered["Shown_Label"].astype(str)) != expected_labels:
            raise ValueError(f"{participant_id} 的方法级评分顺序与 {sequence} 不一致")
        for _, row in ordered.iterrows():
            label = str(row["Shown_Label"])
            if expected_conditions.get(label) != str(row["Condition(保密)"]):
                raise ValueError(f"{participant_id} 的方法级 {label} 映射与 Participants 不一致")


def _require_columns(table: pd.DataFrame, columns: Iterable[str], name: str) -> None:
    """要求逻辑表包含指定列。"""

    missing = set(columns).difference(table.columns)
    if missing:
        raise ValueError(f"{name} 缺少列：{sorted(missing)}")


def _validate_block_values(
    blocks: pd.DataFrame,
    included_ids: frozenset[str],
    *,
    aq_mode: str,
    q10_enabled: bool,
) -> None:
    """检查纳入参与者的区块状态与 1--7 原始评分。"""

    selected = blocks[blocks["Participant_ID"].astype(str).isin(included_ids)]
    for participant_id, rows in selected.groupby("Participant_ID", sort=False):
        valid = rows.apply(_block_is_valid, axis=1)
        if int(valid.sum()) != 6:
            raise ValueError(f"{participant_id} 必须有 6 个明确完成且有效的正式区块")
    required = [BLOCK_ITEMS[item] for item in required_block_items(aq_mode)]
    if q10_enabled:
        required.append(BLOCK_ITEMS["Q10"])
    _validate_numeric_range(selected, required, 1.0, 7.0, "区块评分")
    optional = set(BLOCK_ITEMS.values()).difference(required)
    _validate_numeric_range(
        selected,
        tuple(sorted(optional)),
        1.0,
        7.0,
        "可选区块评分",
        allow_missing=True,
    )
    _validate_manipulation_values(selected)


def _validate_manipulation_values(blocks: pd.DataFrame) -> None:
    """检查冻结方案要求报告的运行时操纵审计字段。"""

    _validate_finite_range(blocks, "Candidate_Rate_Hz", minimum=0.0, strict_minimum=True)
    for column in ("VCD_Median", "VCD_Admission_Rate", "Output_Availability"):
        _validate_finite_range(blocks, column, minimum=0.0, maximum=1.0)
    _validate_finite_range(blocks, "遮挡时长_s", minimum=0.0, strict_minimum=True)
    for column in ("服务器重获取次数", "StaticLock进入次数"):
        _validate_finite_range(blocks, column, minimum=0.0, integer=True)
    lifecycle = {"Coasting", "FrozenUncertain", "Lost", "不适用"}
    if blocks["遮挡生命周期状态"].map(_is_missing_or_na).any() or not blocks[
        "遮挡生命周期状态"
    ].astype(str).isin(lifecycle).all():
        raise ValueError("纳入区块的遮挡生命周期状态必须使用冻结选项")
    if blocks["进入Lost"].map(_is_missing_or_na).any() or not blocks["进入Lost"].map(
        lambda value: _is_yes(value) or _is_no(value)
    ).all():
        raise ValueError("纳入区块的进入Lost必须明确填写是或否")


def _validate_finite_range(
    table: pd.DataFrame,
    column: str,
    *,
    minimum: float,
    maximum: float | None = None,
    strict_minimum: bool = False,
    integer: bool = False,
) -> None:
    """验证一列审计数值完整、有限并位于指定范围。"""

    numeric = pd.to_numeric(table[column], errors="coerce")
    if numeric.isna().any() or not numeric.map(math.isfinite).all():
        raise ValueError(f"纳入区块的 {column} 必须全部填写有限数值")
    below = numeric <= minimum if strict_minimum else numeric < minimum
    above = numeric > maximum if maximum is not None else pd.Series(False, index=numeric.index)
    non_integer = numeric % 1 != 0 if integer else pd.Series(False, index=numeric.index)
    if (below | above | non_integer).any():
        interval = f"{minimum:g}--{maximum:g}" if maximum is not None else f">={minimum:g}"
        raise ValueError(f"纳入区块的 {column} 超出合法范围 {interval}")


def _validate_participant_values(
    participants: pd.DataFrame,
    included_ids: frozenset[str],
    *,
    require_complete: bool,
) -> None:
    """校验纳入样本的背景字段，并保留原始分类语义。"""

    selected = participants[participants["Participant_ID"].astype(str).isin(included_ids)]
    if require_complete:
        started_without_consent = participants[
            ~participants["开始时间"].map(_is_missing_or_na)
            & ~participants["签署同意"].map(_is_yes)
        ]
        if not started_without_consent.empty:
            raise ValueError("已开始会话的参与者必须先明确签署同意")
        if not selected["签署同意"].map(_is_yes).all():
            raise ValueError("纳入参与者必须全部明确签署同意")
        pending = participants[
            participants["签署同意"].map(_is_yes)
            & ~participants["纳入分析"].map(_is_yes)
            & ~participants["纳入分析"].map(_is_no)
        ]
        if not pending.empty:
            raise ValueError("正式分析前，所有已签署同意的参与者都必须明确标记纳入或排除")
        age = pd.to_numeric(selected["B1_年龄"], errors="coerce")
        if age.isna().any() or ((age <= 0) | (age > 120) | (age % 1 != 0)).any():
            raise ValueError("纳入参与者的 B1_年龄必须是 1--120 的正整数；此范围只作录入合法性检查")
        for output_column, source_column in PARTICIPANT_BACKGROUND_COLUMNS.items():
            if output_column == "Age":
                continue
            allowed = set(PARTICIPANT_CATEGORIES[output_column])
            values = selected[source_column]
            if values.isna().any() or not values.astype(str).isin(allowed).all():
                raise ValueError(f"纳入参与者的 {source_column} 必须使用冻结下拉选项")
        exposed = participants[
            participants["签署同意"].map(_is_yes)
            & ~participants["开始时间"].map(_is_missing_or_na)
        ]
        baseline_allowed = set(PARTICIPANT_CATEGORIES["Baseline_Discomfort"])
        baseline = exposed["基线不适"]
        invalid_baseline = ~baseline.map(_is_missing_or_na) & ~baseline.astype(str).isin(baseline_allowed)
        if invalid_baseline.any():
            raise ValueError("已开始参与者的基线不适必须留空或使用冻结选项")
        for column in ("开始时间", "结束时间"):
            values = selected[column]
            if values.map(_is_missing_or_na).any():
                raise ValueError(f"纳入参与者的 {column} 不得缺失")
            if not values.map(_is_supported_time).all():
                raise ValueError(f"纳入参与者的 {column} 必须是 Excel 时间或 HH:MM[:SS]")
        if not exposed["开始时间"].map(_is_supported_time).all():
            raise ValueError("已开始参与者的开始时间必须是 Excel 时间或 HH:MM[:SS]")
        recorded_end = exposed.loc[~exposed["结束时间"].map(_is_missing_or_na), "结束时间"]
        if not recorded_end.map(_is_supported_time).all():
            raise ValueError("已开始参与者的非空结束时间必须是 Excel 时间或 HH:MM[:SS]")

    excluded = participants[
        participants["签署同意"].map(_is_yes)
        & participants["纳入分析"].map(_is_no)
    ]
    if require_complete and excluded["退出/技术问题"].map(_is_missing_or_na).any():
        raise ValueError("已签署同意但不纳入分析的参与者必须记录退出/技术问题")
    if require_complete:
        recorded_reasons = excluded.loc[~excluded["退出/技术问题"].map(_is_missing_or_na), "退出/技术问题"]
        if not recorded_reasons.astype(str).isin(EXCLUSION_REASONS).all():
            raise ValueError("退出/技术问题必须使用冻结主原因；补充细节只写备注")


def _validate_method_values(
    methods: pd.DataFrame,
    included_ids: frozenset[str],
    *,
    require_complete: bool,
) -> None:
    """检查纳入参与者的方法级原始评分与审核状态。"""

    selected = methods[methods["Participant_ID"].astype(str).isin(included_ids)]
    if require_complete:
        for column in METHOD_ITEM_COLUMNS[:10]:
            if selected[column].map(_is_blank_response).any():
                raise ValueError(f"纳入参与者的 TiA 条目 {column} 必须填写评分或“无法回答”")
    _validate_numeric_range(selected, METHOD_ITEM_COLUMNS[:10], 1.0, 5.0, "TiA 原始评分", allow_missing=True)
    _validate_numeric_range(selected, METHOD_ITEM_COLUMNS[10:], 1.0, 7.0, "S-TIAS 原始评分")
    if require_complete and not method_assessment_complete_mask(selected).all():
        raise ValueError("纳入参与者的两次方法级问卷都必须完整作答并确认尺度切换")
    if not method_record_valid_mask(selected).all():
        raise ValueError("纳入参与者的方法级记录必须通过技术状态、A/B 回忆和人工有效性审核")


def _validate_final_values(
    finals: pd.DataFrame,
    included_ids: frozenset[str],
    safety_ids: frozenset[str],
    *,
    require_complete: bool,
) -> None:
    """检查最终选择、条件跳题与区分信心。"""

    selected = finals[finals["Participant_ID"].astype(str).isin(included_ids)]
    choices = {"方法A", "方法B", "无明显偏好"}
    for column in ("方法选择(标签)", "信任选择(标签)"):
        invalid = selected[column].dropna().astype(str).map(lambda value: value not in choices)
        if selected[column].isna().any() or invalid.any():
            raise ValueError(f"纳入参与者的 {column} 必须使用方法A/方法B/无明显偏好")
    _validate_numeric_range(selected, ("区分信心(1-7)",), 1.0, 7.0, "区分信心")
    for _, row in selected.iterrows():
        choice = row["方法选择(标签)"]
        strength = row["偏好强度(1-7/NA)"]
        if str(choice) == "无明显偏好":
            if not _is_missing_or_na(strength):
                raise ValueError("选择无明显偏好时，偏好强度必须留空或写 N/A")
        elif _number_or_none(strength) is None or not 1.0 <= float(strength) <= 7.0:
            raise ValueError("做出方法选择时，偏好强度必须为 1--7")
    if require_complete:
        for column in ("开放:最明显区别", "开放:最破坏信任的现象", "结束不适"):
            if selected[column].map(_is_missing_or_na).any():
                raise ValueError(f"纳入参与者的 {column} 不得缺失")
        allowed_discomfort = set(PARTICIPANT_CATEGORIES["End_Discomfort"])
        if not selected["结束不适"].astype(str).isin(allowed_discomfort).all():
            raise ValueError("纳入参与者的结束不适必须使用冻结选项")
        safety = finals[finals["Participant_ID"].astype(str).isin(safety_ids)]
        recorded = safety.loc[~safety["结束不适"].map(_is_missing_or_na), "结束不适"]
        if not recorded.astype(str).isin(allowed_discomfort).all():
            raise ValueError("已开始参与者的非空结束不适必须使用冻结选项")


def method_assessment_complete_mask(methods: pd.DataFrame) -> pd.Series:
    """返回方法级问卷已作答且完成尺度切换确认的掩码。"""

    responses = methods.loc[:, list(METHOD_ITEM_COLUMNS)].apply(
        lambda column: ~column.map(_is_blank_response)
    )
    return responses.all(axis=1) & methods["尺度切换确认"].map(_is_yes)


def method_record_valid_mask(methods: pd.DataFrame) -> pd.Series:
    """返回通过技术、回忆与人工审核的方法级记录掩码。"""

    valid = methods["尺度切换确认"].map(_is_yes)
    valid &= methods["技术问题"].map(
        lambda value: _is_missing_or_na(value) or str(value).strip() == "无"
    )
    for optional_column in ("A/B归属回忆确认", "方法级记录有效"):
        if optional_column in methods:
            valid &= methods[optional_column].map(_is_yes)
    return valid


def block_valid_mask(blocks: pd.DataFrame) -> pd.Series:
    """返回同时满足完成、问卷与技术状态的区块有效掩码。"""

    return blocks.apply(_block_is_valid, axis=1)


def _block_is_valid(row: pd.Series) -> bool:
    """判断一个区块是否满足冻结的技术有效条件。"""

    return (
        _is_yes(row.get("任务完成"))
        and _is_yes(row.get("问卷完成"))
        and _is_yes(row.get("区块有效"))
    )


def included_participant_ids(participants: pd.DataFrame) -> frozenset[str]:
    """返回明确标记为纳入分析的参与者 ID。"""

    return frozenset(
        participants.loc[participants["纳入分析"].map(_is_yes), "Participant_ID"].astype(str)
    )


def _validate_numeric_range(
    table: pd.DataFrame,
    columns: Iterable[str],
    minimum: float,
    maximum: float,
    label: str,
    *,
    allow_missing: bool = False,
) -> None:
    """检查若干评分列是整数刻度值，并按契约处理缺失。"""

    for column in columns:
        numeric = pd.to_numeric(table[column], errors="coerce")
        invalid_text = table[column].notna() & numeric.isna() & ~table[column].map(_is_missing_or_na)
        if invalid_text.any():
            raise ValueError(f"{label}列 {column} 含非数值响应")
        valid = numeric.dropna()
        if ((valid < minimum) | (valid > maximum) | (valid % 1 != 0)).any():
            raise ValueError(f"{label}列 {column} 必须是 {minimum:.0f}--{maximum:.0f} 整数")
        if not allow_missing and numeric.isna().any():
            raise ValueError(f"{label}列 {column} 不允许缺失")


def _number_or_none(value: Any) -> float | None:
    """把普通数字转换为 float，缺失或 N/A 返回 None。"""

    if _is_missing_or_na(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_missing_or_na(value: Any) -> bool:
    """识别工作簿允许的空值或 N/A 文本。"""

    if value is None or (isinstance(value, float) and pd.isna(value)):
        return True
    return str(value).strip().lower() in {"", "n/a", "na", "无法回答"}


def _is_yes(value: Any) -> bool:
    """识别人工确认字段中的肯定值。"""

    return str(value or "").strip().lower() in {"是", "yes", "true", "1"}


def _is_no(value: Any) -> bool:
    """识别人工确认字段中的否定值。"""

    return str(value or "").strip().lower() in {"否", "no", "false", "0"}


def _is_supported_time(value: Any) -> bool:
    """判断会话时刻能否稳定解析为 Excel 时间或常见时刻文本。"""

    if isinstance(value, (datetime, time)):
        return True
    text = str(value).strip()
    for pattern in ("%H:%M", "%H:%M:%S"):
        try:
            datetime.strptime(text, pattern)
            return True
        except ValueError:
            continue
    return False


def _is_blank_response(value: Any) -> bool:
    """区分真正空白与 TiA 的显式“无法回答”响应。"""

    if isinstance(value, str) and value.strip() == "无法回答":
        return False
    return _is_missing_or_na(value)


__all__ = [
    "block_valid_mask",
    "describe_workbook",
    "included_participant_ids",
    "method_assessment_complete_mask",
    "method_record_valid_mask",
    "read_workbook",
    "validate_for_analysis",
    "workbook_sha256",
]

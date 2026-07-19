"""GPT v4 分析使用的只读 Stage 1 XLSX 流式 reader。"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any


_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_COLUMN_PATTERN = re.compile(r"([A-Z]+)")
_PARTITION_PATTERN = re.compile(r"^(?P<logical>.+)_(?P<index>[0-9]{3})$")


def workbook_sha256(path: Path) -> str:
    """返回输入 workbook 的 SHA-256，供结果 lineage 使用。"""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _column_index(reference: str) -> int:
    """把 Excel 列引用转换为从零开始的整数索引。"""

    match = _COLUMN_PATTERN.match(reference)
    if match is None:
        return -1
    index = 0
    for character in match.group(1):
        index = index * 26 + ord(character) - 64
    return index - 1


def _sheet_map(path: Path) -> Mapping[str, str]:
    """读取 XLSX workbook 关系并返回 sheet 名到 XML 路径的映射。"""

    with zipfile.ZipFile(path) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {row.attrib["Id"]: row.attrib["Target"] for row in relationships}
        sheets = workbook.find(f"{{{_MAIN_NS}}}sheets")
        if sheets is None:
            raise ValueError(f"XLSX 缺少 sheets：{path}")
        result: dict[str, str] = {}
        for sheet in sheets:
            name = sheet.attrib["name"]
            relation_id = sheet.attrib[f"{{{_REL_NS}}}id"]
            target = targets[relation_id]
            result[name] = target.lstrip("/") if target.startswith("/") else f"xl/{target.lstrip('/')}"
        return result


def _logical_sheets(path: Path, logical_name: str) -> tuple[str, ...]:
    """返回逻辑 sheet 对应的单 sheet 或全部 ``_001`` 分片。"""

    names = tuple(_sheet_map(path))
    if logical_name in names:
        return (logical_name,)
    partitions: list[tuple[int, str]] = []
    for name in names:
        match = _PARTITION_PATTERN.match(name)
        if match is not None and match.group("logical") == logical_name:
            partitions.append((int(match.group("index")), name))
    if not partitions:
        raise KeyError(f"workbook 缺少逻辑 sheet：{logical_name}: {path}")
    return tuple(name for _, name in sorted(partitions))


def _cell_value(cell: ET.Element) -> Any:
    """按 XLSX 单元格类型还原布尔、数值或文本值。"""

    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.iter(f"{{{_MAIN_NS}}}t"))
    value_node = cell.find(f"{{{_MAIN_NS}}}v")
    if value_node is None or value_node.text is None:
        return None
    text = value_node.text
    if cell_type == "b":
        return text == "1"
    if cell_type in {"str", "e"}:
        return text
    try:
        return float(text) if any(character in text for character in ".eE") else int(text)
    except ValueError:
        return text


def _iter_physical_rows(
    path: Path,
    sheet_name: str,
    columns: frozenset[str] | None,
) -> Iterator[dict[str, Any]]:
    """流式读取一个物理 sheet；每个分片独立校验表头。"""

    xml_path = _sheet_map(path)[sheet_name]
    with zipfile.ZipFile(path) as archive, archive.open(xml_path) as handle:
        headers: list[str | None] = []
        for _, element in ET.iterparse(handle, events=("end",)):
            if element.tag != f"{{{_MAIN_NS}}}row":
                continue
            cells: dict[int, Any] = {}
            maximum_index = -1
            for cell in element.findall(f"{{{_MAIN_NS}}}c"):
                index = _column_index(cell.attrib.get("r", ""))
                if index >= 0:
                    cells[index] = _cell_value(cell)
                    maximum_index = max(maximum_index, index)
            if not headers:
                headers = [None] * (maximum_index + 1)
                for index, value in cells.items():
                    headers[index] = str(value) if value is not None else None
                element.clear()
                continue
            row = {
                headers[index]: value
                for index, value in cells.items()
                if index < len(headers)
                and headers[index] is not None
                and (columns is None or headers[index] in columns)
            }
            if row:
                yield row  # type: ignore[misc]
            element.clear()


def iter_rows(
    path: Path,
    logical_sheet: str,
    columns: Iterable[str] | None = None,
) -> Iterator[dict[str, Any]]:
    """只读遍历 Stage 1 逻辑 sheet，自动串接超限分片。"""

    normalized = path.expanduser().resolve()
    if normalized.suffix.lower() != ".xlsx":
        raise ValueError(f"GPT v4 分析只接受 Stage 1 XLSX：{path}")
    if not normalized.is_file():
        raise FileNotFoundError(normalized)
    selected = frozenset(columns) if columns is not None else None
    for sheet_name in _logical_sheets(normalized, logical_sheet):
        yield from _iter_physical_rows(normalized, sheet_name, selected)


__all__ = ["iter_rows", "workbook_sha256"]

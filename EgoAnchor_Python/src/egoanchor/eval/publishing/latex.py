"""Stage 3 paper CSV 到可审计 TeX 中间产物的生成器。"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping

from ..contracts import CSV_TABLE_CONTRACTS
from ._atomic import atomic_publish_directories, validate_output_boundary
from .style import csv_sha256


_EXPERIMENTS = {
    "exp1_system_characterization": ("One", "exp1"),
    "exp2_design_attribution": ("Two", "exp2"),
}
"""实验标识到 TeX 前缀和文件名前缀的冻结映射。"""

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
"""CSV 行级来源 SHA-256 的格式。"""

_CONTROL_DIGIT_PATTERN = re.compile(r"\\[A-Za-z]*[0-9]")
"""非法含数字 LaTeX 控制序列扫描规则。"""

_TABLE_LAYOUTS = {
    "exp1_scenario_summary": (
        "System",
        (
            "World P95 ↓",
            "HP--RMS ↓",
            "Response ↓",
            "Trans. residual ↓",
            "Rot. residual ↓",
            "Occlusion P95 ↓",
        ),
        (
            r"@{}>{\raggedright\arraybackslash}p{0.16\textwidth}"
            r"*{6}{>{\raggedleft\arraybackslash}X}@{}"
        ),
    ),
    "exp2_mechanism_attribution": (
        "机制 / 场景",
        (
            "主指标",
            "Full median [IQR]",
            "Ablated median [IQR]",
            "Delta [IQR]（+/0/-）",
            "护栏 Delta [IQR]",
        ),
        (
            r"@{}>{\raggedright\arraybackslash}p{0.14\textwidth}"
            r">{\raggedright\arraybackslash}p{0.13\textwidth}"
            r"*{3}{>{\raggedleft\arraybackslash}X}"
            r">{\raggedleft\arraybackslash}p{0.19\textwidth}@{}"
        ),
    ),
}
"""论文表机器名到首列表头、冻结列和 tabularx 列布局的映射。"""


@dataclass(frozen=True, slots=True)
class LatexPublishResult:
    """保存四个 TeX 中间产物及其输入输出 hash。"""

    output_root: Path
    """原子替换后的 TeX 发布目录。"""

    tex_sha256: Mapping[str, str]
    """四个 TeX 文件的二进制 SHA-256。"""

    input_csv_sha256: Mapping[str, str]
    """numbers/tables CSV 的二进制 SHA-256。"""


@dataclass(frozen=True, slots=True)
class _LatexBuild:
    """保存 staging 目录内完成回读的 TeX hash。"""

    tex_sha256: Mapping[str, str]
    """四个 staging TeX 的 SHA-256。"""

    input_csv_sha256: Mapping[str, str]
    """两个固定 paper CSV 的 SHA-256。"""


def _contract_columns(table_name: str) -> tuple[str, ...]:
    """读取 paper CSV 的冻结列顺序。

    参数：
        table_name: numbers 或 tables 契约名。
    """

    for contract in CSV_TABLE_CONTRACTS:
        if contract.name == table_name:
            return contract.column_names()
    raise ValueError(f"未知 paper CSV 契约：{table_name}")


def _read_csv(path: Path, table_name: str) -> tuple[dict[str, str], ...]:
    """按冻结表头读取一个固定 paper CSV。

    参数：
        path: 固定 paper CSV 路径。
        table_name: 对应的冻结契约名。
    """

    if not path.is_file():
        raise FileNotFoundError(f"缺少 Stage 2 paper CSV：{path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != _contract_columns(table_name):
            raise ValueError(f"paper CSV 表头不符合契约：{path}")
        rows = tuple(dict(row) for row in reader)
    if not rows:
        raise ValueError(f"paper CSV 不能为空：{path}")
    return rows


def _validate_common_row(row: Mapping[str, str]) -> tuple[str, str]:
    """校验实验标识和 Stage 2 上游来源字段。

    参数：
        row: numbers 或 tables 的一条 CSV 行。
    """

    experiment = str(row.get("experiment") or "")
    if experiment not in _EXPERIMENTS:
        raise ValueError(f"paper CSV 使用未知实验标识：{experiment}")
    source_csv = str(row.get("source_csv") or "")
    source_sha256 = str(row.get("source_sha256") or "")
    if not source_csv.endswith(".csv") or not _SHA256_PATTERN.fullmatch(source_sha256):
        raise ValueError("paper CSV 的上游 source_csv/source_sha256 非法")
    return _EXPERIMENTS[experiment]


def _numeric_text(value: str) -> str:
    """验证宏值为有限十进制并保留 CSV 原始文本。

    参数：
        value: numbers.csv 的原始 value 单元格。
    """

    text = value.strip()
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"paper number 不是数字：{value}") from exc
    if not number.is_finite():
        raise ValueError(f"paper number 不是有限数字：{value}")
    return text


def _escape_tex(value: str) -> str:
    """转义表格中的 LaTeX 特殊字符，不解释任意控制序列。

    参数：
        value: display-ready 纯文本。
    """

    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(character, character) for character in value)


def _render_cell(value: str) -> str:
    """渲染表格单元格，并支持 Stage 2 标记的最佳值加粗。"""

    marker = "[BEST]"
    if value.startswith(marker):
        return rf"\textbf{{{_escape_tex(value[len(marker):].lstrip())}}}"
    return _escape_tex(value)


def _source_header(relative_path: str, source_hash: str) -> str:
    """生成 TeX 中间产物的固定 lineage 头。

    参数：
        relative_path: Stage 3 输入 CSV 的相对路径。
        source_hash: 该 CSV 的二进制 SHA-256。
    """

    return (
        f"% Source: {relative_path}; SHA-256: {source_hash}; "
        "generator: egoanchor.eval.publishing.latex-v1\n"
    )


def _render_numbers(
    rows: tuple[dict[str, str], ...],
    experiment: str,
    source_hash: str,
) -> str:
    """把一个实验的 number 行渲染为纯字母控制序列。

    参数：
        rows: numbers.csv 的全部行。
        experiment: 当前输出的冻结实验标识。
        source_hash: numbers.csv 的二进制 SHA-256。
    """

    prefix, _ = _EXPERIMENTS[experiment]
    selected = [row for row in rows if row.get("experiment") == experiment]
    if not selected:
        raise ValueError(f"numbers.csv 缺少实验：{experiment}")
    commands: list[tuple[str, str]] = []
    seen: set[str] = set()
    for row in selected:
        _validate_common_row(row)
        suffix = str(row.get("macro_name") or "")
        if not suffix.isascii() or not suffix.isalpha():
            raise ValueError(f"TeX 宏名必须只含 ASCII 字母：{suffix}")
        command = f"EAExp{prefix}{suffix}"
        if command in seen:
            raise ValueError(f"TeX 宏名重复：{command}")
        seen.add(command)
        commands.append((command, _numeric_text(str(row.get("value") or ""))))
    lines = [_source_header("paper/numbers.csv", source_hash).rstrip("\n")]
    lines.extend(f"\\newcommand{{\\{command}}}{{{value}}}" for command, value in sorted(commands))
    return "\n".join(lines) + "\n"


def _render_tables(
    rows: tuple[dict[str, str], ...],
    experiment: str,
    source_hash: str,
) -> str:
    """把一个实验的 display-ready table cells 渲染为 tabular。

    参数：
        rows: tables.csv 的全部 display-ready 单元格。
        experiment: 当前输出的冻结实验标识。
        source_hash: tables.csv 的二进制 SHA-256。
    """

    selected = [row for row in rows if row.get("experiment") == experiment]
    if not selected:
        raise ValueError(f"tables.csv 缺少实验：{experiment}")
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in selected:
        _validate_common_row(row)
        table_name = str(row.get("table_name") or "")
        row_key = str(row.get("row_key") or "")
        column_key = str(row.get("column_key") or "")
        if not table_name or not row_key or not column_key:
            raise ValueError("paper table 的 table_name/row_key/column_key 不能为空")
        grouped[table_name].append(row)

    lines = [_source_header("paper/tables.csv", source_hash).rstrip("\n")]
    for table_name, cells in grouped.items():
        row_keys = list(dict.fromkeys(str(cell["row_key"]) for cell in cells))
        column_keys = list(dict.fromkeys(str(cell["column_key"]) for cell in cells))
        values = {
            (str(cell["row_key"]), str(cell["column_key"])): str(cell["display_value"])
            for cell in cells
        }
        if len(values) != len(cells):
            raise ValueError(f"paper table 单元格重复：{table_name}")
        missing = [
            (row_key, column_key)
            for row_key in row_keys
            for column_key in column_keys
            if (row_key, column_key) not in values
        ]
        if missing:
            raise ValueError(f"paper table 不是完整矩形：{table_name}")
        try:
            row_header, expected_columns, column_spec = _TABLE_LAYOUTS[table_name]
        except KeyError as exc:
            raise ValueError(f"paper table 缺少固定排版：{table_name}") from exc
        if tuple(column_keys) != expected_columns:
            raise ValueError(f"paper table 列顺序不符合固定排版：{table_name}")
        lines.append(f"% Table: {_escape_tex(table_name)}")
        lines.append(r"\begingroup")
        lines.append(r"\scriptsize")
        lines.append(r"\setlength{\tabcolsep}{3pt}")
        lines.append(r"\renewcommand{\arraystretch}{1.08}")
        lines.append(rf"\begin{{tabularx}}{{\textwidth}}{{{column_spec}}}")
        lines.append(r"\toprule")
        header = _escape_tex(row_header) + " & " + " & ".join(
            _escape_tex(value) for value in column_keys
        ) + r" \\"
        lines.append(header)
        lines.append(r"\midrule")
        for row_key in row_keys:
            values_text = " & ".join(
                _render_cell(values[(row_key, column_key)]) for column_key in column_keys
            )
            lines.append(f"{_escape_tex(row_key)} & {values_text} " + r"\\")
        lines.append(r"\bottomrule")
        lines.append(r"\end{tabularx}")
        lines.append(r"\endgroup")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _build_latex(csv_root: Path, output_root: Path) -> _LatexBuild:
    """在 staging 目录生成并回读四个 TeX。

    参数：
        csv_root: Stage 2 CSV 根目录。
        output_root: 本次调用独占的 staging 目录。
    """

    root = csv_root.expanduser().resolve()
    numbers_path = root / "paper" / "numbers.csv"
    tables_path = root / "paper" / "tables.csv"
    numbers = _read_csv(numbers_path, "numbers")
    tables = _read_csv(tables_path, "tables")
    input_hashes = {
        "paper/numbers.csv": csv_sha256(numbers_path),
        "paper/tables.csv": csv_sha256(tables_path),
    }
    rendered: dict[str, str] = {}
    for experiment, (_, file_prefix) in _EXPERIMENTS.items():
        rendered[f"{file_prefix}_numbers.tex"] = _render_numbers(
            numbers,
            experiment,
            input_hashes["paper/numbers.csv"],
        )
        rendered[f"{file_prefix}_tables.tex"] = _render_tables(
            tables,
            experiment,
            input_hashes["paper/tables.csv"],
        )

    destination = output_root.expanduser().resolve()
    expected_files = set(rendered)
    for file_name, content in rendered.items():
        (destination / file_name).write_text(content, encoding="utf-8", newline="\n")
    actual_files = {path.name for path in destination.iterdir() if path.is_file()}
    if actual_files != expected_files:
        raise ValueError("TeX staging 文件集合不完整")
    tex_hashes: dict[str, str] = {}
    for file_name, expected_content in rendered.items():
        path = destination / file_name
        actual_content = path.read_text(encoding="utf-8")
        if actual_content != expected_content:
            raise ValueError(f"TeX 回读内容不一致：{file_name}")
        if _CONTROL_DIGIT_PATTERN.search(actual_content):
            raise ValueError(f"TeX 控制序列含阿拉伯数字：{file_name}")
        tex_hashes[file_name] = csv_sha256(path)
    return _LatexBuild(tex_hashes, input_hashes)


def publish_latex(csv_root: Path, output_root: Path) -> LatexPublishResult:
    """只读两个 Stage 2 paper CSV，原子发布四个 TeX 中间产物。

    参数：
        csv_root: Stage 2 CSV 根目录。
        output_root: 四个 TeX 的正式输出目录。
    """

    root = csv_root.expanduser().resolve()
    destination = validate_output_boundary(root, output_root, "TeX ")
    build = atomic_publish_directories(
        (destination,),
        (lambda stage: _build_latex(root, stage),),
    )[0]
    return LatexPublishResult(destination, build.tex_sha256, build.input_csv_sha256)


__all__ = ["LatexPublishResult", "publish_latex"]

"""Stage 4 四个 TeX 中间产物到中文主稿受控区块的物化工具。"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


_SOURCE_FILES = (
    "exp1_numbers.tex",
    "exp2_numbers.tex",
    "exp1_tables.tex",
    "exp2_tables.tex",
)
"""Stage 4 唯一允许读取的四个固定 TeX 文件。"""

_SOURCE_CSV = {
    "exp1_numbers.tex": "paper/numbers.csv",
    "exp2_numbers.tex": "paper/numbers.csv",
    "exp1_tables.tex": "paper/tables.csv",
    "exp2_tables.tex": "paper/tables.csv",
}
"""四个 TeX 必须声明的直接 Stage 2 CSV。"""

_SOURCE_CONTENT = {
    "exp1_numbers.tex": "EAExpOne",
    "exp2_numbers.tex": "EAExpTwo",
    "exp1_tables.tex": r"% Table: exp1\_scenario\_summary",
    "exp2_tables.tex": r"% Table: exp2\_mechanism\_attribution",
}
"""四个 TeX 的实验归属标识。"""

_LATEX_GENERATOR = "egoanchor.eval.publishing.latex-v1"
"""Task 11 冻结的 TeX 生成器版本。"""

_BLOCKS = {
    "numbers": (
        "% EGOANCHOR-EXP-DATA:BEGIN",
        "% EGOANCHOR-EXP-DATA:END",
    ),
    "exp1_table": (
        "% EGOANCHOR-EXP-ONE-TABLE:BEGIN",
        "% EGOANCHOR-EXP-ONE-TABLE:END",
    ),
    "exp2_table": (
        "% EGOANCHOR-EXP-TWO-TABLE:BEGIN",
        "% EGOANCHOR-EXP-TWO-TABLE:END",
    ),
}
"""主稿三个唯一受控区块的稳定边界。"""

_SOURCE_HEADER = re.compile(
    r"^% Source: (?P<csv>[^;]+); SHA-256: (?P<hash>[0-9a-f]{64}); "
    r"generator: (?P<generator>[^;]+)$"
)
"""Task 11 TeX 首行的 Stage 2 CSV lineage。"""

_COMMAND_PATTERN = re.compile(r"\\newcommand\{\\(?P<name>[A-Za-z]+)\}")
"""纯字母宏定义提取规则。"""

_OLD_INCLUDE_PATTERN = re.compile(
    r"(?:\./)?generated[\\/]+exp(?:1|2)_(?:numbers|tables)(?:\.tex)?"
)
"""主稿不得保留的四个旧 include 路径及常见变体。"""


@dataclass(frozen=True, slots=True)
class _TexSource:
    """保存一个 Stage 3 TeX 的内容和两级 lineage。"""

    file_name: str
    """固定 TeX 文件名。"""

    body: str
    """移除 Task 11 lineage 首行后的 TeX 正文。"""

    tex_sha256: str
    """Stage 3 TeX 文件二进制 SHA-256。"""

    csv_sha256: str
    """Stage 3 TeX 记录的直接输入 CSV SHA-256。"""


@dataclass(frozen=True, slots=True)
class MaterializeResult:
    """保存一次 Stage 4 主稿物化的 hash 和区块数量。"""

    manuscript_path: Path
    """已原子更新的中文主稿路径。"""

    manuscript_sha256: str
    """物化后主稿二进制 SHA-256。"""

    source_tex_sha256: Mapping[str, str]
    """四个 Stage 3 TeX 的二进制 SHA-256。"""

    source_csv_sha256: Mapping[str, str]
    """四个 TeX 首行记录的 Stage 2 CSV SHA-256。"""

    block_count: int
    """已验证并替换的受控区块数量，固定为三。"""


def _file_sha256(path: Path) -> str:
    """流式计算文件 SHA-256。

    参数：
        path: 待计算的 TeX 或主稿文件。
    """

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_source(path: Path) -> _TexSource:
    """读取并验证一个固定 Stage 3 TeX。

    参数：
        path: tex_root 下的固定 TeX 文件。
    """

    if not path.is_file():
        raise FileNotFoundError(f"缺少 Stage 3 TeX：{path}")
    encoded = path.read_bytes()
    text = encoded.decode("utf-8")
    first_line, separator, body = text.partition("\n")
    first_line = first_line.rstrip("\r")
    match = _SOURCE_HEADER.fullmatch(first_line)
    if not separator or match is None or not body.strip():
        raise ValueError(f"Stage 3 TeX 缺少合法 lineage 或正文：{path.name}")
    if (
        match.group("csv") != _SOURCE_CSV[path.name]
        or match.group("generator") != _LATEX_GENERATOR
    ):
        raise ValueError(f"Stage 3 TeX lineage 与固定来源不匹配：{path.name}")
    expected_content = _SOURCE_CONTENT[path.name]
    if path.name.endswith("_numbers.tex"):
        commands = _COMMAND_PATTERN.findall(body)
        if not commands or any(not command.startswith(expected_content) for command in commands):
            raise ValueError(f"Stage 3 TeX 实验归属错误：{path.name}")
    elif expected_content not in body:
        raise ValueError(f"Stage 3 TeX 实验归属错误：{path.name}")
    return _TexSource(
        file_name=path.name,
        body=body.rstrip("\n") + "\n",
        tex_sha256=hashlib.sha256(encoded).hexdigest(),
        csv_sha256=match.group("hash"),
    )


def _lineage(source: _TexSource) -> str:
    """生成受控区块内单个 TeX 的完整 lineage 首行。

    参数：
        source: 已验证的 Stage 3 TeX 来源。
    """

    return (
        f"% Source CSV SHA-256: {source.csv_sha256}; "
        f"Stage 3 TeX SHA-256: {source.tex_sha256}; "
        f"generator: egoanchor.eval.materialize-v1; file: {source.file_name}"
    )


def _payload(*sources: _TexSource) -> str:
    """拼接一个受控区块的 lineage 与 TeX 正文。

    参数：
        sources: 按冻结顺序进入同一区块的一个或多个 TeX。
    """

    lines = [_lineage(source) for source in sources]
    lines.append("% 由 egoanchor.eval 自动生成，请勿手工修改本区块。")
    for source in sources:
        lines.append(source.body.rstrip("\n"))
    return "\n".join(lines) + "\n"


def _replace_block(text: str, begin: str, end: str, payload: str) -> str:
    """只替换一对唯一边界标记之间的内容。

    参数：
        text: 当前完整主稿。
        begin: 区块开始标记。
        end: 区块结束标记。
        payload: 待写入区块的已验证 TeX。
    """

    if text.count(begin) != 1 or text.count(end) != 1:
        raise ValueError(f"主稿区块标记必须唯一：{begin} / {end}")
    prefix, remainder = text.split(begin, 1)
    _, suffix = remainder.split(end, 1)
    if text.index(begin) >= text.index(end):
        raise ValueError(f"主稿区块标记顺序非法：{begin}")
    return f"{prefix}{begin}\n{payload.rstrip()}\n{end}{suffix}"


def _validate_manuscript(text: str, sources: Mapping[str, _TexSource]) -> None:
    """验证物化后的区块、宏唯一性和旧 include 清理。

    参数：
        text: 待正式写入的完整主稿。
        sources: 四个固定 Stage 3 TeX 来源。
    """

    for begin, end in _BLOCKS.values():
        if text.count(begin) != 1 or text.count(end) != 1:
            raise ValueError(f"物化后主稿区块标记不唯一：{begin}")
    if _OLD_INCLUDE_PATTERN.search(text):
        raise ValueError("物化后主稿仍含旧 generated TeX include")
    expected_commands: list[str] = []
    for file_name in ("exp1_numbers.tex", "exp2_numbers.tex"):
        commands = _COMMAND_PATTERN.findall(sources[file_name].body)
        if not commands:
            raise ValueError(f"数字 TeX 未定义任何宏：{file_name}")
        expected_commands.extend(commands)
    if len(expected_commands) != len(set(expected_commands)):
        raise ValueError("四个 TeX 包含重复实验宏")
    for command in expected_commands:
        if len(re.findall(rf"\\newcommand\{{\\{command}\}}", text)) != 1:
            raise ValueError(f"主稿实验宏未唯一物化：{command}")
    for file_name in ("exp1_tables.tex", "exp2_tables.tex"):
        if not any(
            environment in sources[file_name].body
            for environment in (r"\begin{tabular}", r"\begin{tabularx}")
        ):
            raise ValueError(f"表格 TeX 缺少 tabular/tabularx：{file_name}")


def materialize_paper(tex_root: Path, manuscript_path: Path) -> MaterializeResult:
    """只读取四个 Stage 3 TeX，将其原子写入主稿三个受控区块。

    参数：
        tex_root: 只包含四个固定 Stage 3 TeX 的目录。
        manuscript_path: 已建立三个唯一边界标记的中文主稿。
    """

    root = tex_root.expanduser().resolve()
    manuscript = manuscript_path.expanduser().resolve()
    if manuscript == root or manuscript.is_relative_to(root):
        raise ValueError("主稿输出不得位于 Stage 3 TeX 输入目录内")
    if not manuscript.is_file():
        raise FileNotFoundError(f"主稿不存在：{manuscript}")
    sources = {file_name: _read_source(root / file_name) for file_name in _SOURCE_FILES}
    original = manuscript.read_bytes().decode("utf-8")
    if _OLD_INCLUDE_PATTERN.search(original):
        raise ValueError("主稿仍含旧 generated TeX include")
    updated = _replace_block(
        original,
        *_BLOCKS["numbers"],
        _payload(sources["exp1_numbers.tex"], sources["exp2_numbers.tex"]),
    )
    updated = _replace_block(
        updated,
        *_BLOCKS["exp1_table"],
        _payload(sources["exp1_tables.tex"]),
    )
    updated = _replace_block(
        updated,
        *_BLOCKS["exp2_table"],
        _payload(sources["exp2_tables.tex"]),
    )
    _validate_manuscript(updated, sources)
    encoded = updated.encode("utf-8")
    manuscript_hash = hashlib.sha256(encoded).hexdigest()
    if encoded != manuscript.read_bytes():
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{manuscript.name}-",
            suffix=".tmp",
            dir=manuscript.parent,
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            temporary.write_bytes(encoded)
            if temporary.read_bytes() != encoded:
                raise OSError("主稿临时文件回读不一致")
            os.replace(temporary, manuscript)
        finally:
            if temporary.exists():
                temporary.unlink()
    return MaterializeResult(
        manuscript_path=manuscript,
        manuscript_sha256=manuscript_hash,
        source_tex_sha256={name: source.tex_sha256 for name, source in sources.items()},
        source_csv_sha256={name: source.csv_sha256 for name, source in sources.items()},
        block_count=len(_BLOCKS),
    )


__all__ = ["MaterializeResult", "materialize_paper"]

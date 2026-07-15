"""实验分析目录到论文 LaTeX 产物目录的发布工具。"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Mapping, Sequence


LATEX_FILES: Mapping[str, tuple[str, ...]] = {
    "exp1": ("exp1_numbers.tex", "exp1_tables.tex"),
    "exp2": ("exp2_numbers.tex", "exp2_tables.tex"),
}
"""每个实验必须发布的固定 LaTeX 文件名。"""


def required_latex_files(experiment: str, analysis_dir: str | Path) -> tuple[Path, ...]:
    """返回并校验指定实验的全部 LaTeX 来源文件。"""

    return _required_files(experiment, analysis_dir, LATEX_FILES, "LaTeX")


def publish_latex_outputs(
    experiment: str,
    analysis_dir: str | Path,
    output_dir: str | Path,
) -> tuple[Path, ...]:
    """把固定 LaTeX 文件逐个原子发布到目标目录。"""

    sources = required_latex_files(experiment, analysis_dir)
    return _publish_files(sources, output_dir)


def _required_files(
    experiment: str,
    analysis_dir: str | Path,
    contracts: Mapping[str, tuple[str, ...]],
    kind: str,
) -> tuple[Path, ...]:
    """按固定契约校验分析目录及其来源文件。"""

    if experiment not in contracts:
        allowed = ", ".join(sorted(contracts))
        raise ValueError(f"未知实验 {experiment!r}；仅允许：{allowed}。")
    source_dir = Path(analysis_dir).expanduser().resolve()
    if not source_dir.is_dir():
        raise NotADirectoryError(f"分析目录不存在或不是目录：{source_dir}")
    sources = tuple(source_dir / filename for filename in contracts[experiment])
    missing = [source for source in sources if not source.is_file()]
    if missing:
        names = ", ".join(source.name for source in missing)
        raise FileNotFoundError(f"{experiment} 分析目录缺少固定 {kind} 产物：{names}")
    return sources


def _publish_files(sources: Sequence[Path], output_dir: str | Path) -> tuple[Path, ...]:
    """原子复制一组已校验文件；同源目标只校验存在并直接返回。"""

    destination_dir = Path(output_dir).expanduser().resolve()
    destinations = tuple(destination_dir / source.name for source in sources)
    copies = [
        (source, destination)
        for source, destination in zip(sources, destinations, strict=True)
        if source.resolve() != destination.resolve()
    ]
    if copies:
        destination_dir.mkdir(parents=True, exist_ok=True)
    for source, destination in copies:
        _atomic_copy(source, destination)
    return destinations


def _atomic_copy(source: Path, destination: Path) -> None:
    """在目标目录内复制到临时文件，再用原子替换发布。"""

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


__all__ = ["LATEX_FILES", "publish_latex_outputs", "required_latex_files"]

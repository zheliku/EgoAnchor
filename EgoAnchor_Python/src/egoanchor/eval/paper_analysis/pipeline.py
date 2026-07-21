"""从 Stage 1 XLSX 到图表和主稿的单入口。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .figures import publish_figures
from .metrics import analyze_workbooks
from .paper import write_paper
from .settings import load_settings


_TASK_PATTERN = re.compile(r"^task_(?P<number>[1-9][0-9]*)_complete\.xlsx$")


def _validate_inputs(workbooks: tuple[Path, ...], output_root: Path) -> tuple[Path, ...]:
    """校验五本初始 workbook 的命名、唯一性和输出边界。"""

    if len(workbooks) != 5:
        raise ValueError("正式论文入口必须接收 task_1 到 task_5 五本 Stage 1 XLSX")
    normalized = tuple(path.expanduser().resolve() for path in workbooks)
    numbers: list[int] = []
    output = output_root.expanduser().resolve()
    for path in normalized:
        match = _TASK_PATTERN.match(path.name)
        if match is None:
            raise ValueError(f"输入必须使用 task_N_complete.xlsx：{path.name}")
        if not path.is_file():
            raise FileNotFoundError(path)
        if output == path or output.is_relative_to(path.parent):
            raise ValueError(f"论文输出目录不得位于 Stage 1 XLSX 目录内：{output}")
        numbers.append(int(match.group("number")))
    if sorted(numbers) != [1, 2, 3, 4, 5]:
        raise ValueError(f"输入 task 编号必须恰好覆盖 1--5：{sorted(numbers)}")
    return normalized


def build_paper(
    workbooks: tuple[Path, ...],
    output_root: Path,
    paper_root: Path,
    settings_path: Path | None = None,
) -> dict[str, Any]:
    """只读取五本 Stage 1 XLSX，发布图、表和中文主稿。"""

    normalized = _validate_inputs(workbooks, output_root)
    settings = load_settings(settings_path)
    results = analyze_workbooks(normalized, settings)
    figure_paths = publish_figures(results, paper_root.expanduser().resolve())
    paper_paths = write_paper(
        results,
        paper_root.expanduser().resolve(),
        output_root.expanduser().resolve(),
    )
    payload = {
        "passed": True,
        "input_workbooks": [str(path) for path in normalized],
        "input_sha256": dict(results.workbook_sha256),
        "figure_paths": {key: str(value) for key, value in figure_paths.items()},
        "paper_paths": {key: str(value) for key, value in paper_paths.items()},
        "performance": dict(results.performance),
    }
    provenance_root = output_root / "provenance"
    provenance_root.mkdir(parents=True, exist_ok=True)
    (provenance_root / "build_result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


__all__ = ["build_paper"]

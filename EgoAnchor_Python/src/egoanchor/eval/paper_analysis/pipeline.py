"""从 Stage 1 XLSX 到图表和主稿的单入口。"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..preprocess import verify_task_workbook
from .figures import publish_figures
from .metrics import analyze_workbooks
from .paper import write_paper
from .settings import load_settings, settings_sha256
from .xlsx import iter_rows


_TASK_PATTERN = re.compile(r"^task_(?P<number>[1-9][0-9]*)_complete\.xlsx$")

_TASK_SCENARIOS = (
    "static_head_motion",
    "start_stop_6dof",
    "continuous_translation",
    "continuous_rotation",
    "occlusion_recovery",
)
"""五本正式工作簿按文件编号对应的固定物理场景。"""

_COMMON_MANIFEST_FIELDS = (
    "config_hash",
    "frozen_parameter_set_id",
    "object_id",
    "object_model_id",
    "protocol_version",
    "run_kind",
)
"""五项任务必须共享的运行时和对象身份。"""


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
    ordered = tuple(path for _, path in sorted(zip(numbers, normalized), key=lambda item: item[0]))
    _validate_batch_identity(ordered)
    return ordered


def _validate_batch_identity(workbooks: tuple[Path, ...]) -> None:
    """复验工作簿结构，并核对五项任务来自同一冻结配置。"""

    session_ids: set[str] = set()
    common_identity: tuple[str, ...] | None = None
    for task_number, workbook in enumerate(workbooks, start=1):
        verification = verify_task_workbook(workbook)
        if not verification.passed:
            raise ValueError(f"Stage 1 工作簿完整性验证失败：{workbook}")

        manifest_rows = list(
            iter_rows(
                workbook,
                "manifest",
                ("session_id", *_COMMON_MANIFEST_FIELDS),
            )
        )
        if len(manifest_rows) != 1:
            raise ValueError(f"Stage 1 工作簿必须包含唯一 manifest 行：{workbook}")
        manifest = manifest_rows[0]
        session_id = str(manifest.get("session_id") or "")
        if not session_id or session_id in session_ids:
            raise ValueError(f"五本 Stage 1 工作簿的 session_id 必须非空且唯一：{session_id!r}")
        session_ids.add(session_id)

        identity = tuple(str(manifest.get(field) or "") for field in _COMMON_MANIFEST_FIELDS)
        if identity[-1] != "formal":
            raise ValueError(f"论文分析只接受 formal session：{workbook}")
        if any(not value for value in identity):
            raise ValueError(f"Stage 1 工作簿缺少冻结批次身份：{workbook}")
        if common_identity is None:
            common_identity = identity
        elif identity != common_identity:
            raise ValueError("五本 Stage 1 工作簿的对象、协议或冻结配置不一致")

        expected_scenario = _TASK_SCENARIOS[task_number - 1]
        completed_rows = list(
            iter_rows(
                workbook,
                "completed_trials",
                ("session_id", "scenario_id", "trial_id"),
            )
        )
        if not completed_rows or any(
            row.get("session_id") != session_id
            or row.get("scenario_id") != expected_scenario
            or not str(row.get("trial_id") or "")
            for row in completed_rows
        ):
            raise ValueError(
                f"task_{task_number} 必须只包含场景 {expected_scenario} 的最终完成 trial"
            )


def build_paper(
    workbooks: tuple[Path, ...],
    output_root: Path,
    paper_root: Path,
    manuscript_path: Path,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """只读取五本 Stage 1 XLSX，发布图、表和中文主稿。"""

    _report_progress(progress, "验证五本 XLSX")
    normalized = _validate_inputs(workbooks, output_root)
    settings = load_settings()
    _report_progress(progress, "计算实验指标")
    results = analyze_workbooks(normalized, settings)
    _report_progress(progress, "生成论文图表")
    figure_paths = publish_figures(results, paper_root.expanduser().resolve())
    _report_progress(progress, "写入指标、表格和主稿")
    paper_paths = write_paper(
        results,
        paper_root.expanduser().resolve(),
        output_root.expanduser().resolve(),
        manuscript_path.expanduser().resolve(),
    )
    payload = {
        "passed": True,
        "input_workbooks": [str(path) for path in normalized],
        "input_sha256": dict(results.workbook_sha256),
        "parameters_sha256": settings_sha256(),
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


def _report_progress(progress: Callable[[str], None] | None, message: str) -> None:
    """在调用方提供进度回调时报告论文构建阶段。"""

    if progress is not None:
        progress(message)


__all__ = ["build_paper"]

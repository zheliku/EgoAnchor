"""从 Stage 1 XLSX 到活动批次分析产物的单入口。"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from ...common import begin_build, complete_build, source_tree_sha256
from .cache import (
    cache_key,
    cache_path,
    implementation_sha256,
    load_task_results,
    write_task_results,
)
from .figures import publish_figures
from .metrics import analyze_task_workbook, merge_task_results
from .paper import write_analysis_artifacts
from .reader import workbook_sha256 as calculate_workbook_sha256
from .settings import AnalysisSettings


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
    return tuple(path for _, path in sorted(zip(numbers, normalized), key=lambda item: item[0]))


def build_analysis(
    workbooks: tuple[Path, ...],
    output_root: Path,
    figure_tex_directory: str,
    cache_root: Path,
    batch_id: str,
    workbook_sha256: Mapping[str, str],
    settings: AnalysisSettings,
    config_sha256: str,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """复用逐 task 指标缓存，发布当前五任务批次的完整论文产物。"""

    _report_progress(progress, "验证五本 XLSX")
    normalized = _validate_inputs(workbooks, output_root)
    if not batch_id.strip():
        raise ValueError("论文分析必须绑定非空 batch_id")
    if re.fullmatch(r"[0-9a-f]{64}", config_sha256) is None:
        raise ValueError("实验一/二科学参数摘要必须是小写 SHA-256")
    expected_paths = {str(path) for path in normalized}
    if set(workbook_sha256) != expected_paths:
        raise ValueError("batch manifest 的 workbook SHA 映射必须恰好覆盖 task_1 到 task_5")

    frozen_digests: dict[str, str] = {}
    for workbook in normalized:
        expected_digest = str(workbook_sha256[str(workbook)]).lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
            raise ValueError(f"batch manifest 的 workbook SHA-256 非法：{workbook.name}")
        frozen_digests[workbook.name] = expected_digest

    implementation_digest = source_tree_sha256(Path(__file__).resolve().parent)
    building = begin_build(
        output_root,
        owner="experiment_1_2",
        source_kind="formal",
        inputs=(
            {
                "key": f"task_{number}",
                "path": str(workbook),
                "sha256": frozen_digests[workbook.name],
            }
            for number, workbook in enumerate(normalized, start=1)
        ),
        config_sha256=config_sha256,
        implementation_sha256=implementation_digest,
        details={"batch_id": batch_id},
    )
    task_results = []
    cache_states: dict[str, str] = {}
    for task_number, workbook in enumerate(normalized, start=1):
        frozen_digest = frozen_digests[workbook.name]
        key = cache_key(frozen_digest, config_sha256)
        destination = cache_path(cache_root, workbook)
        result = load_task_results(destination, key, workbook)
        if result is None:
            _report_progress(progress, f"Task {task_number}: 重建指标缓存")
            actual_digest = calculate_workbook_sha256(workbook)
            if actual_digest != frozen_digest:
                raise ValueError(f"Stage 1 workbook 与 batch manifest 摘要不一致：{workbook.name}")
            result = analyze_task_workbook(
                workbook,
                settings,
                known_sha256=actual_digest,
            )
            write_task_results(destination, key, result)
            cache_states[workbook.name] = "rebuilt"
        else:
            _report_progress(progress, f"Task {task_number}: 使用指标缓存")
            cache_states[workbook.name] = "hit"
        task_results.append(result)

    results = merge_task_results(tuple(task_results))
    _report_progress(progress, "生成本地论文图表")
    figure_paths = publish_figures(results, output_root.expanduser().resolve())
    _report_progress(progress, "写入本地指标、表格和 TeX")
    artifact_paths = write_analysis_artifacts(
        results,
        output_root.expanduser().resolve(),
        figure_tex_directory,
    )
    details = {
        "batch_id": batch_id,
        "metrics_implementation_sha256": implementation_sha256(),
        "task_cache": cache_states,
        "performance": dict(results.performance),
    }
    outputs = [
        {"key": key, "kind": value.suffix.lower().lstrip("."), "path": str(value)}
        for key, value in sorted(figure_paths.items())
    ]
    outputs.extend(
        {"key": key, "kind": value.suffix.lower().lstrip("."), "path": str(value)}
        for key, value in sorted(artifact_paths.items())
    )
    manifest = complete_build(output_root, building, outputs=outputs, details=details)
    return {
        "passed": True,
        "build": manifest,
        "task_cache": cache_states,
        "performance": dict(results.performance),
    }


def _report_progress(progress: Callable[[str], None] | None, message: str) -> None:
    """在调用方提供进度回调时报告论文构建阶段。"""

    if progress is not None:
        progress(message)


__all__ = ["build_analysis"]

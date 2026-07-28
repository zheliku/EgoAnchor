"""实验一/二的状态、门禁、分析构建和论文资源计划。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...preprocess import file_sha256
from ..common import (
    ArtifactPlan,
    PlannedAsset,
    read_build_manifest,
    source_tree_sha256,
    validate_output_files,
)
from .data import (
    _BATCH_MANIFEST_NAME,
    _report_progress,
    _stage_progress,
    active_batch_id,
    load_active_batch,
    preprocess_current,
    validate_active_data,
)
from .pipeline import build_analysis
from .settings import load_batch_paths, settings_sha256


_EXPERIMENT_FIGURE_KEYS = frozenset(
    f"figure{figure}{panel}_{suffix}"
    for figure in (2, 3)
    for panel in "abcd"
    for suffix in ("pdf", "png")
)
"""一次完整构建必须声明的实验一/二面板键。"""


def describe_workflow(root: Path | None = None) -> dict[str, Any]:
    """返回实验一/二配置、活动批次和统一生命周期状态。"""

    paths = load_batch_paths(root)
    active = paths.active_root
    build_path = active / "analysis" / "provenance" / "build_result.json"
    build: dict[str, Any] = {"status": "missing"}
    if build_path.is_file():
        try:
            manifest = read_build_manifest(active / "analysis", owner="experiment_1_2")
        except (OSError, ValueError) as error:
            build = {"status": "invalid", "reason": str(error)}
        else:
            build = {
                "build_id": manifest["build_id"],
                "status": manifest["status"],
                "source_kind": manifest["source_kind"],
            }
    return {
        "passed": True,
        "target": "exp1-2",
        "configs": {
            "batch": str(paths.batch_config_path),
            "paper": str(paths.paper_config_path),
        },
        "paths": {
            "task_data_root": str(paths.task_data_root),
            "task_workbook_root": str(paths.task_workbook_root),
            "task_analysis_root": str(paths.task_analysis_root),
            "staging_root": str(paths.staging_root),
            "archive_root": str(paths.archive_root),
            "active_root": str(active),
            "paper_root": str(paths.paper_root),
            "experiment_asset_destination": str(paths.experiment_asset_destination),
            "table_destinations": [
                {
                    "artifact_key": item.artifact_key,
                    "destination": str(item.destination),
                }
                for item in paths.table_destinations
            ],
            "relay_assets": [
                {"source": str(asset.source), "destination": str(asset.destination)}
                for asset in paths.relay_assets
            ],
        },
        "active_batch": active_batch_id(active),
        "build": build,
        "operations": {
            "data_sessions": {
                "input": str(paths.task_data_root),
                "output": "stdout JSON",
            },
            "data_stage": {
                "input": str(paths.task_data_root / "task_<N>_v<V>_<time>_<object>"),
                "output": [
                    str(paths.task_workbook_root / "task_<N>_v<V>_<time>_<object>"),
                    str(paths.staging_root / "<batch_id>" / _BATCH_MANIFEST_NAME),
                ],
            },
            "data_promote": {
                "input": str(paths.staging_root / "<batch_id>"),
                "output": str(active),
            },
            "validate": {
                "input": str(active / _BATCH_MANIFEST_NAME),
                "output": "stdout JSON；按活动清单对五个 task_data 原始目录执行完整 QC",
            },
            "data_preprocess": {
                "input": str(active / _BATCH_MANIFEST_NAME),
                "output": str(paths.task_workbook_root),
            },
            "analyze": {
                "input": str(active / _BATCH_MANIFEST_NAME),
                "output": [
                    str(active / "analysis"),
                    str(paths.task_analysis_root),
                ],
                "note": "只生成活动批次内的图、表和 TeX，不修改论文目录或主稿",
            },
            "copy-assets": {
                "input": [
                    str(active / "analysis" / "figures"),
                    str(active / "analysis" / "tex" / "tables"),
                    *[str(asset.source) for asset in paths.relay_assets],
                ],
                "output": [
                    str(paths.experiment_asset_destination),
                    *[str(item.destination) for item in paths.table_destinations],
                    *[str(asset.destination) for asset in paths.relay_assets],
                ],
                "note": "复制构建清单中的图、表和显式 relay，不改写主稿",
            },
        },
    }


def validate_workflow(*, root: Path | None = None) -> dict[str, Any]:
    """按活动清单对五个原始任务显式执行完整硬 QC。"""

    _report_progress("qc: 检查当前活动批次")
    paths = load_batch_paths(root)
    summaries, reports = validate_active_data(paths)
    return {
        "passed": all(report.passed for report in reports),
        "task_data_root": str(paths.task_data_root),
        "sessions": [summary.to_dict() for summary in summaries],
        "tasks": [report.to_dict() for report in reports],
    }


def analyze_workflow(
    *,
    root: Path | None = None,
    rebuild: bool = False,
) -> dict[str, Any]:
    """从当前五本工作簿生成活动批次内的指标、图表和 TeX。"""

    paths = load_batch_paths(root)
    rebuilt_workbooks: dict[str, str] | None = None
    if rebuild:
        _report_progress("analyze: 强制重建五项任务缓存")
        preprocess_result = preprocess_current(root=paths.project_root, force=True)
        rebuilt_workbooks = dict(preprocess_result["workbook_sha256"])
    active = paths.active_root
    batch_id, records = load_active_batch(paths)
    workbooks = tuple(
        paths.task_workbook_root / record.workbook_relative_path for record in records
    )
    workbook_sha256 = {
        str(path): record.workbook_sha256
        for path, record in zip(workbooks, records, strict=True)
    }
    figure_tex_directory = paths.experiment_asset_destination.relative_to(
        paths.paper_root
    ).as_posix()
    with _stage_progress("analyze", 8, "stage") as progress:

        def update_analysis_progress(message: str) -> None:
            """更新论文分析的当前阶段。"""

            progress.set_postfix_str(message)
            progress.update()

        payload = build_analysis(
            workbooks,
            active / "analysis",
            figure_tex_directory,
            cache_root=paths.task_analysis_root,
            batch_id=batch_id,
            workbook_sha256=workbook_sha256,
            progress=update_analysis_progress,
        )
    result = {
        "passed": True,
        "analysis": payload,
        "next_command": "pixi run eval copy-assets exp1-2",
    }
    if rebuilt_workbooks is not None:
        result["workbook_sha256"] = rebuilt_workbooks
    return result


def plan_assets(*, root: Path | None = None) -> ArtifactPlan:
    """预检实验一/二当前分析并返回不写文件的完整资源计划。"""

    paths = load_batch_paths(root)
    batch_id, records = load_active_batch(paths)
    analysis_root = paths.active_root / "analysis"
    figure_root = analysis_root / "figures"
    if not figure_root.is_dir():
        raise FileNotFoundError(
            f"尚未生成当前批次图片，请先运行 analyze exp1-2：{figure_root}"
        )
    build_result = read_build_manifest(analysis_root, owner="experiment_1_2")
    if build_result.get("status") != "complete" or build_result.get("source_kind") != "formal":
        raise ValueError("实验一/二构建尚未完整完成，拒绝复制论文资源")
    details = build_result.get("details")
    if not isinstance(details, dict) or details.get("batch_id") != batch_id:
        raise ValueError("当前 analysis 不属于活动批次，请先运行 analyze exp1-2")
    if build_result.get("config_sha256") != settings_sha256():
        raise ValueError("实验一/二分析参数已变化，请重新运行 analyze exp1-2")
    implementation_root = Path(__file__).resolve().parent
    if build_result.get("implementation_sha256") != source_tree_sha256(implementation_root):
        raise ValueError("实验一/二分析实现已变化，请重新运行 analyze exp1-2")
    expected_inputs = {
        f"task_{record.task_number}": {
            "path": str(
                (paths.task_workbook_root / record.workbook_relative_path).resolve()
            ),
            "sha256": record.workbook_sha256,
        }
        for record in records
    }
    actual_inputs = {
        str(item.get("key")): {
            "path": str(item.get("path")),
            "sha256": str(item.get("sha256")),
        }
        for item in build_result.get("inputs", [])
        if isinstance(item, dict)
    }
    if actual_inputs != expected_inputs:
        raise ValueError("实验一/二构建输入与活动批次不一致，请重新运行 analyze exp1-2")

    outputs = validate_output_files(build_result)
    if not _EXPERIMENT_FIGURE_KEYS.issubset(outputs):
        raise ValueError("当前 analysis 的图片清单必须恰好覆盖图二和图三的八个 PNG/PDF 面板")
    resolved_figure_root = figure_root.resolve()
    resolved_table_root = (analysis_root / "tex" / "tables").resolve()
    copies: list[PlannedAsset] = []
    for key in sorted(_EXPERIMENT_FIGURE_KEYS):
        figure_output = outputs[key]
        source = Path(figure_output["path"]).expanduser().resolve()
        expected_suffix = f".{key.rsplit('_', 1)[1]}"
        if source.parent != resolved_figure_root or source.suffix.lower() != expected_suffix:
            raise ValueError(f"当前分析图片清单越界或后缀不匹配：{key}: {source}")
        copies.append(
            PlannedAsset(
                owner="experiment_1_2",
                key=key,
                source=source,
                destination=paths.experiment_asset_destination / source.name,
                expected_sha256=figure_output["sha256"],
            )
        )
    for item in paths.table_destinations:
        table_output = outputs.get(item.artifact_key)
        if table_output is None:
            raise ValueError(f"当前 analysis 缺少表格产物：{item.artifact_key}")
        source = Path(table_output["path"]).expanduser().resolve()
        if source.parent != resolved_table_root or source.suffix.lower() != ".tex":
            raise ValueError(f"当前分析表格清单越界或后缀不匹配：{item.artifact_key}: {source}")
        copies.append(
            PlannedAsset(
                owner="experiment_1_2",
                key=item.artifact_key,
                source=source,
                destination=item.destination,
                expected_sha256=table_output["sha256"],
            )
        )
    copies.extend(
        PlannedAsset(
            owner="experiment_1_2",
            key=f"relay_{index}",
            source=item.source,
            destination=item.destination,
            expected_sha256=file_sha256(item.source),
        )
        for index, item in enumerate(paths.relay_assets, start=1)
    )
    return ArtifactPlan(owner="experiment_1_2", assets=tuple(copies))


__all__ = [
    "analyze_workflow",
    "describe_workflow",
    "plan_assets",
    "validate_workflow",
]

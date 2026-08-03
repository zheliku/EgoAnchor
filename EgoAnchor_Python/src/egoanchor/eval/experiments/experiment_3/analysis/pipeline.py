"""实验三从原始工作簿到本地分析产物的构建管线。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ...._filesystem import (
    create_inherited_temp_directory,
    remove_tree_with_retry,
    replace_directory_with_rollback,
)
from ...common import begin_build, complete_build, source_trees_sha256
from .artifacts import EXP3_ARTIFACTS
from .contracts import PRIMARY_OUTCOMES, SCALE_OUTCOMES
from .figures import publish_figures
from .paper import write_subjective_table
from .reader import read_workbook, validate_for_analysis
from .scoring import derive_scores
from .settings import AnalysisSettings
from .summaries import analyze_scores
from .workbook import write_results_workbook


def build_analysis(
    settings: AnalysisSettings,
    *,
    input_workbook: Path,
    output_root: Path,
    project_root: Path,
    config_sha256: str,
    batch_config_path: Path,
    paper_config_path: Path,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """一次完成计分、推断、结果工作簿、TeX 和论文图。"""

    source = input_workbook.expanduser().resolve()
    root = output_root.expanduser().resolve()
    _validate_output_root(root, project_root.expanduser().resolve())
    _report_progress(progress, "读取并验证原始工作簿")
    data = read_workbook(source)
    validation = validate_for_analysis(
        data,
        aq_mode=settings.aq_mode,
        q10_enabled=settings.q10_enabled,
    )
    _report_progress(progress, "计算区块、量表和参与者配对分")
    scores = derive_scores(data, settings)
    validate_complete_pair_counts(scores.paired_scores, settings.minimum_participants)
    _report_progress(progress, "计算 Wilcoxon、Holm、效应量、信度与操纵描述")
    tables = analyze_scores(data, scores, settings)
    details = {
        "included_count": validation["included_count"],
        "artifact_contract_version": EXP3_ARTIFACTS.version,
    }
    implementation_root = Path(__file__).resolve().parent
    implementation_digest = source_trees_sha256(
        {
            "analysis": implementation_root,
            "visuals": implementation_root.parents[3] / "visuals",
        }
    )
    staging = create_inherited_temp_directory(root.parent, f".{root.name}.build-")
    try:
        building = begin_build(
            staging,
            owner="experiment_3",
            source_kind="raw_workbook",
            inputs=(
                {
                    "key": "raw_workbook",
                    "path": data.source_path,
                    "sha256": data.source_sha256,
                },
            ),
            config_sha256=config_sha256,
            implementation_sha256=implementation_digest,
            details=details,
        )
        _report_progress(progress, "写入并回读验证结果工作簿")
        results_path = EXP3_ARTIFACTS.results_workbook.path_under(staging)
        write_results_workbook(
            results_path,
            data=data,
            tables=tables,
            settings=settings,
            settings_sha256=config_sha256,
            batch_config_path=batch_config_path,
            paper_config_path=paper_config_path,
            validation=validation,
        )
        tex_path = write_subjective_table(
            EXP3_ARTIFACTS.subjective_table.path_under(staging),
            tables.results,
        )
        _report_progress(progress, "从同一批内存结果生成论文图")
        figures = publish_figures(
            scores,
            tables,
            staging,
            settings,
        )
        paths_by_key = {
            EXP3_ARTIFACTS.results_workbook.key: results_path,
            EXP3_ARTIFACTS.subjective_table.key: tex_path,
            **figures,
        }
        expected_keys = {artifact.key for artifact in EXP3_ARTIFACTS.outputs}
        if set(paths_by_key) != expected_keys:
            raise ValueError("实验三构建产物与冻结产物契约不一致")
        outputs = [
            {
                "key": artifact.key,
                "kind": artifact.kind,
                "path": str(paths_by_key[artifact.key]),
            }
            for artifact in EXP3_ARTIFACTS.outputs
        ]
        manifest = complete_build(
            staging,
            building,
            outputs=outputs,
            warnings=validation["warnings"],
            details=details,
            published_root=root,
        )
        replace_directory_with_rollback(staging, root)
    except Exception:
        remove_tree_with_retry(staging)
        raise
    return {"passed": True, "build": manifest}


def validate_complete_pair_counts(paired_scores: Any, minimum: int) -> dict[str, int]:
    """要求十二项冻结结局各自达到参与者级完整配对下限。"""

    expected = (*PRIMARY_OUTCOMES, *SCALE_OUTCOMES)
    required_columns = {"Participant_ID", "Outcome"}
    if not required_columns.issubset(paired_scores.columns):
        raise ValueError("实验三配对分缺少 Participant_ID 或 Outcome，无法执行逐结局样本量门禁")
    selected = paired_scores.loc[
        paired_scores["Outcome"].astype(str).isin(expected),
        ["Participant_ID", "Outcome"],
    ].copy()
    selected["Participant_ID"] = selected["Participant_ID"].astype(str)
    selected["Outcome"] = selected["Outcome"].astype(str)
    if selected.duplicated(["Participant_ID", "Outcome"]).any():
        raise ValueError("实验三逐结局样本量门禁发现重复的参与者×结局配对")
    counts = {
        outcome: int((selected["Outcome"] == outcome).sum())
        for outcome in expected
    }
    insufficient: list[str] = []
    for outcome, count in counts.items():
        if count < minimum:
            insufficient.append(f"{outcome} N={count}")
    if insufficient:
        raise ValueError(
            f"十二项冻结结局均须至少有 {minimum} 个完整配对；不足项："
            + "，".join(insufficient)
        )
    return counts


def _validate_output_root(root: Path, project_root: Path) -> None:
    """限制实验三分析输出位于 EgoAnchor_Python/data。"""

    data_root = (project_root / "data").resolve()
    if not root.is_relative_to(data_root):
        raise ValueError(f"实验三输出必须位于 {data_root} 内：{root}")
    relative = root.relative_to(data_root)
    if len(relative.parts) < 2 or root.name != "analysis":
        raise ValueError(f"实验三事务发布目标必须是 data 下的专用 analysis 目录：{root}")


def _report_progress(callback: Callable[[str], None] | None, message: str) -> None:
    """存在回调时报告当前分析阶段。"""

    if callback is not None:
        callback(message)


__all__ = ["build_analysis", "validate_complete_pair_counts"]

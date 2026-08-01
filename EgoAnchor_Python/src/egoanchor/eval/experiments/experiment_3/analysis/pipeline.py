"""实验三从原始工作簿到本地分析产物的构建管线。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ...common import begin_build, complete_build, source_tree_sha256
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
    allow_synthetic: bool = False,
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
        minimum_participants=settings.minimum_participants,
        aq_mode=settings.aq_mode,
        q10_enabled=settings.q10_enabled,
        approved_response_fingerprints=settings.approved_response_fingerprints,
        allow_synthetic=allow_synthetic,
    )
    implementation_digest = source_tree_sha256(Path(__file__).resolve().parent)
    building = begin_build(
        root,
        owner="experiment_3",
        source_kind=data.source_kind,
        inputs=(
            {
                "key": "raw_workbook",
                "path": data.source_path,
                "sha256": data.source_sha256,
            },
        ),
        config_sha256=config_sha256,
        implementation_sha256=implementation_digest,
        details={"included_count": validation["included_count"]},
    )
    _report_progress(progress, "计算区块、量表和参与者配对分")
    scores = derive_scores(data, settings)
    _report_progress(progress, "计算 Wilcoxon、Holm、效应量、信度与操纵描述")
    tables = analyze_scores(data, scores, settings)
    _report_progress(progress, "写入并回读验证结果工作簿")
    results_path = root / "results" / "experiment3_analysis.xlsx"
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
    paper_eligible = bool(validation["paper_eligible"])
    tex_path = write_subjective_table(
        root / "tex" / "exp3_subjective.tex",
        tables.results,
        paper_eligible=paper_eligible,
    )
    _report_progress(progress, "从同一批内存结果生成论文图")
    figures = publish_figures(
        scores,
        tables,
        root,
        settings,
        paper_eligible=paper_eligible,
    )
    details = {
        "included_count": validation["included_count"],
        "paper_eligible": paper_eligible,
        "response_fingerprint": validation["response_fingerprint"],
        "source_gate_reason": validation["source_gate_reason"],
    }
    outputs = [
        {"key": "results_workbook", "kind": "xlsx", "path": str(results_path)},
        {"key": "subjective_table", "kind": "tex", "path": str(tex_path)},
    ]
    outputs.extend(
        {
            "key": key,
            "kind": value.suffix.lower().lstrip("."),
            "path": str(value),
        }
        for key, value in sorted(figures.items())
    )
    manifest = complete_build(
        root,
        building,
        outputs=outputs,
        warnings=validation["warnings"],
        details=details,
    )
    return {"passed": True, "build": manifest}


def _validate_output_root(root: Path, project_root: Path) -> None:
    """限制实验三分析输出位于 EgoAnchor_Python/data。"""

    data_root = (project_root / "data").resolve()
    if not root.is_relative_to(data_root):
        raise ValueError(f"实验三输出必须位于 {data_root} 内：{root}")


def _report_progress(callback: Callable[[str], None] | None, message: str) -> None:
    """存在回调时报告当前分析阶段。"""

    if callback is not None:
        callback(message)


__all__ = ["build_analysis"]

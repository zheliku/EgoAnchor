"""实验三从正式原始工作簿到结果、图和论文资源的单入口。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..common import (
    ArtifactPlan,
    PlannedAsset,
    begin_build,
    build_manifest_path,
    complete_build,
    file_sha256,
    read_build_manifest,
    source_tree_sha256,
    validate_output_files,
)
from .clmm import fit_item_models
from .figures import publish_figures
from .paper import write_subjective_table
from .reader import describe_workbook, read_workbook, validate_for_analysis
from .scoring import derive_scores
from .settings import load_settings, settings_sha256
from .summaries import analyze_scores
from .template import build_raw_template
from .workbook import write_results_workbook


def describe_experiment3() -> dict[str, Any]:
    """显示实验三生效配置、固定路径和当前输入进度。"""

    settings = load_settings()
    payload: dict[str, Any] = {
        "passed": True,
        "configs": {
            "batch": str(settings.paths.batch_config_path),
            "paper": str(settings.paths.paper_config_path),
        },
        "config_sha256": settings_sha256(),
        "input_workbook": str(settings.paths.input_workbook),
        "output_root": str(settings.paths.output_root),
        "paper_figure_destination": str(settings.paths.figure_destination),
        "paper_table_destination": str(settings.paths.table_destination),
        "aq_mode": settings.aq_mode,
        "q10_enabled": settings.q10_enabled,
        "tost_enabled": settings.equivalence_enabled,
        "clmm_enabled": settings.clmm_enabled,
    }
    if settings.paths.input_workbook.is_file():
        payload["workbook"] = describe_workbook(read_workbook(settings.paths.input_workbook))
    else:
        payload["workbook"] = {"passed": False, "reason": "原始模板尚未生成"}
    manifest_path = build_manifest_path(settings.paths.output_root)
    if manifest_path.is_file():
        try:
            manifest = read_build_manifest(settings.paths.output_root, owner="experiment_3")
        except (OSError, ValueError) as error:
            payload["build"] = {"status": "invalid", "reason": str(error)}
        else:
            payload["build"] = {
                "build_id": manifest["build_id"],
                "status": manifest["status"],
                "source_kind": manifest["source_kind"],
            }
    else:
        payload["build"] = {"status": "missing"}
    return payload


def create_template(*, destination: Path | None = None) -> dict[str, Any]:
    """生成正式空白原始工作簿，并立即回读结构。"""

    settings = load_settings()
    output_path = (destination or settings.paths.input_workbook).expanduser().resolve()
    repository_root = settings.paths.project_root.parent.resolve()
    if not output_path.is_relative_to(repository_root):
        raise ValueError(f"实验三正式模板必须生成在仓库内：{output_path}")
    if output_path.exists():
        raise FileExistsError(f"拒绝覆盖已有实验三原始工作簿：{output_path}")
    output = build_raw_template(settings, destination)
    data = read_workbook(output)
    return {"passed": True, "template": str(output), "workbook": describe_workbook(data)}


def validate_input(
    *,
    input_workbook: Path | None = None,
    require_complete: bool = False,
    allow_synthetic: bool = False,
) -> dict[str, Any]:
    """验证工作簿结构；可选进一步要求达到正式分析完整性。"""

    settings = load_settings()
    source = input_workbook or settings.paths.input_workbook
    data = read_workbook(source)
    payload = describe_workbook(data)
    if require_complete:
        payload["analysis_readiness"] = validate_for_analysis(
            data,
            minimum_participants=settings.minimum_participants,
            aq_mode=settings.aq_mode,
            q10_enabled=settings.q10_enabled,
            allow_synthetic=allow_synthetic,
        )
    return payload


def analyze_experiment3(
    *,
    input_workbook: Path | None = None,
    output_root: Path | None = None,
    allow_synthetic: bool = False,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """一次完成计分、推断、CLMM、结果工作簿、TeX 和论文图。"""

    settings = load_settings()
    source = (input_workbook or settings.paths.input_workbook).expanduser().resolve()
    root = (output_root or settings.paths.output_root).expanduser().resolve()
    _validate_output_root(root, settings.paths.project_root)
    _progress(progress, "读取并验证原始工作簿")
    data = read_workbook(source)
    validation = validate_for_analysis(
        data,
        minimum_participants=settings.minimum_participants,
        aq_mode=settings.aq_mode,
        q10_enabled=settings.q10_enabled,
        allow_synthetic=allow_synthetic,
    )
    config_digest = settings_sha256()
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
        config_sha256=config_digest,
        implementation_sha256=implementation_digest,
        details={"included_count": validation["included_count"]},
    )
    _progress(progress, "计算区块、量表和参与者配对分")
    scores = derive_scores(data, settings)
    _progress(progress, "计算 Wilcoxon、Holm、效应量、信度与操纵描述")
    tables = analyze_scores(data, scores, settings)
    clmm_coefficients, clmm_contrasts = fit_item_models(
        scores.block_scores,
        settings,
        progress=progress,
    )
    _progress(progress, "写入并回读验证结果工作簿")
    results_path = root / "results" / "experiment3_analysis.xlsx"
    write_results_workbook(
        results_path,
        data=data,
        scores=scores,
        tables=tables,
        clmm_coefficients=clmm_coefficients,
        clmm_contrasts=clmm_contrasts,
        settings=settings,
        settings_sha256=config_digest,
        validation=validation,
    )
    tex_path = write_subjective_table(root / "tex" / "exp3_subjective.tex", tables.primary, tables.scales)
    _progress(progress, "从结果工作簿生成论文图")
    figures = publish_figures(results_path, root, settings)
    details = {
        "included_count": validation["included_count"],
        "clmm_models": int(clmm_coefficients["Outcome"].nunique()) if not clmm_coefficients.empty else 0,
        "clmm_converged": int(
            clmm_coefficients.groupby("Outcome")["Converged"].first().fillna(False).sum()
        ) if not clmm_coefficients.empty else 0,
    }
    outputs = [
        {"key": "results_workbook", "kind": "xlsx", "path": str(results_path)},
        {"key": "subjective_table", "kind": "tex", "path": str(tex_path)},
    ]
    outputs.extend(
        {"key": key, "kind": value.suffix.lower().lstrip("."), "path": str(value)}
        for key, value in sorted(figures.items())
    )
    manifest = complete_build(
        root,
        building,
        outputs=outputs,
        warnings=validation["warnings"],
        details=details,
    )
    return {
        "passed": True,
        "build": manifest,
        "next_command": "pixi run eval publish exp3",
    }


def plan_publication() -> ArtifactPlan | None:
    """存在完整正式构建时，返回不写文件的实验三发布计划。"""

    settings = load_settings()
    manifest_path = build_manifest_path(settings.paths.output_root)
    if not manifest_path.is_file():
        return None
    manifest = read_build_manifest(settings.paths.output_root, owner="experiment_3")
    if manifest.get("status") != "complete":
        raise ValueError("实验三构建尚未完整完成，拒绝 publish")
    if manifest.get("source_kind") != "formal":
        raise ValueError("实验三合成/模拟构建不得发布到论文目录")
    if manifest.get("config_sha256") != settings_sha256():
        raise ValueError("实验三配置已变化，请重新运行 analyze exp3")
    if manifest.get("implementation_sha256") != source_tree_sha256(Path(__file__).resolve().parent):
        raise ValueError("实验三分析实现已变化，请重新运行 analyze exp3")
    inputs = manifest.get("inputs")
    if not isinstance(inputs, list) or len(inputs) != 1 or not isinstance(inputs[0], dict):
        raise ValueError("实验三构建必须恰好声明一个原始工作簿")
    input_path = Path(str(inputs[0].get("path", ""))).expanduser().resolve()
    if input_path != settings.paths.input_workbook.resolve():
        raise ValueError("实验三构建没有使用配置固定的正式原始工作簿")
    if not input_path.is_file() or file_sha256(input_path) != inputs[0].get("sha256"):
        raise ValueError("实验三原始输入已变化，请重新运行 analyze exp3")
    outputs = validate_output_files(manifest)
    figure_root = (settings.paths.output_root / "figures").resolve()
    expected_figure_names = {
        "paired_png": "figure4_exp3_paired.png",
        "paired_pdf": "figure4_exp3_paired.pdf",
        "scales_png": "figure5_exp3_scales.png",
        "scales_pdf": "figure5_exp3_scales.pdf",
    }
    assets: list[PlannedAsset] = []
    for key, expected_name in expected_figure_names.items():
        output = outputs.get(key)
        if output is None:
            raise ValueError(f"实验三构建缺少图片来源清单：{key}")
        source = Path(output["path"]).expanduser().resolve()
        if source.parent != figure_root or source.name != expected_name:
            raise ValueError(f"实验三图片来源越界或文件名不匹配：{key}: {source}")
        assets.append(
            PlannedAsset(
                owner="experiment_3",
                key=key,
                source=source,
                destination=settings.paths.figure_destination / source.name,
                expected_sha256=output["sha256"],
            )
        )
    tex_output = outputs.get("subjective_table")
    if tex_output is None:
        raise ValueError("实验三构建缺少主观结果表")
    tex = Path(tex_output["path"]).expanduser().resolve()
    expected_tex = (settings.paths.output_root / "tex" / "exp3_subjective.tex").resolve()
    if tex != expected_tex:
        raise ValueError(f"实验三 TeX 来源越界或文件名不匹配：{tex}")
    assets.append(
        PlannedAsset(
            owner="experiment_3",
            key="subjective_table",
            source=tex,
            destination=settings.paths.table_destination,
            expected_sha256=tex_output["sha256"],
        )
    )
    return ArtifactPlan(owner="experiment_3", assets=tuple(assets))


def _validate_output_root(root: Path, project_root: Path) -> None:
    """限制实验三分析输出位于 EgoAnchor_Python/data。"""

    data_root = (project_root / "data").resolve()
    if not root.is_relative_to(data_root):
        raise ValueError(f"实验三输出必须位于 {data_root} 内：{root}")


def _progress(callback: Callable[[str], None] | None, message: str) -> None:
    """存在回调时报告当前分析阶段。"""

    if callback is not None:
        callback(message)


__all__ = [
    "analyze_experiment3",
    "create_template",
    "describe_experiment3",
    "plan_publication",
    "validate_input",
]

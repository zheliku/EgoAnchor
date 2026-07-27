"""实验三从正式原始工作簿到结果、图和论文资源的单入口。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..common import ArtifactPlan, PlannedAsset, publish_artifact_plans
from .clmm import fit_item_models
from .figures import publish_figures
from .paper import write_subjective_table
from .reader import describe_workbook, read_workbook, validate_for_analysis
from .scoring import derive_scores
from .settings import load_settings, settings_sha256
from .summaries import analyze_scores
from .template import build_raw_template
from .workbook import write_results_workbook


_BUILD_RESULT = "build_result.json"
"""实验三分析与发布共同读取的来源清单文件名。"""


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
    return payload


def create_template(*, destination: Path | None = None) -> dict[str, Any]:
    """生成正式空白原始工作簿，并立即回读结构。"""

    settings = load_settings()
    output_path = (destination or settings.paths.input_workbook).expanduser().resolve()
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
    """从原始值独立重算计分、推断、CLMM 与结果工作簿。"""

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
    config_digest = settings_sha256()
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
    payload: dict[str, Any] = {
        "passed": True,
        "status": "analyzed",
        "source_kind": data.source_kind,
        "input_workbook": data.source_path,
        "input_sha256": data.source_sha256,
        "configs": {
            "batch": str(settings.paths.batch_config_path),
            "paper": str(settings.paths.paper_config_path),
        },
        "config_sha256": config_digest,
        "included_count": validation["included_count"],
        "results_workbook": str(results_path),
        "results_sha256": _sha256(results_path),
        "tex_path": str(tex_path),
        "tex_sha256": _sha256(tex_path),
        "clmm_models": int(clmm_coefficients["Outcome"].nunique()) if not clmm_coefficients.empty else 0,
        "clmm_converged": int(
            clmm_coefficients.groupby("Outcome")["Converged"].first().fillna(False).sum()
        ) if not clmm_coefficients.empty else 0,
        "warnings": list(validation["warnings"]),
        "next_command": "pixi run eval experiment3 plot",
    }
    _write_manifest(root, payload)
    return payload


def plot_experiment3(
    *,
    output_root: Path | None = None,
) -> dict[str, Any]:
    """从结果 XLSX 回读绘图数据并发布 PNG/PDF。"""

    settings = load_settings()
    root = (output_root or settings.paths.output_root).expanduser().resolve()
    manifest = _read_manifest(root)
    results = Path(str(manifest.get("results_workbook", ""))).expanduser().resolve()
    if not results.is_file() or _sha256(results) != manifest.get("results_sha256"):
        raise ValueError("实验三结果工作簿缺失或已变化，请先重新运行 analyze")
    figures = publish_figures(results, root, settings)
    manifest["status"] = "complete"
    manifest["figure_paths"] = {key: str(value) for key, value in figures.items()}
    manifest["figure_sha256"] = {key: _sha256(value) for key, value in figures.items()}
    manifest["next_command"] = "pixi run eval copy-assets"
    _write_manifest(root, manifest)
    return {
        "passed": True,
        "source_results": str(results),
        "figure_paths": manifest["figure_paths"],
        "next_command": manifest["next_command"],
    }


def plan_experiment3_assets_if_ready() -> ArtifactPlan | None:
    """存在完整正式构建时，返回不写文件的实验三发布计划。"""

    settings = load_settings()
    manifest_path = settings.paths.output_root / "provenance" / _BUILD_RESULT
    if not manifest_path.is_file():
        return None
    manifest = _read_manifest(settings.paths.output_root)
    if manifest.get("status") != "complete":
        raise ValueError("实验三构建尚未完成 plot，拒绝 copy-assets")
    if manifest.get("source_kind") != "formal":
        raise ValueError("实验三合成/模拟构建不得发布到论文目录")
    if manifest.get("config_sha256") != settings_sha256():
        raise ValueError("实验三配置已变化，请重新运行 analyze 与 plot")
    input_path = Path(str(manifest.get("input_workbook", ""))).expanduser().resolve()
    if not input_path.is_file() or _sha256(input_path) != manifest.get("input_sha256"):
        raise ValueError("实验三原始输入已变化，请重新运行 analyze 与 plot")
    figure_paths = manifest.get("figure_paths")
    figure_hashes = manifest.get("figure_sha256")
    if not isinstance(figure_paths, dict) or not isinstance(figure_hashes, dict):
        raise ValueError("实验三构建缺少图片来源清单")
    figure_root = (settings.paths.output_root / "figures").resolve()
    expected_figure_names = {
        "paired_png": "figure4_exp3_paired.png",
        "paired_pdf": "figure4_exp3_paired.pdf",
        "scales_png": "figure5_exp3_scales.png",
        "scales_pdf": "figure5_exp3_scales.pdf",
    }
    assets: list[PlannedAsset] = []
    for key, expected_name in expected_figure_names.items():
        source = Path(str(figure_paths.get(key, ""))).expanduser().resolve()
        if source.parent != figure_root or source.name != expected_name:
            raise ValueError(f"实验三图片来源越界或文件名不匹配：{key}: {source}")
        if not source.is_file() or _sha256(source) != figure_hashes.get(key):
            raise ValueError(f"实验三图片缺失或已变化：{key}")
        assets.append(
            PlannedAsset(
                owner="experiment_3",
                key=key,
                source=source,
                destination=settings.paths.figure_destination / source.name,
                expected_sha256=str(figure_hashes[key]),
            )
        )
    tex = Path(str(manifest.get("tex_path", ""))).expanduser().resolve()
    expected_tex = (settings.paths.output_root / "tex" / "exp3_subjective.tex").resolve()
    if tex != expected_tex:
        raise ValueError(f"实验三 TeX 来源越界或文件名不匹配：{tex}")
    if not tex.is_file() or _sha256(tex) != manifest.get("tex_sha256"):
        raise ValueError("实验三 TeX 表格缺失或已变化")
    assets.append(
        PlannedAsset(
            owner="experiment_3",
            key="subjective_table",
            source=tex,
            destination=settings.paths.table_destination,
            expected_sha256=str(manifest["tex_sha256"]),
        )
    )
    return ArtifactPlan(owner="experiment_3", assets=tuple(assets))


def copy_experiment3_assets_if_ready() -> dict[str, Any]:
    """独立调用时，预检并发布正式实验三图和 TeX。"""

    plan = plan_experiment3_assets_if_ready()
    if plan is None:
        return {"status": "skipped", "reason": "实验三尚无完整分析构建"}
    published = publish_artifact_plans((plan,))
    return {"status": "published", "published": published}


def _validate_output_root(root: Path, project_root: Path) -> None:
    """限制实验三分析输出位于 EgoAnchor_Python/data。"""

    data_root = (project_root / "data").resolve()
    if not root.is_relative_to(data_root):
        raise ValueError(f"实验三输出必须位于 {data_root} 内：{root}")


def _manifest_path(root: Path) -> Path:
    """返回构建来源清单路径。"""

    return root / "provenance" / _BUILD_RESULT


def _write_manifest(root: Path, payload: dict[str, Any]) -> None:
    """原子写入稳定排序的 UTF-8 JSON 来源清单。"""

    destination = _manifest_path(root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)


def _read_manifest(root: Path) -> dict[str, Any]:
    """读取并验证构建来源清单是 JSON object。"""

    path = _manifest_path(root)
    if not path.is_file():
        raise FileNotFoundError(f"实验三尚无分析结果，请先运行 analyze：{path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"实验三来源清单必须是 JSON object：{path}")
    return value


def _sha256(path: Path) -> str:
    """返回文件 SHA-256。"""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _progress(callback: Callable[[str], None] | None, message: str) -> None:
    """存在回调时报告当前分析阶段。"""

    if callback is not None:
        callback(message)


__all__ = [
    "analyze_experiment3",
    "copy_experiment3_assets_if_ready",
    "create_template",
    "describe_experiment3",
    "plot_experiment3",
    "plan_experiment3_assets_if_ready",
    "validate_input",
]

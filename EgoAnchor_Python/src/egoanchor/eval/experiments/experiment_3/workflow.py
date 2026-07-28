"""实验三的状态、门禁、分析构建和论文资源计划。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..common import (
    ArtifactPlan,
    PlannedAsset,
    build_manifest_path,
    file_sha256,
    read_build_manifest,
    source_tree_sha256,
    validate_output_files,
)
from .pipeline import build_analysis
from .analysis import describe_workbook, read_workbook, validate_for_analysis
from .settings import load_settings, settings_sha256


def describe_workflow() -> dict[str, Any]:
    """返回实验三固定配置、填表进度和最近构建状态。"""

    settings = load_settings()
    payload: dict[str, Any] = {
        "passed": True,
        "target": "exp3",
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
        payload["workbook"] = describe_workbook(
            read_workbook(settings.paths.input_workbook)
        )
    else:
        payload["workbook"] = {"passed": False, "reason": "原始模板尚未生成"}
    manifest_path = build_manifest_path(settings.paths.output_root)
    if manifest_path.is_file():
        try:
            manifest = read_build_manifest(
                settings.paths.output_root,
                owner="experiment_3",
            )
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


def validate_workflow() -> dict[str, Any]:
    """执行正式来源门禁，并要求工作簿达到完整分析条件。"""

    settings = load_settings()
    data = read_workbook(settings.paths.input_workbook)
    payload = describe_workbook(data)
    payload["analysis_readiness"] = validate_for_analysis(
        data,
        minimum_participants=settings.minimum_participants,
        aq_mode=settings.aq_mode,
        q10_enabled=settings.q10_enabled,
        allow_synthetic=False,
    )
    return payload


def analyze_workflow(
    *,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """从 TOML 固定原始工作簿完成全部本地分析产物。"""

    payload = build_analysis(load_settings(), progress=progress)
    payload["next_command"] = "pixi run eval copy-assets exp3"
    return payload


def plan_assets() -> ArtifactPlan:
    """返回实验三完整正式构建的只读资源计划。"""

    settings = load_settings()
    manifest_path = build_manifest_path(settings.paths.output_root)
    if not manifest_path.is_file():
        raise FileNotFoundError("实验三尚无完整正式构建，请先运行 analyze exp3")
    manifest = read_build_manifest(settings.paths.output_root, owner="experiment_3")
    if manifest.get("status") != "complete":
        raise ValueError("实验三构建尚未完整完成，拒绝复制论文资源")
    if manifest.get("source_kind") != "formal":
        raise ValueError("实验三合成/模拟构建不得复制到论文目录")
    if manifest.get("config_sha256") != settings_sha256():
        raise ValueError("实验三配置已变化，请重新运行 analyze exp3")
    implementation_root = Path(__file__).resolve().parent
    if manifest.get("implementation_sha256") != source_tree_sha256(implementation_root):
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
    expected_tex = (
        settings.paths.output_root / "tex" / "exp3_subjective.tex"
    ).resolve()
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


__all__ = [
    "analyze_workflow",
    "describe_workflow",
    "plan_assets",
    "validate_workflow",
]

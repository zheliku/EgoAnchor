"""实验三的状态、质量检查、分析构建和论文资源计划。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..common import (
    DEFAULT_PAPER_CONFIG_PATH,
    ArtifactPlan,
    PlannedAsset,
    build_manifest_path,
    file_sha256,
    read_build_manifest,
    source_tree_sha256,
    validate_output_files,
)
from . import analysis
from .analysis import (
    build_analysis,
    derive_scores,
    describe_workbook,
    load_settings_snapshot,
    read_workbook,
    validate_complete_pair_counts,
    validate_for_analysis,
)
from .data import load_paths


def describe_workflow() -> dict[str, Any]:
    """返回实验三固定配置、填表进度和最近构建状态。"""

    paths = load_paths()
    snapshot = load_settings_snapshot()
    settings = snapshot.settings
    payload: dict[str, Any] = {
        "passed": True,
        "target": "exp3",
        "configs": {
            "batch": str(paths.batch_config_path),
            "paper": str(DEFAULT_PAPER_CONFIG_PATH),
        },
        "config_sha256": snapshot.sha256,
        "input_workbook": str(paths.input_workbook),
        "output_root": str(paths.analysis_root),
        "paper_figure_destination": str(paths.figure_destination),
        "paper_table_destination": str(paths.table_destination),
        "aq_mode": settings.aq_mode,
        "q10_enabled": settings.q10_enabled,
        "tost_enabled": settings.equivalence_enabled,
    }
    if paths.input_workbook.is_file():
        payload["workbook"] = describe_workbook(read_workbook(paths.input_workbook))
    else:
        payload["workbook"] = {"passed": False, "reason": "原始模板尚未生成"}
    manifest_path = build_manifest_path(paths.analysis_root)
    if manifest_path.is_file():
        try:
            manifest = read_build_manifest(paths.analysis_root, owner="experiment_3")
        except (OSError, ValueError) as error:
            payload["build"] = {"status": "invalid", "reason": str(error)}
        else:
            payload["build"] = {
                "build_id": manifest["build_id"],
                "status": manifest["status"],
            }
    else:
        payload["build"] = {"status": "missing"}
    return payload


def validate_workflow() -> dict[str, Any]:
    """执行工作簿结构、填写完整性和冻结配对样本量检查。"""

    paths = load_paths()
    settings = load_settings_snapshot().settings
    data = read_workbook(paths.input_workbook)
    payload = describe_workbook(data)
    readiness = validate_for_analysis(
        data,
        aq_mode=settings.aq_mode,
        q10_enabled=settings.q10_enabled,
    )
    scores = derive_scores(data, settings)
    pair_counts = validate_complete_pair_counts(
        scores.paired_scores,
        settings.minimum_participants,
    )
    payload["analysis_readiness"] = {
        "included_participants": list(readiness["included_participants"]),
        "included_count": readiness["included_count"],
        "paired_counts": pair_counts,
    }
    return payload


def analyze_workflow(
    *,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """从共享 TOML 固定输入完成全部本地分析产物。"""

    paths = load_paths()
    snapshot = load_settings_snapshot()
    settings = snapshot.settings
    payload = build_analysis(
        settings,
        input_workbook=paths.input_workbook,
        output_root=paths.analysis_root,
        project_root=paths.project_root,
        config_sha256=snapshot.sha256,
        batch_config_path=paths.batch_config_path,
        paper_config_path=DEFAULT_PAPER_CONFIG_PATH,
        progress=progress,
    )
    payload["next_command"] = "pixi run eval copy-assets exp3"
    return payload


def plan_assets() -> ArtifactPlan:
    """返回实验三完整构建的只读资源计划。"""

    paths = load_paths()
    snapshot = load_settings_snapshot()
    manifest_path = build_manifest_path(paths.analysis_root)
    if not manifest_path.is_file():
        raise FileNotFoundError("实验三尚无完整构建，请先运行 analyze exp3")
    manifest = read_build_manifest(paths.analysis_root, owner="experiment_3")
    if manifest.get("status") != "complete":
        raise ValueError("实验三构建尚未完整完成，拒绝复制论文资源")
    if manifest.get("config_sha256") != snapshot.sha256:
        raise ValueError("实验三配置已变化，请重新运行 analyze exp3")
    implementation_root = Path(analysis.__file__).resolve().parent
    if manifest.get("implementation_sha256") != source_tree_sha256(implementation_root):
        raise ValueError("实验三分析实现已变化，请重新运行 analyze exp3")
    inputs = manifest.get("inputs")
    if not isinstance(inputs, list) or len(inputs) != 1 or not isinstance(inputs[0], dict):
        raise ValueError("实验三构建必须恰好声明一个原始工作簿")
    input_path = Path(str(inputs[0].get("path", ""))).expanduser().resolve()
    if input_path != paths.input_workbook.resolve():
        raise ValueError("实验三构建没有使用配置固定的原始工作簿")
    if not input_path.is_file() or file_sha256(input_path) != inputs[0].get("sha256"):
        raise ValueError("实验三原始输入已变化，请重新运行 analyze exp3")
    outputs = validate_output_files(manifest)
    contract = analysis.EXP3_ARTIFACTS
    expected_keys = {artifact.key for artifact in contract.outputs}
    if set(outputs) != expected_keys:
        missing = expected_keys.difference(outputs)
        unexpected = set(outputs).difference(expected_keys)
        raise ValueError(
            "实验三构建清单与冻结产物契约不一致："
            f"missing={sorted(missing)}, unexpected={sorted(unexpected)}"
        )
    resolved_outputs: dict[str, tuple[Path, str]] = {}
    for artifact in contract.outputs:
        output = outputs[artifact.key]
        source = Path(output["path"]).expanduser().resolve()
        expected = (
            paths.analysis_root / artifact.category / artifact.canonical_name
        ).resolve()
        if output.get("kind") != artifact.kind or source != expected:
            raise ValueError(
                f"实验三产物来源越界、文件名或类型不匹配：{artifact.key}: {source}"
            )
        resolved_outputs[artifact.key] = (source, output["sha256"])

    assets: list[PlannedAsset] = []
    for artifact in contract.figures:
        source, sha256 = resolved_outputs[artifact.key]
        assets.append(
            PlannedAsset(
                owner="experiment_3",
                key=artifact.key,
                source=source,
                destination=paths.figure_destination / artifact.canonical_name,
                expected_sha256=sha256,
            )
        )
    table = contract.subjective_table
    tex, tex_sha256 = resolved_outputs[table.key]
    if paths.table_destination.name != table.canonical_name:
        raise ValueError("实验三论文表目标文件名与冻结产物契约不一致")
    assets.append(
        PlannedAsset(
            owner="experiment_3",
            key=table.key,
            source=tex,
            destination=paths.table_destination,
            expected_sha256=tex_sha256,
        )
    )
    return ArtifactPlan(owner="experiment_3", assets=tuple(assets))


__all__ = [
    "analyze_workflow",
    "describe_workflow",
    "plan_assets",
    "validate_workflow",
]

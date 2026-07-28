"""从共享 ``batch.toml`` 与 ``paper.toml`` 读取实验一/二配置。"""

from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_BATCH_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "batch.toml"
"""实验一、二、三共同使用的批处理路径配置。"""

DEFAULT_PAPER_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "paper.toml"
"""实验一、二、三共同使用的论文统计配置。"""

_ANALYSIS_TABLE_KEYS = frozenset(
    {
        "exp1_static_table",
        "exp1_dynamic_table",
        "exp2_table",
    }
)
"""实验一/二必须复制到论文目录的三张表格键。"""

_IMAGE_SUFFIXES = frozenset({".png", ".pdf"})
"""论文图片资源允许的文件后缀。"""


@dataclass(frozen=True, slots=True)
class ArtifactDestination:
    """保存一项分析产物键及其论文目标路径。"""

    artifact_key: str
    """``build_result.json`` 中的稳定产物键。"""

    destination: Path
    """论文根目录内由 ``batch.toml`` 明确配置的目标文件。"""


@dataclass(frozen=True, slots=True)
class AssetCopy:
    """保存一项由配置选择的只读资源及其论文目标。"""

    source: Path
    """EgoAnchor_Python 项目内的只读源文件。"""

    destination: Path
    """论文根目录内的目标文件。"""


@dataclass(frozen=True, slots=True)
class BatchPaths:
    """保存实验一/二从共享配置解析出的全部绝对路径。"""

    project_root: Path
    """包含 ``pixi.toml`` 的 EgoAnchor_Python 根目录。"""

    task_data_root: Path
    """人工归档并按任务、版本命名的原始日志目录。"""

    task_workbook_root: Path
    """按原始任务目录独立保存的 Stage 1 工作簿缓存。"""

    task_analysis_root: Path
    """按工作簿独立保存的论文指标缓存。"""

    staging_root: Path
    """新批次通过全部检查前的临时父目录。"""

    archive_root: Path
    """退出当前论文活动集的旧批次父目录。"""

    active_root: Path
    """当前论文唯一使用的活动批次目录。"""

    paper_root: Path
    """论文图片和表格所在的仓库内目录。"""

    experiment_asset_destination: Path
    """实验一、二图片复制到论文时使用的目标目录。"""

    table_destinations: tuple[ArtifactDestination, ...]
    """三张分析表格在论文目录中的明确目标路径。"""

    relay_assets: tuple[AssetCopy, ...]
    """由配置明确选择的定性 replay 图片或 PDF。"""

    batch_config_path: Path
    """本次读取的共享批处理配置绝对路径。"""

    paper_config_path: Path
    """本次读取的共享论文参数配置绝对路径。"""


@dataclass(frozen=True, slots=True)
class PaperSettings:
    """保存实验一/二路径和冻结计算参数。"""

    contract_version: int
    """参数契约版本。"""

    lag_minimum_ms: float
    """有效时延搜索下界。"""

    lag_maximum_ms: float
    """有效时延搜索上界。"""

    lag_step_ms: float
    """有效时延搜索步长。"""

    lag_minimum_samples: int
    """每个候选时延的最小重叠样本数。"""

    transition_baseline_ms: float
    """起停动作的基线时长。"""

    transition_displacement_mm: float
    """起停动作的位移阈值。"""

    transition_persistence_ms: float
    """起停动作的持续门槛。"""

    occlusion_catastrophic_mm: float
    """遮挡灾难性失效阈值。"""

    paths: BatchPaths
    """本配置解析得到的实验一/二固定路径。"""


def project_root() -> Path:
    """返回包含 ``pixi.toml`` 的 EgoAnchor_Python 根目录。"""

    return Path(__file__).resolve().parents[5]


def settings_sha256(
    paper_config_path: Path | None = None,
) -> str:
    """返回仅覆盖实验一/二科学分析参数的稳定 SHA-256。"""

    paper_path = (paper_config_path or DEFAULT_PAPER_CONFIG_PATH).expanduser().resolve()
    paper_document = _load_toml(paper_path)
    owned = {
        "experiment_1_2": _mapping(
            paper_document,
            "experiment_1_2",
            paper_path.name,
        ),
    }
    encoded = json.dumps(owned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def load_settings(
    *,
    project_root_override: Path | None = None,
    batch_config_path: Path | None = None,
    paper_config_path: Path | None = None,
) -> PaperSettings:
    """读取并完整校验实验一/二的共享路径与论文分析参数。"""

    batch_path = (batch_config_path or DEFAULT_BATCH_CONFIG_PATH).expanduser().resolve()
    paper_path = (paper_config_path or DEFAULT_PAPER_CONFIG_PATH).expanduser().resolve()
    batch_document = _load_toml(batch_path)
    paper_document = _load_toml(paper_path)
    base = _normalize_project_root(project_root_override)

    batch_experiment = _mapping(batch_document, "experiment_1_2", batch_path.name)
    paper_experiment = _mapping(paper_document, "experiment_1_2", paper_path.name)
    paths = _load_paths(batch_document, batch_experiment, base, batch_path, paper_path)
    contract = _mapping(paper_experiment, "contract", "paper.toml [experiment_1_2]")
    lag = _mapping(paper_experiment, "lag", "paper.toml [experiment_1_2]")
    transition = _mapping(
        paper_experiment,
        "transition",
        "paper.toml [experiment_1_2]",
    )
    occlusion = _mapping(
        paper_experiment,
        "occlusion",
        "paper.toml [experiment_1_2]",
    )
    settings = PaperSettings(
        contract_version=int(contract["version"]),
        lag_minimum_ms=float(lag["minimum_ms"]),
        lag_maximum_ms=float(lag["maximum_ms"]),
        lag_step_ms=float(lag["step_ms"]),
        lag_minimum_samples=int(lag["minimum_samples"]),
        transition_baseline_ms=float(transition["baseline_ms"]),
        transition_displacement_mm=float(transition["displacement_mm"]),
        transition_persistence_ms=float(transition["persistence_ms"]),
        occlusion_catastrophic_mm=float(occlusion["catastrophic_mm"]),
        paths=paths,
    )
    _validate_settings(settings)
    return settings


def load_batch_paths(root: Path | None = None) -> BatchPaths:
    """读取实验一/二共享配置并返回全部绝对路径。"""

    return load_settings(project_root_override=root).paths


def _load_toml(path: Path) -> dict[str, Any]:
    """读取一份 TOML 并要求顶层为映射。"""

    with path.open("rb") as handle:
        document = tomllib.load(handle)
    if not isinstance(document, dict):
        raise ValueError(f"TOML 顶层必须是 table：{path}")
    return document


def _load_paths(
    batch_document: dict[str, Any],
    experiment: dict[str, Any],
    base: Path,
    batch_config_path: Path,
    paper_config_path: Path,
) -> BatchPaths:
    """解析实验一/二路径，并限制输入、输出和论文目录边界。"""

    shared = _mapping(batch_document, "shared", "batch.toml")
    shared_paths = _mapping(shared, "paths", "batch.toml [shared]")
    raw_paths = _mapping(experiment, "paths", "batch.toml [experiment_1_2]")
    raw_copy = _mapping(
        experiment,
        "copy_assets",
        "batch.toml [experiment_1_2]",
    )

    task_data_root = _resolve_data_path(base, raw_paths, "task_data_root")
    task_workbook_root = _resolve_data_path(base, raw_paths, "task_workbook_root")
    task_analysis_root = _resolve_data_path(base, raw_paths, "task_analysis_root")
    staging_root = _resolve_data_path(base, raw_paths, "staging_root")
    archive_root = _resolve_data_path(base, raw_paths, "archive_root")
    active_root = _resolve_data_path(base, raw_paths, "active_root")
    paper_root = _resolve_paper_path(base, shared_paths)
    experiment_asset_destination = _resolve_asset_destination(
        paper_root,
        raw_copy.get("experiment_destination"),
        "experiment_destination",
        directory=True,
    )
    table_destinations = _resolve_table_destinations(paper_root, raw_copy)
    relay_assets = _resolve_relay_assets(base, paper_root, raw_copy)
    managed = (
        task_data_root,
        task_workbook_root,
        task_analysis_root,
        staging_root,
        archive_root,
        active_root,
    )
    if len(set(managed)) != len(managed):
        raise ValueError("batch.toml 的实验一/二托管路径必须互不相同")
    for index, left in enumerate(managed):
        for right in managed[index + 1 :]:
            if left.is_relative_to(right) or right.is_relative_to(left):
                raise ValueError("batch.toml 的实验一/二托管路径不得互为父子目录")
    if any(
        paper_root.is_relative_to(path) or path.is_relative_to(paper_root)
        for path in managed
    ):
        raise ValueError("paper_root 不得与实验一/二托管数据目录重叠")
    return BatchPaths(
        project_root=base,
        task_data_root=task_data_root,
        task_workbook_root=task_workbook_root,
        task_analysis_root=task_analysis_root,
        staging_root=staging_root,
        archive_root=archive_root,
        active_root=active_root,
        paper_root=paper_root,
        experiment_asset_destination=experiment_asset_destination,
        table_destinations=table_destinations,
        relay_assets=relay_assets,
        batch_config_path=batch_config_path,
        paper_config_path=paper_config_path,
    )


def _normalize_project_root(root: Path | None) -> Path:
    """规范化项目根目录，并确认 ``pixi.toml`` 存在。"""

    base = (root or project_root()).expanduser().resolve()
    if not (base / "pixi.toml").is_file():
        raise FileNotFoundError(f"EgoAnchor_Python 根目录缺少 pixi.toml：{base}")
    return base


def _resolve_data_path(base: Path, raw_paths: dict[str, Any], field_name: str) -> Path:
    """解析必须位于 EgoAnchor_Python/data 内的实验目录。"""

    raw_value = raw_paths.get(field_name)
    if not isinstance(raw_value, str) or not raw_value:
        raise ValueError(f"batch.toml experiment_1_2.paths.{field_name} 必须为非空字符串")
    resolved = (base / raw_value).resolve()
    data_root = (base / "data").resolve()
    if not resolved.is_relative_to(data_root):
        raise ValueError(
            f"batch.toml experiment_1_2.paths.{field_name} 必须位于 {data_root} 内"
        )
    return resolved


def _resolve_paper_path(base: Path, raw_paths: dict[str, Any]) -> Path:
    """解析必须位于当前仓库内的论文目录。"""

    raw_value = raw_paths.get("paper_root")
    if not isinstance(raw_value, str) or not raw_value:
        raise ValueError("batch.toml shared.paths.paper_root 必须为非空字符串")
    resolved = (base / raw_value).resolve()
    repository_root = base.parent.resolve()
    if not resolved.is_relative_to(repository_root):
        raise ValueError(f"batch.toml shared.paths.paper_root 必须位于 {repository_root} 内")
    return resolved


def _resolve_asset_destination(
    paper_root: Path,
    raw_value: Any,
    config_key: str,
    *,
    directory: bool,
    allowed_suffixes: frozenset[str] = _IMAGE_SUFFIXES,
) -> Path:
    """解析论文目录内的资源目标，并拒绝绝对路径和越界路径。"""

    if not isinstance(raw_value, str) or not raw_value:
        raise ValueError(
            f"batch.toml experiment_1_2.copy_assets.{config_key} 必须为非空字符串"
        )
    relative = Path(raw_value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(
            f"batch.toml experiment_1_2.copy_assets.{config_key} 必须是 paper_root 内的相对路径"
        )
    resolved = (paper_root / relative).resolve()
    if not resolved.is_relative_to(paper_root):
        raise ValueError(
            f"batch.toml experiment_1_2.copy_assets.{config_key} 超出 paper_root"
        )
    if directory:
        return resolved
    if resolved.suffix.lower() not in allowed_suffixes:
        readable_suffixes = "、".join(
            sorted(suffix.lstrip(".").upper() for suffix in allowed_suffixes)
        )
        raise ValueError(
            f"batch.toml experiment_1_2.copy_assets.{config_key} 只能指向 {readable_suffixes}"
        )
    return resolved


def _resolve_table_destinations(
    paper_root: Path,
    copy_assets: dict[str, Any],
) -> tuple[ArtifactDestination, ...]:
    """读取三张分析表格在论文目录中的明确目标路径。"""

    raw_tables = copy_assets.get("tables")
    if not isinstance(raw_tables, dict) or set(raw_tables) != _ANALYSIS_TABLE_KEYS:
        raise ValueError(
            "batch.toml experiment_1_2.copy_assets.tables 必须恰好配置三张分析表格"
        )
    destinations = tuple(
        ArtifactDestination(
            artifact_key=key,
            destination=_resolve_asset_destination(
                paper_root,
                raw_tables[key],
                f"tables.{key}",
                directory=False,
                allowed_suffixes=frozenset({".tex"}),
            ),
        )
        for key in sorted(_ANALYSIS_TABLE_KEYS)
    )
    if len({item.destination for item in destinations}) != len(destinations):
        raise ValueError("batch.toml experiment_1_2.copy_assets.tables 的目标路径不得重复")
    return destinations


def _resolve_relay_assets(
    project_root_path: Path,
    paper_root: Path,
    copy_assets: dict[str, Any],
) -> tuple[AssetCopy, ...]:
    """读取明确的 replay 来源与论文目标，不按修改时间猜测资源。"""

    raw_assets = copy_assets.get("relay")
    if not isinstance(raw_assets, list) or not raw_assets:
        raise ValueError(
            "batch.toml experiment_1_2.copy_assets.relay 必须包含至少一项明确资源"
        )
    assets: list[AssetCopy] = []
    for index, item in enumerate(raw_assets, start=1):
        if not isinstance(item, dict):
            raise ValueError(
                f"batch.toml experiment_1_2.copy_assets.relay[{index}] 必须是表"
            )
        raw_source = item.get("source")
        if not isinstance(raw_source, str) or not raw_source:
            raise ValueError(
                f"batch.toml experiment_1_2.copy_assets.relay[{index}].source 必须为非空字符串"
            )
        source_relative = Path(raw_source)
        if source_relative.is_absolute() or ".." in source_relative.parts:
            raise ValueError(
                f"batch.toml experiment_1_2.copy_assets.relay[{index}].source 必须是项目内相对路径"
            )
        source = (project_root_path / source_relative).resolve()
        if (
            not source.is_relative_to(project_root_path)
            or source.suffix.lower() not in _IMAGE_SUFFIXES
        ):
            raise ValueError(
                f"batch.toml experiment_1_2.copy_assets.relay[{index}].source 只能指向项目内 PNG 或 PDF"
            )
        destination = _resolve_asset_destination(
            paper_root,
            item.get("destination"),
            f"relay[{index}].destination",
            directory=False,
        )
        assets.append(AssetCopy(source=source, destination=destination))
    if len({item.destination for item in assets}) != len(assets):
        raise ValueError(
            "batch.toml experiment_1_2.copy_assets.relay 的 destination 不得重复"
        )
    return tuple(assets)


def _mapping(document: dict[str, Any], section: str, source: str) -> dict[str, Any]:
    """读取一项必需 TOML table。"""

    value = document.get(section)
    if not isinstance(value, dict):
        raise ValueError(f"{source} 缺少 [{section}]")
    return value


def _validate_settings(settings: PaperSettings) -> None:
    """检查实验一/二科学参数的联合约束。"""

    if settings.contract_version != 1:
        raise ValueError("实验一/二当前只接受参数契约 v1")
    if settings.lag_step_ms <= 0 or settings.lag_maximum_ms < settings.lag_minimum_ms:
        raise ValueError("有效时延网格无效")
    if settings.lag_minimum_samples < 2:
        raise ValueError("有效时延最小重叠样本数必须至少为 2")


__all__ = [
    "ArtifactDestination",
    "AssetCopy",
    "BatchPaths",
    "DEFAULT_BATCH_CONFIG_PATH",
    "DEFAULT_PAPER_CONFIG_PATH",
    "PaperSettings",
    "load_batch_paths",
    "load_settings",
    "project_root",
    "settings_sha256",
]

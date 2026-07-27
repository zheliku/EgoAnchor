"""跨实验联合预检并发布论文资源。"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


_PUBLISH_SUFFIXES = frozenset({".png", ".pdf", ".tex"})
"""论文资源发布器接受的固定文件类型。"""


@dataclass(frozen=True, slots=True)
class PlannedAsset:
    """描述一项通过来源清单约束的待发布文件。"""

    owner: str
    """拥有该资源的实验流水线。"""

    key: str
    """实验内稳定资源键。"""

    source: Path
    """本地分析产物绝对路径。"""

    destination: Path
    """论文目录中的明确目标路径。"""

    expected_sha256: str | None = None
    """来源清单冻结的可选内容摘要。"""


@dataclass(frozen=True, slots=True)
class ArtifactPlan:
    """保存一条实验流水线的完整发布计划。"""

    owner: str
    """实验流水线稳定名称。"""

    assets: tuple[PlannedAsset, ...]
    """该实验全部待发布资源。"""


def publish_artifact_plans(plans: tuple[ArtifactPlan, ...]) -> list[dict[str, str]]:
    """联合预检全部实验，暂存全部文件后再逐项原子替换。"""

    for plan in plans:
        if any(asset.owner != plan.owner for asset in plan.assets):
            raise ValueError(f"发布计划包含其他实验的资源：{plan.owner}")
    assets = tuple(asset for plan in plans for asset in plan.assets)
    _validate_assets(assets)
    staged: list[tuple[PlannedAsset, Path]] = []
    try:
        for asset in assets:
            asset.destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = asset.destination.with_name(
                f".{asset.destination.name}.{uuid4().hex}.tmp"
            )
            shutil.copyfile(asset.source, temporary)
            staged.append((asset, temporary))
        for asset, temporary in staged:
            temporary.replace(asset.destination)
    finally:
        for _, temporary in staged:
            temporary.unlink(missing_ok=True)
    return [
        {
            "owner": asset.owner,
            "key": asset.key,
            "source": str(asset.source),
            "destination": str(asset.destination),
            "sha256": _sha256(asset.destination),
        }
        for asset in assets
    ]


def _validate_assets(assets: tuple[PlannedAsset, ...]) -> None:
    """在任何论文目标写入前完成联合来源和目标检查。"""

    destinations: set[Path] = set()
    identities: set[tuple[str, str]] = set()
    for asset in assets:
        identity = (asset.owner, asset.key)
        if identity in identities:
            raise ValueError(f"发布计划资源键重复：{asset.owner}/{asset.key}")
        identities.add(identity)
        source = asset.source.expanduser().resolve()
        destination = asset.destination.expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"待复制资源不存在：{source}")
        if source.suffix.lower() not in _PUBLISH_SUFFIXES:
            raise ValueError(f"只允许复制 PNG、PDF 或 TeX：{source}")
        if destination in destinations:
            raise ValueError(f"copy-assets 目标路径重复：{destination}")
        destinations.add(destination)
        if asset.expected_sha256 is not None and _sha256(source) != asset.expected_sha256:
            raise ValueError(f"待复制资源摘要已变化：{asset.owner}/{asset.key}")


def _sha256(path: Path) -> str:
    """返回文件 SHA-256。"""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


__all__ = ["ArtifactPlan", "PlannedAsset", "publish_artifact_plans"]

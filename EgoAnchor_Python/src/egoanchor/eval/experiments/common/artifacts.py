"""跨实验联合预检并复制论文资源。"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


_COPY_SUFFIXES = frozenset({".png", ".pdf", ".tex"})
"""论文资源复制器接受的固定文件类型。"""


@dataclass(frozen=True, slots=True)
class PlannedAsset:
    """描述一项通过来源清单约束的待复制文件。"""

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
    """保存一条实验流水线的完整资源复制计划。"""

    owner: str
    """实验流水线稳定名称。"""

    assets: tuple[PlannedAsset, ...]
    """该实验全部待发布资源。"""


def copy_artifact_plans(plans: tuple[ArtifactPlan, ...]) -> list[dict[str, str]]:
    """联合预检、暂存并以可回滚事务复制全部实验资源。"""

    for plan in plans:
        if any(asset.owner != plan.owner for asset in plan.assets):
            raise ValueError(f"资源计划包含其他实验的文件：{plan.owner}")
    assets = tuple(asset for plan in plans for asset in plan.assets)
    _validate_assets(assets)
    staged: list[tuple[PlannedAsset, Path]] = []
    backups: list[tuple[PlannedAsset, Path | None]] = []
    preserve_backups = False
    try:
        for asset in assets:
            asset.destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = asset.destination.with_name(
                f".{asset.destination.name}.{uuid4().hex}.tmp"
            )
            shutil.copyfile(asset.source, temporary)
            staged.append((asset, temporary))
        for asset, _ in staged:
            backup: Path | None = None
            if asset.destination.exists():
                backup = asset.destination.with_name(
                    f".{asset.destination.name}.{uuid4().hex}.backup"
                )
                asset.destination.replace(backup)
            backups.append((asset, backup))
        for asset, temporary in staged:
            temporary.replace(asset.destination)
    except Exception:
        restore_errors: list[str] = []
        for asset, backup in reversed(backups):
            try:
                asset.destination.unlink(missing_ok=True)
                if backup is not None and backup.exists():
                    backup.replace(asset.destination)
            except OSError as error:
                restore_errors.append(f"{asset.destination}: {error}")
        if restore_errors:
            preserve_backups = True
            raise RuntimeError("复制失败且回滚不完整：" + "; ".join(restore_errors))
        raise
    finally:
        for _, temporary in staged:
            temporary.unlink(missing_ok=True)
        if not preserve_backups:
            for _, backup in backups:
                if backup is not None:
                    backup.unlink(missing_ok=True)
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
        if source.suffix.lower() not in _COPY_SUFFIXES:
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


__all__ = ["ArtifactPlan", "PlannedAsset", "copy_artifact_plans"]

"""统一读取评估工程的共享 TOML，并计算实验专属参数摘要。"""

from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path
from typing import Any


DEFAULT_BATCH_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "batch.toml"
"""实验一、二、三共用的路径与发布配置。"""

DEFAULT_PAPER_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "paper.toml"
"""实验一、二、三共用的冻结科学参数配置。"""


def project_root(root: Path | None = None) -> Path:
    """返回并校验包含 ``pixi.toml`` 的 EgoAnchor_Python 根目录。"""

    resolved = (root or Path(__file__).resolve().parents[5]).expanduser().resolve()
    if not (resolved / "pixi.toml").is_file():
        raise FileNotFoundError(f"EgoAnchor_Python 根目录缺少 pixi.toml：{resolved}")
    return resolved


def load_toml(path: Path) -> dict[str, Any]:
    """读取 TOML，并要求其顶层为映射。"""

    resolved = path.expanduser().resolve()
    with resolved.open("rb") as handle:
        document = tomllib.load(handle)
    if not isinstance(document, dict):
        raise ValueError(f"TOML 顶层必须是 table：{resolved}")
    return document


def require_table(document: dict[str, Any], section: str, source: str) -> dict[str, Any]:
    """读取一项必需 TOML table。"""

    value = document.get(section)
    if not isinstance(value, dict):
        raise ValueError(f"{source} 缺少 [{section}]")
    return value


def section_sha256(section: str, path: Path | None = None) -> str:
    """只摘要 ``paper.toml`` 中指定实验拥有的科学参数。"""

    config_path = (path or DEFAULT_PAPER_CONFIG_PATH).expanduser().resolve()
    document = load_toml(config_path)
    owned = {section: require_table(document, section, config_path.name)}
    encoded = json.dumps(owned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = [
    "DEFAULT_BATCH_CONFIG_PATH",
    "DEFAULT_PAPER_CONFIG_PATH",
    "load_toml",
    "project_root",
    "require_table",
    "section_sha256",
]

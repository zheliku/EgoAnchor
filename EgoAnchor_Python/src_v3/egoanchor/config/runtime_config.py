"""v3 轻量配置加载器。

配置层只读取 TOML 并提供路径信息，不导入 ZMQ、OpenCV 或模型模块。
这样可以保证后续单元测试、CLI 和配置检查都不会触发重依赖初始化。
"""

from __future__ import annotations

import copy
import tomllib
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any


@dataclass(frozen=True)
class RuntimePaths:
    """v3 运行时常用路径集合。"""

    repo_root: Path
    python_root: Path
    protocol_root: Path
    subjects_path: Path


DEFAULT_CONFIG_PATH = Path(__file__).resolve().with_name("defaults.toml")


def _repo_root() -> Path:
    """返回仓库根目录 `EgoAnchor`。"""

    return Path(__file__).resolve().parents[4]


def _python_root() -> Path:
    """返回 `EgoAnchor_Python` 项目目录。"""

    return Path(__file__).resolve().parents[3]


def _dict_to_namespace(value: Any) -> Any:
    """递归把 dict 转成 `SimpleNamespace`，便于用点号访问配置。"""

    if isinstance(value, dict):
        return SimpleNamespace(**{key: _dict_to_namespace(item) for key, item in value.items()})
    if isinstance(value, list):
        return [_dict_to_namespace(item) for item in value]
    return value


def _merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """递归合并默认配置和用户覆盖配置。"""

    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(config_path: str | Path | None = None) -> SimpleNamespace:
    """加载 v3 配置并附加仓库路径信息。"""

    with DEFAULT_CONFIG_PATH.open("rb") as f:
        data = tomllib.load(f)

    if config_path is not None:
        path = Path(config_path)
        with path.open("rb") as f:
            data = _merge_dict(data, tomllib.load(f))

    cfg = _dict_to_namespace(data)
    repo_root = _repo_root()
    cfg.paths = RuntimePaths(
        repo_root=repo_root,
        python_root=_python_root(),
        protocol_root=repo_root / "EgoAnchor_Protocol",
        subjects_path=repo_root / "EgoAnchor_Protocol" / "subjects.v1.json",
    )
    return cfg
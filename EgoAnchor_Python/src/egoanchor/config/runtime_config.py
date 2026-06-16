"""轻量配置加载器。

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
    """运行时常用路径集合。"""

    python_root: Path
    """EgoAnchor_Python 项目根目录。"""

    protocol_root: Path
    """Python 运行时随包携带的协议资源目录。"""

    subjects_path: Path
    """共享 subject registry JSON 文件路径。"""

    objects_path: Path
    """对象覆盖配置 TOML 文件路径。"""


DEFAULT_CONFIG_PATH = Path(__file__).resolve().with_name("defaults.toml")
OBJECT_CONFIG_PATH = Path(__file__).resolve().with_name("objects.toml")


def _python_root() -> Path:
    """返回 `EgoAnchor_Python` 项目目录。"""

    return Path(__file__).resolve().parents[3]


def _python_protocol_root() -> Path:
    """返回 Python 运行时随包携带的协议资源目录。"""

    return _python_root() / "src" / "egoanchor" / "protocol"


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


def load_object_override(name: str, objects_path: str | Path | None = None) -> dict[str, Any]:
    """按对象名读取统一对象覆盖配置。

    返回值可直接叠加到 defaults.toml 上。未知对象名会立即报错，避免
    tracking server 悄悄退回默认 cube 配置。
    """

    object_name = str(name or "").strip()
    if not object_name:
        raise KeyError("未知对象配置: <empty>")
    path = Path(objects_path) if objects_path is not None else OBJECT_CONFIG_PATH
    with path.open("rb") as f:
        data = tomllib.load(f)
    objects = data.get("objects", {})
    if object_name not in objects:
        available = ", ".join(sorted(objects)) or "<none>"
        raise KeyError(f"未知对象配置: {object_name}; 可用对象: {available}")
    value = objects[object_name]
    if not isinstance(value, dict):
        raise KeyError(f"未知对象配置: {object_name}")
    return copy.deepcopy(value)


def load_config(config_path: str | Path | None = None, object_name: str | None = None) -> SimpleNamespace:
    """加载运行配置并附加仓库路径信息。

    合并顺序为 defaults.toml -> objects.toml 对象覆盖 -> 显式 config_path，
    便于先选择目标物体，再用本地 TOML 做临时调参。
    """

    normalized_object_name = str(object_name).strip() if object_name is not None else ""
    with DEFAULT_CONFIG_PATH.open("rb") as f:
        data = tomllib.load(f)

    if object_name is not None:
        data = _merge_dict(data, load_object_override(normalized_object_name))

    if config_path is not None:
        path = Path(config_path)
        with path.open("rb") as f:
            data = _merge_dict(data, tomllib.load(f))

    cfg = _dict_to_namespace(data)
    protocol_root = _python_protocol_root()
    cfg.paths = RuntimePaths(
        python_root=_python_root(),
        protocol_root=protocol_root,
        subjects_path=protocol_root / "subjects.v1.json",
        objects_path=OBJECT_CONFIG_PATH,
    )
    cfg.runtime.object_id = normalized_object_name or str(getattr(cfg.runtime, "object_id", "default") or "default")
    return cfg

"""EgoAnchor v2 配置加载。

本文件只负责读取 v2 的轻量配置，不导入 ZMQ、OpenCV 或模型依赖。
这样做的原因是：配置层应保持纯净，避免单元测试或 CLI 打印配置时触发昂贵依赖。
"""

from __future__ import annotations

import copy
import tomllib
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any


def _repo_root() -> Path:
    """返回仓库根目录。

    当前文件路径为：EgoAnchor_Python/src_v2/egoanchor/config/runtime_config.py。
    parents[4] 正好对应仓库根目录 EgoAnchor。
    """

    return Path(__file__).resolve().parents[4]


def _python_root() -> Path:
    """返回 EgoAnchor_Python 项目目录。"""

    return Path(__file__).resolve().parents[3]


DEFAULT_CONFIG_PATH = _python_root() / "src_v2" / "egoanchor" / "config" / "defaults.toml"

PATH_FIELDS: set[tuple[str, ...]] = {
    ("module", "yoloe", "model_path"),
    ("module", "yoloe", "mobileclip2_path"),
    ("module", "ffs", "model_path"),
    ("module", "ffs", "trt_feature_engine_path"),
    ("module", "ffs", "trt_post_engine_path"),
    ("module", "foundationpose", "mesh_path"),
    ("module", "foundationpose", "debug_dir"),
}


@dataclass(frozen=True)
class RuntimePaths:
    """v2 常用路径集合。

    这些路径不写进 TOML，是因为它们由仓库布局唯一决定；集中暴露便于后续模块复用。
    """

    repo_root: Path
    python_root: Path
    protocol_root: Path
    subjects_path: Path


def _dict_to_namespace(value: Any) -> Any:
    """递归把 dict 转为 SimpleNamespace，便于 cfg.network.data_plane.listen_port 访问。"""

    if isinstance(value, dict):
        return SimpleNamespace(**{k: _dict_to_namespace(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_dict_to_namespace(v) for v in value]
    return value


def _merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """递归合并配置字典。

    - base 是 defaults.toml。
    - override 是用户传入配置。
    - 两边同为 dict 时递归合并，否则 override 覆盖 base。
    """

    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def _resolve_project_path(value: str | Path, project_dir: Path) -> Path | str:
    """把配置中的相对路径解析到 EgoAnchor_Python 项目目录。"""

    if value == "":
        return ""
    path = Path(value)
    if path.is_absolute():
        return path
    return (project_dir / path).resolve()


def _resolve_paths(cfg: SimpleNamespace, project_dir: Path) -> None:
    """原地解析 v2 已知路径字段。缺失字段会被跳过，保持配置层兼容。"""

    for field_path in PATH_FIELDS:
        parent: Any = cfg
        missing = False
        for part in field_path[:-1]:
            if not hasattr(parent, part):
                missing = True
                break
            parent = getattr(parent, part)
        if missing:
            continue
        key = field_path[-1]
        if hasattr(parent, key):
            setattr(parent, key, _resolve_project_path(getattr(parent, key), project_dir))


def load_config(config_path: str | Path | None = None) -> SimpleNamespace:
    """加载 v2 运行配置。

    参数：
    - config_path=None：只读取默认配置。
    - config_path=路径：先读默认配置，再用指定 TOML 覆盖。

    返回：
    - SimpleNamespace，包含 cfg.network.data_plane 等字段。
    - 额外附加 cfg.paths，便于定位协议契约与项目根目录。
    """

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
    _resolve_paths(cfg, cfg.paths.python_root)
    return cfg

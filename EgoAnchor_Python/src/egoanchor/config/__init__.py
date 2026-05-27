"""配置包级入口。"""

from __future__ import annotations

from .runtime_config import RuntimePaths, load_config, load_object_override

__all__ = ["RuntimePaths", "load_config", "load_object_override"]

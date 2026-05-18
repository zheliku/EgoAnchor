"""v2 runtime 层：拥有 pipeline 状态并组织主循环。"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from egoanchor.runtime.command_queue import CommandQueue, RuntimeCommand


def __getattr__(name: str) -> Any:
	"""惰性导出 TrackingRuntime，避免 import runtime 包时加载 perception 模型链。"""

	if name == "TrackingRuntime":
		module = import_module("egoanchor.runtime.tracking_runtime")
		value = module.TrackingRuntime
		globals()[name] = value
		return value
	raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["CommandQueue", "RuntimeCommand", "TrackingRuntime"]

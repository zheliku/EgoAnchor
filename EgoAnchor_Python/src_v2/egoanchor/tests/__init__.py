"""v2 测试与本机辅助脚本包。"""

from __future__ import annotations

from importlib import import_module
from typing import Any


def __getattr__(name: str) -> Any:
	"""惰性导出本机 fake Quest stream 入口。"""

	if name == "fake_quest_stream_main":
		module = import_module("egoanchor.tests.send_fake_quest_stream")
		value = module.main
		globals()[name] = value
		return value
	raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["fake_quest_stream_main"]
"""v2 Python 单元/烟雾测试。"""

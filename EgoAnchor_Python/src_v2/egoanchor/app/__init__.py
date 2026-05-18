"""v2 app 入口层。

本包按需导出可直接运行的入口函数。这里使用惰性导入，避免 import `egoanchor.app`
时立刻加载 YOLOE/FFS/FoundationPose 等重依赖。
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_LAZY_EXPORTS = {
	"tracking_server_main": ("egoanchor.app.tracking_server", "main"),
	"quest_video_stream_demo_main": ("egoanchor.app.quest_video_stream_demo", "main"),
	"quest_pose_debug_demo_main": ("egoanchor.app.quest_pose_debug_demo", "main"),
	"run_server": ("egoanchor.app.tracking_server", "run_server"),
	"run_quest_video_stream_demo": ("egoanchor.app.quest_video_stream_demo", "run_demo"),
	"run_quest_pose_debug_demo": ("egoanchor.app.quest_pose_debug_demo", "run_demo"),
}


def __getattr__(name: str) -> Any:
	"""按需加载 app 入口函数。"""

	target = _LAZY_EXPORTS.get(name)
	if target is None:
		raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
	module_name, attr_name = target
	module = import_module(module_name)
	value = getattr(module, attr_name)
	globals()[name] = value
	return value


__all__ = [
	"tracking_server_main",
	"quest_video_stream_demo_main",
	"quest_pose_debug_demo_main",
	"run_server",
	"run_quest_video_stream_demo",
	"run_quest_pose_debug_demo",
]

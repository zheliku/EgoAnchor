"""v3 runtime 包级入口。"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from egoanchor.runtime.latest_quest_input_store import LatestQuestInputStore, QuestInputStats
from egoanchor.runtime.quest_stream_receiver import QuestStreamReceiver

_LAZY_EXPORTS = {
	"RuntimeTickResult": "egoanchor.runtime.tracking_runtime",
	"TrackingRuntime": "egoanchor.runtime.tracking_runtime",
}


def __getattr__(name: str) -> Any:
	"""惰性导出 TrackingRuntime，避免导入 runtime 包时加载 pose pipeline。"""

	module_name = _LAZY_EXPORTS.get(name)
	if module_name is None:
		raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
	module = import_module(module_name)
	value = getattr(module, name)
	globals()[name] = value
	return value


__all__ = ["LatestQuestInputStore", "QuestInputStats", "QuestStreamReceiver", "RuntimeTickResult", "TrackingRuntime"]
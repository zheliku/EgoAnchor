"""runtime 包级入口。"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from .commands import (
    CommandDedupStore,
    CommandExecutionResult,
    CommandExecutor,
    CommandHandler,
    CommandPump,
    CommandQueue,
    CommandType,
    RuntimeCommand,
    command_handler,
    control_action_handler,
)
from .runtime_state import RuntimeState, runtime_state_value
from .message_factories import HeartbeatFactory, PoseResultFactory, StatusEventFactory
from .quest_stream_receiver import LatestQuestInputStore, QuestInputStats
from .runtime_log_writer import PoseLogFactory, RuntimeLogWriter

_LAZY_EXPORTS = {
    "QuestStreamReceiver": "egoanchor.runtime.quest_stream_receiver",
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


__all__ = [
    "CommandDedupStore",
    "CommandExecutionResult",
    "CommandExecutor",
    "CommandHandler",
    "CommandPump",
    "CommandQueue",
    "CommandType",
    "command_handler",
    "control_action_handler",
    "LatestQuestInputStore",
    "HeartbeatFactory",
    "PoseLogFactory",
    "PoseResultFactory",
    "QuestInputStats",
    "QuestStreamReceiver",
    "RuntimeState",
    "RuntimeLogWriter",
    "runtime_state_value",
    "RuntimeCommand",
    "RuntimeTickResult",
    "StatusEventFactory",
    "TrackingRuntime",
]


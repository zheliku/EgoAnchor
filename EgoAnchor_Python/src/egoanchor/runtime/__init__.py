"""runtime 包级入口。"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from .command_models import CommandType, RuntimeCommand
from .command_dedup import CommandDedupStore
from .command_executor import CommandExecutionResult, CommandExecutor, CommandHandler, command_handler, control_action_handler
from .command_queue import CommandQueue
from .runtime_state import RuntimeState, runtime_state_value
from .heartbeat_factory import HeartbeatFactory
from .latest_value_store import LatestValueStore
from .latest_quest_input_store import LatestQuestInputStore, QuestInputStats
from .pose_log_factory import PoseLogFactory
from .pose_result_factory import PoseResultFactory
from .runtime_log_writer import RuntimeLogWriter
from .command_pump import CommandPump
from .status_event_factory import StatusEventFactory

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
    "LatestValueStore",
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


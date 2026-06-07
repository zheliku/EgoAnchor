"""runtime command 流水线。"""

from __future__ import annotations

import heapq
import itertools
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from google.protobuf.message import Message

from egoanchor.protocol import AnchorControlRequest, CommandAck
from egoanchor.utils import get_logger
from .runtime_state import RuntimeState

LOGGER = get_logger(__name__, component="RuntimeCommand")


class CommandType(str, Enum):
    """runtime 当前支持的命令类型。"""

    RESET = "reset"
    REACQUIRE = "reacquire"
    CONTROL = "control"


@dataclass(frozen=True, slots=True)
class RuntimeCommand:
    """已接受、等待 TrackingRuntime 在 frame 边界执行的命令。"""

    command_type: CommandType
    request_id: str
    anchor_id: str
    message: Message
    created_mono_ms: float

    @classmethod
    def from_message(cls, command_type: CommandType, message: Message) -> "RuntimeCommand":
        """从 protobuf command message 中提取 header 并构造 runtime command。"""

        header = getattr(message, "header", None)
        return cls(
            command_type=command_type,
            request_id=str(getattr(header, "request_id", "")),
            anchor_id=str(getattr(header, "anchor_id", "")),
            message=message,
            created_mono_ms=time.monotonic() * 1000.0,
        )


@dataclass(slots=True)
class _DedupEntry:
    """幂等缓存中的单个 request_id 记录。"""

    ack: CommandAck
    """首次处理该 request_id 时返回的 ack 副本。"""

    expires_mono_ms: float
    """该缓存记录过期的本地单调时间，单位毫秒。"""


class CommandDedupStore:
    """基于 header.request_id 的 TTL 去重缓存。"""

    def __init__(self, ttl_ms: float = 60_000.0) -> None:
        """初始化 TTL 与线程安全缓存。"""

        self._ttl_ms = float(ttl_ms)
        self._entries: dict[str, _DedupEntry] = {}
        self._lock = threading.Lock()

    def get(self, request_id: str) -> CommandAck | None:
        """命中重复 request_id 时返回 ack 副本，并标记 duplicate=true。"""

        with self._lock:
            self._prune_locked()
            entry = self._entries.get(request_id)
            if entry is None:
                return None
            ack = CommandAck()
            ack.CopyFrom(entry.ack)
            ack.duplicate = True
            return ack

    def remember(self, request_id: str, ack: CommandAck) -> None:
        """记录某个 request_id 的首次 ack。"""

        if not request_id:
            return
        with self._lock:
            stored = CommandAck()
            stored.CopyFrom(ack)
            self._entries[request_id] = _DedupEntry(stored, time.monotonic() * 1000.0 + self._ttl_ms)

    def _prune_locked(self) -> None:
        """清理过期 request_id。"""

        now = time.monotonic() * 1000.0
        expired = [key for key, entry in self._entries.items() if entry.expires_mono_ms <= now]
        for key in expired:
            del self._entries[key]

    def __len__(self) -> int:
        """返回当前仍在 TTL 内的 request_id 数量。"""

        with self._lock:
            self._prune_locked()
            return len(self._entries)


_PRIORITY = {
    CommandType.RESET: 0,
    CommandType.REACQUIRE: 0,
    CommandType.CONTROL: 10,
}


@dataclass(order=True)
class _QueueItem:
    """CommandQueue 内部 heap item。"""

    priority: int
    """命令优先级；数值越小越先执行。"""

    sequence: int
    """入队序号；同优先级下保持 FIFO。"""

    command: RuntimeCommand = field(compare=False)
    """实际 runtime command；不参与 heap 比较。"""


class CommandQueue:
    """线程安全轻量优先级命令队列。"""

    def __init__(self, max_size: int = 128) -> None:
        """初始化队列容量和序号生成器。"""

        self._max_size = max(1, int(max_size))
        self._items: list[_QueueItem] = []
        self._seq = itertools.count()
        self._lock = threading.Lock()

    def put(self, command: RuntimeCommand) -> bool:
        """按优先级入队；队列满时返回 False。"""

        with self._lock:
            if len(self._items) >= self._max_size:
                return False
            heapq.heappush(self._items, _QueueItem(_PRIORITY.get(command.command_type, 100), next(self._seq), command))
            return True

    def pop_many(self, limit: int) -> list[RuntimeCommand]:
        """最多取出 limit 条命令，未取出的命令留在队列中保持原顺序。"""

        if limit <= 0:
            return []
        with self._lock:
            out: list[RuntimeCommand] = []
            for _ in range(min(int(limit), len(self._items))):
                out.append(heapq.heappop(self._items).command)
            return out

    def __len__(self) -> int:
        """返回当前队列长度。"""

        with self._lock:
            return len(self._items)


@dataclass(slots=True)
class CommandExecutionResult:
    """单条 runtime command 的执行结果。"""

    paused: bool | None = None
    """是否修改 runtime 暂停状态；None 表示不改变当前暂停状态。"""

    stage: int | None = None
    """是否切换 debug stage；None 表示不改变当前 stage。"""

    reset_tracking: bool = False
    """是否重置 tracking 状态；由 TrackingRuntime 在主线程顺序执行。"""


CommandHandler = Callable[[RuntimeCommand], CommandExecutionResult]
"""RuntimeCommand -> CommandExecutionResult 的命令解释函数类型。"""

COMMAND_HANDLERS: dict[CommandType, CommandHandler] = {}
"""模块级 command handler 注册表；通过 @command_handler 自动填充。"""

CONTROL_ACTION_HANDLERS: dict[int, CommandHandler] = {}
"""模块级 control action handler 注册表；通过 @control_action_handler 自动填充。"""


def command_handler(command_type: CommandType) -> Callable[[CommandHandler], CommandHandler]:
    """注册 RuntimeCommand 类型解释函数的装饰器。"""

    def decorator(handler: CommandHandler) -> CommandHandler:
        """保存 handler 并原样返回，便于测试中直接调用。"""

        if command_type in COMMAND_HANDLERS:
            raise ValueError(f"command handler already registered for {command_type!r}")
        COMMAND_HANDLERS[command_type] = handler
        return handler

    return decorator


def control_action_handler(action: int) -> Callable[[CommandHandler], CommandHandler]:
    """注册 AnchorControlRequest action 解释函数的装饰器。"""

    action_key = int(action)

    def decorator(handler: CommandHandler) -> CommandHandler:
        """保存 handler 并原样返回，便于测试中直接调用。"""

        if action_key in CONTROL_ACTION_HANDLERS:
            raise ValueError(f"control action handler already registered for {action_key!r}")
        CONTROL_ACTION_HANDLERS[action_key] = handler
        return handler

    return decorator


class CommandExecutor:
    """把 RuntimeCommand 转换成 TrackingRuntime 可执行动作。"""

    def interpret(self, command: RuntimeCommand) -> CommandExecutionResult:
        """解释一条命令；不直接接触 pipeline/GPU 对象。"""

        handler = COMMAND_HANDLERS.get(command.command_type)
        if handler is None:
            LOGGER.warning("ignore unknown command_type=%s request_id=%s", command.command_type, command.request_id)
            return CommandExecutionResult()
        return handler(command)


@command_handler(CommandType.RESET)
def interpret_reset(_command: RuntimeCommand) -> CommandExecutionResult:
    """解释 reset command。"""

    return CommandExecutionResult(reset_tracking=True)


@command_handler(CommandType.REACQUIRE)
def interpret_reacquire(_command: RuntimeCommand) -> CommandExecutionResult:
    """解释 reacquire command。"""

    return CommandExecutionResult(reset_tracking=True)


@command_handler(CommandType.CONTROL)
def interpret_control(command: RuntimeCommand) -> CommandExecutionResult:
    """解释 control command，并按 action 注册表继续分发。"""

    action = int(getattr(command.message, "action", AnchorControlRequest.CONTROL_ACTION_UNSPECIFIED))
    handler = CONTROL_ACTION_HANDLERS.get(action)
    if handler is None:
        LOGGER.warning("ignore unknown control action=%s request_id=%s", action, command.request_id)
        return CommandExecutionResult()
    return handler(command)


@control_action_handler(AnchorControlRequest.SET_STAGE)
def interpret_set_stage(command: RuntimeCommand) -> CommandExecutionResult:
    """解释 SET_STAGE control action。"""

    stage = int(getattr(command.message, "stage", 0))
    if 1 <= stage <= 4:
        return CommandExecutionResult(stage=stage)
    LOGGER.warning("ignore invalid SET_STAGE stage=%s request_id=%s", stage, command.request_id)
    return CommandExecutionResult()


@control_action_handler(AnchorControlRequest.PAUSE)
def interpret_pause(_command: RuntimeCommand) -> CommandExecutionResult:
    """解释 PAUSE control action。"""

    return CommandExecutionResult(paused=True)


@control_action_handler(AnchorControlRequest.RESUME)
def interpret_resume(_command: RuntimeCommand) -> CommandExecutionResult:
    """解释 RESUME control action。"""

    return CommandExecutionResult(paused=False)


class CommandPump:
    """在 runtime owner 线程顺序解释并应用已接受的 command。"""

    def __init__(
        self,
        *,
        queue: CommandQueue,
        executor: CommandExecutor,
        execute_per_tick: int,
        log_execution: Callable[[object, object, int], None],
        set_paused: Callable[[bool], None],
        set_stage: Callable[[int], None],
        reset_tracking: Callable[[], None],
        get_state: Callable[[], RuntimeState],
        publish_state: Callable[..., None],
    ) -> None:
        """保存命令队列、解释器和 TrackingRuntime 回调。"""

        self.queue = queue
        self.executor = executor
        self.execute_per_tick = max(1, int(execute_per_tick))
        self._log_execution = log_execution
        self._set_paused = set_paused
        self._set_stage = set_stage
        self._reset_tracking = reset_tracking
        self._get_state = get_state
        self._publish_state = publish_state

    def execute_pending(self, *, pipeline_ready: bool) -> None:
        """执行当前 tick 额度内的 command。"""

        if not pipeline_ready:
            return
        for command in self.queue.pop_many(self.execute_per_tick):
            result = self.executor.interpret(command)
            self._log_execution(command, result, len(self.queue))
            if result.paused is not None:
                self._set_paused(bool(result.paused))
            if result.stage is not None:
                self._set_stage(int(result.stage))
            if result.reset_tracking:
                self._reset_tracking()
            self._publish_command_status(command, result)

    def _publish_command_status(self, command: RuntimeCommand, result: CommandExecutionResult) -> None:
        """发布 runtime command 执行后的状态事件。"""

        if command.command_type == CommandType.RESET:
            self._publish_state(RuntimeState.DETECTING, event="RESET_APPLIED", message="reset command 已在 runtime 线程执行。", request_id=command.request_id)
            return
        if command.command_type == CommandType.REACQUIRE:
            self._publish_state(
                RuntimeState.REACQUIRING,
                event="REACQUIRE_STARTED",
                message="reacquire command 已在 runtime 线程执行，等待后续有效 pose。",
                request_id=command.request_id,
            )
            return
        if result.paused is True:
            self._publish_state(RuntimeState.PAUSED, event="PAUSE_APPLIED", message="runtime 已暂停处理新图像。", request_id=command.request_id)
            return
        if result.paused is False:
            self._publish_state(RuntimeState.DETECTING, event="RESUME_APPLIED", message="runtime 已恢复处理新图像。", request_id=command.request_id)
            return
        if result.stage is not None:
            self._publish_state(self._get_state(), event="STAGE_SET", message=f"debug stage 已切换为 {result.stage}。", request_id=command.request_id)


__all__ = [
    "CommandDedupStore",
    "CommandExecutionResult",
    "CommandExecutor",
    "CommandHandler",
    "CommandPump",
    "CommandQueue",
    "CommandType",
    "RuntimeCommand",
    "command_handler",
    "control_action_handler",
]

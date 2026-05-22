"""v3 runtime command executor。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from egoanchor.protocol import AnchorControlRequest
from egoanchor.runtime import CommandType, RuntimeCommand

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class CommandExecutionResult:
    """单条 runtime command 的执行结果。"""

    paused: bool | None = None
    """是否修改 runtime 暂停状态；None 表示不改变当前暂停状态。"""

    stage: int | None = None
    """是否切换 debug stage；None 表示不改变当前 stage。"""

    reset_tracking: bool = False
    """是否重置 tracking 状态；由 TrackingRuntime 在主线程顺序执行。"""


CommandHandler = Callable[["CommandExecutor", RuntimeCommand], CommandExecutionResult]
"""CommandExecutor + RuntimeCommand -> CommandExecutionResult 的命令解释函数类型。"""

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
    """把 RuntimeCommand 转换成 TrackingRuntime 可执行动作。

    本类只负责查注册表并解释命令，不再显式罗列 reset/reacquire/control。
    具体命令语义在模块底部通过装饰器注册的小函数中定义，和 nats_example 的
    handler registry 风格保持一致。

    它仍然只返回轻量结果，不直接接触 pipeline/GPU 对象。
    """

    def __init__(self) -> None:
        """初始化命令解释注册表。"""

        self._command_handlers = dict(COMMAND_HANDLERS)
        """命令类型到解释函数的映射。"""

        self._control_handlers = dict(CONTROL_ACTION_HANDLERS)
        """AnchorControlRequest.action 到解释函数的映射。"""

    def register_command(self, command_type: CommandType, handler: CommandHandler) -> None:
        """注册一个 runtime command 类型解释函数。"""

        if command_type in self._command_handlers:
            raise ValueError(f"command handler already registered for {command_type!r}")
        self._command_handlers[command_type] = handler

    def register_control_action(self, action: int, handler: CommandHandler) -> None:
        """注册一个 AnchorControlRequest action 解释函数。"""

        if action in self._control_handlers:
            raise ValueError(f"control action handler already registered for {action!r}")
        self._control_handlers[int(action)] = handler

    def interpret(self, command: RuntimeCommand) -> CommandExecutionResult:
        """解释一条命令；不直接接触 pipeline/GPU 对象。"""

        handler = self._command_handlers.get(command.command_type)
        if handler is None:
            LOGGER.warning("[CommandExecutor:v3] ignore unknown command_type=%s request_id=%s", command.command_type, command.request_id)
            return CommandExecutionResult()
        return handler(self, command)

    def interpret_control(self, command: RuntimeCommand) -> CommandExecutionResult:
        """解释 control command，并按 action 注册表继续分发。"""

        action = int(getattr(command.message, "action", AnchorControlRequest.CONTROL_ACTION_UNSPECIFIED))
        handler = self._control_handlers.get(action)
        if handler is None:
            LOGGER.warning("[CommandExecutor:v3] ignore unknown control action=%s request_id=%s", action, command.request_id)
            return CommandExecutionResult()
        return handler(self, command)


@command_handler(CommandType.RESET)
def interpret_reset(executor: CommandExecutor, command: RuntimeCommand) -> CommandExecutionResult:
    """解释 reset command。"""

    return CommandExecutionResult(reset_tracking=True)


@command_handler(CommandType.REACQUIRE)
def interpret_reacquire(executor: CommandExecutor, command: RuntimeCommand) -> CommandExecutionResult:
    """解释 reacquire command。"""

    _ = executor
    _ = command
    return CommandExecutionResult(reset_tracking=True)


@command_handler(CommandType.CONTROL)
def interpret_control(executor: CommandExecutor, command: RuntimeCommand) -> CommandExecutionResult:
    """解释 control command；具体 action 由当前 CommandExecutor 的 action 注册表分发。"""

    return executor.interpret_control(command)


@control_action_handler(AnchorControlRequest.SET_STAGE)
def interpret_set_stage(executor: CommandExecutor, command: RuntimeCommand) -> CommandExecutionResult:
    """解释 SET_STAGE control action。"""

    stage = int(getattr(command.message, "stage", 0))
    if 1 <= stage <= 4:
        return CommandExecutionResult(stage=stage)
    LOGGER.warning("[CommandExecutor:v3] ignore invalid SET_STAGE stage=%s request_id=%s", stage, command.request_id)
    return CommandExecutionResult()


@control_action_handler(AnchorControlRequest.PAUSE)
def interpret_pause(executor: CommandExecutor, command: RuntimeCommand) -> CommandExecutionResult:
    """解释 PAUSE control action。"""

    return CommandExecutionResult(paused=True)


@control_action_handler(AnchorControlRequest.RESUME)
def interpret_resume(executor: CommandExecutor, command: RuntimeCommand) -> CommandExecutionResult:
    """解释 RESUME control action。"""

    return CommandExecutionResult(paused=False)


__all__ = [
    "CommandExecutionResult",
    "CommandExecutor",
    "CommandHandler",
    "command_handler",
    "control_action_handler",
]

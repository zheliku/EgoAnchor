"""TrackingRuntime 命令泵。"""

from __future__ import annotations

from collections.abc import Callable

from egoanchor.runtime import CommandExecutor, CommandQueue, RuntimeState


class CommandPump:
    """在 runtime owner 线程顺序解释并应用已接受的 command。

    NATS handler 只负责 validate/dedup/enqueue/ack；本类在 TrackingRuntime
    tick 边界消费队列，确保 pipeline/GPU 状态仍由单一 owner 线程修改。
    """

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
        """等待 runtime owner 线程执行的命令队列。"""

        self.executor = executor
        """RuntimeCommand -> CommandExecutionResult 的解释器。"""

        self.execute_per_tick = max(1, int(execute_per_tick))
        """每轮 tick 最多执行的命令数量。"""

        self._log_execution = log_execution
        """命令执行日志回调。"""

        self._set_paused = set_paused
        """修改 runtime pause 状态的回调。"""

        self._set_stage = set_stage
        """修改 pipeline debug stage 的回调。"""

        self._reset_tracking = reset_tracking
        """重置 tracking 状态的回调。"""

        self._get_state = get_state
        """读取 TrackingRuntime 当前状态的回调。"""

        self._publish_state = publish_state
        """发布 AnchorStatusEvent 的回调。"""

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

    def _publish_command_status(self, command: object, result: object) -> None:
        """发布 runtime command 执行后的状态事件。"""

        command_value = command.command_type.value
        if command_value == "reset":
            self._publish_state(RuntimeState.DETECTING, event="RESET_APPLIED", message="reset command 已在 runtime 线程执行。", request_id=command.request_id)
            return
        if command_value == "reacquire":
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


__all__ = ["CommandPump"]

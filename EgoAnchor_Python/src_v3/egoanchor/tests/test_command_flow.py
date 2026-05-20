"""v3 command request/reply 链路轻量测试。

这些测试不启动 NATS、不加载模型，只验证：
- NATS router 能把 protobuf bytes 分发给 command handler。
- handler 能快速 ack/enqueue，重复 request_id 返回 duplicate ack。
- handler 会拒绝明显非法 control 参数。
- CommandExecutor 的 runtime 语义符合 Unity 远程控制需求。
"""

from __future__ import annotations

import unittest

from egoanchor.handlers import register_command_handlers
from egoanchor.protocol import (
    CMD_ANCHOR_CONTROL,
    CMD_ANCHOR_RESET,
    AnchorControlRequest,
    CommandAck,
    MessageHeader,
    ProtobufRegistry,
    ReacquireAnchorRequest,
    ResetTrackingRequest,
    SubjectRegistry,
)
from egoanchor.routing import HandlerContext, HandlerRegistry, NatsRouter
from egoanchor.runtime import CommandDedupStore, CommandExecutor, CommandQueue, CommandType, RuntimeCommand


class CommandFlowTest(unittest.IsolatedAsyncioTestCase):
    """验证 Unity command -> Python ack/enqueue 的最小闭环。"""

    def _make_router(self, queue: CommandQueue, dedup: CommandDedupStore) -> NatsRouter:
        """构造只用于单测的 NATS router。"""

        handlers = HandlerRegistry()
        register_command_handlers(handlers)
        return NatsRouter(
            SubjectRegistry.load(),
            ProtobufRegistry(),
            handlers,
            HandlerContext(commands=queue, dedup=dedup),
        )

    async def test_reset_ack_enqueue_and_dedup(self) -> None:
        """reset 首次请求入队，重复 request_id 不重复入队并返回 duplicate ack。"""

        queue = CommandQueue(max_size=4)
        dedup = CommandDedupStore(ttl_ms=60_000)
        router = self._make_router(queue, dedup)
        request = ResetTrackingRequest(
            header=MessageHeader(request_id="req-reset-1", anchor_id="default", client_id="unity-test"),
            clear_filters=True,
            clear_anchor_pose=True,
            reason="unit_test",
        )

        reply = await router.handle_message(CMD_ANCHOR_RESET, request.SerializeToString(), reply="_INBOX.test")
        ack = CommandAck()
        ack.ParseFromString(reply)
        self.assertTrue(ack.accepted)
        self.assertFalse(ack.duplicate)
        self.assertEqual(len(queue), 1)

        duplicate_reply = await router.handle_message(CMD_ANCHOR_RESET, request.SerializeToString(), reply="_INBOX.test")
        duplicate_ack = CommandAck()
        duplicate_ack.ParseFromString(duplicate_reply)
        self.assertTrue(duplicate_ack.accepted)
        self.assertTrue(duplicate_ack.duplicate)
        self.assertEqual(len(queue), 1)

    async def test_invalid_set_stage_is_rejected(self) -> None:
        """SET_STAGE 超出 1..4 时应在 handler 层拒绝，不进入 runtime queue。"""

        queue = CommandQueue(max_size=4)
        router = self._make_router(queue, CommandDedupStore(ttl_ms=60_000))
        request = AnchorControlRequest(
            header=MessageHeader(request_id="req-stage-invalid", anchor_id="default"),
            action=AnchorControlRequest.SET_STAGE,
            stage=9,
            reason="unit_test",
        )

        reply = await router.handle_message(CMD_ANCHOR_CONTROL, request.SerializeToString(), reply="_INBOX.test")
        ack = CommandAck()
        ack.ParseFromString(reply)
        self.assertFalse(ack.accepted)
        self.assertEqual(ack.status, "INVALID_ARGUMENT")
        self.assertEqual(len(queue), 0)


class CommandExecutorTest(unittest.TestCase):
    """验证已入队 command 的 runtime 执行语义。"""

    def test_reacquire_resets_tracking_for_next_register(self) -> None:
        """reacquire 默认也应触发下一帧重新 register，而不是成为空操作。"""

        executor = CommandExecutor()
        request = ReacquireAnchorRequest(
            header=MessageHeader(request_id="req-reacquire", anchor_id="default"),
            mode=ReacquireAnchorRequest.NEXT_VALID_FRAME,
            clear_tracking_first=False,
        )
        result = executor.interpret(RuntimeCommand.from_message(CommandType.REACQUIRE, request))
        self.assertTrue(result.reset_tracking)

    def test_set_stage_does_not_implicitly_reset_tracking(self) -> None:
        """SET_STAGE 应与 Python 键盘 1/2/3/4 一致，只切 stage，不隐式 reset。"""

        executor = CommandExecutor()
        request = AnchorControlRequest(
            header=MessageHeader(request_id="req-stage", anchor_id="default"),
            action=AnchorControlRequest.SET_STAGE,
            stage=3,
        )
        result = executor.interpret(RuntimeCommand.from_message(CommandType.CONTROL, request))
        self.assertEqual(result.stage, 3)
        self.assertFalse(result.reset_tracking)


if __name__ == "__main__":
    unittest.main()
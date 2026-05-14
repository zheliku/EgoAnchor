import unittest
import sys
from pathlib import Path

SRC_V2_DIR = Path(__file__).resolve().parents[2] / "src_v2"
if str(SRC_V2_DIR) not in sys.path:
    sys.path.append(str(SRC_V2_DIR))

from egoanchor.protocol.v1.anchor_pb2 import ResetTrackingRequest
from egoanchor.protocol.v1.common_pb2 import CommandAck, MessageHeader
from egoanchor.protocol.v1.quest_pb2 import QuestStereoFrame
from egoanchor.handlers import register_command_handlers, register_quest_handlers
from egoanchor.routing import HandlerContext, HandlerRegistry, ProtobufRegistry, SubjectRegistry
from egoanchor.runtime import CommandDedupStore, CommandQueue, CommandType, LatestInputStore
from egoanchor.transport.nats_router import NatsRouter


class EgoAnchorV2HandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_reset_request_returns_ack_and_queues_command(self) -> None:
        handlers = HandlerRegistry()
        register_command_handlers(handlers)
        queue = CommandQueue()
        dedup = CommandDedupStore()
        ctx = HandlerContext(commands=queue, dedup=dedup)
        request = ResetTrackingRequest(header=MessageHeader(request_id="req-1", anchor_id="main"))

        ack = await handlers.dispatch("egoanchor.v1.cmd.anchor.reset", ctx, request)

        self.assertIsInstance(ack, CommandAck)
        self.assertTrue(ack.accepted)
        self.assertEqual(len(queue), 1)
        command = queue.get_nowait()
        self.assertEqual(command.command_type, CommandType.RESET)

    async def test_duplicate_request_does_not_queue_twice(self) -> None:
        handlers = HandlerRegistry()
        register_command_handlers(handlers)
        queue = CommandQueue()
        ctx = HandlerContext(commands=queue, dedup=CommandDedupStore())
        request = ResetTrackingRequest(header=MessageHeader(request_id="req-1", anchor_id="main"))

        first = await handlers.dispatch("egoanchor.v1.cmd.anchor.reset", ctx, request)
        second = await handlers.dispatch("egoanchor.v1.cmd.anchor.reset", ctx, request)

        self.assertTrue(first.accepted)
        self.assertTrue(second.duplicate)
        self.assertEqual(len(queue), 1)

    async def test_router_dispatches_stereo_to_latest_store(self) -> None:
        handlers = HandlerRegistry()
        register_quest_handlers(handlers)
        store = LatestInputStore()
        router = NatsRouter(SubjectRegistry.load(), ProtobufRegistry(), handlers, HandlerContext(latest_inputs=store))
        frame = QuestStereoFrame(header=MessageHeader(frame_id=42))

        response = await router.handle_message("egoanchor.v1.quest.stereo", frame.SerializeToString())

        self.assertIsNone(response)
        self.assertEqual(store.get_input_state().latest_stereo_frame_id, 42)

    async def test_router_returns_protobuf_ack_for_reset(self) -> None:
        handlers = HandlerRegistry()
        register_command_handlers(handlers)
        router = NatsRouter(
            SubjectRegistry.load(),
            ProtobufRegistry(),
            handlers,
            HandlerContext(commands=CommandQueue(), dedup=CommandDedupStore()),
        )
        request = ResetTrackingRequest(header=MessageHeader(request_id="req-1", anchor_id="main"))

        response = await router.handle_message("egoanchor.v1.cmd.anchor.reset", request.SerializeToString(), reply="_INBOX.1")

        self.assertIsNotNone(response)
        ack = CommandAck()
        ack.ParseFromString(response)
        self.assertTrue(ack.accepted)
        self.assertEqual(ack.header.request_id, "req-1")


if __name__ == "__main__":
    unittest.main()

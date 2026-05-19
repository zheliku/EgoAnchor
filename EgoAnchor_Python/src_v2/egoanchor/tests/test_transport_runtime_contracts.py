"""v2 transport/runtime 边界契约测试。"""

from __future__ import annotations

import unittest

from egoanchor.protocol import QUEST_CAMERA_INFO, QUEST_STEREO
from egoanchor.protocol import anchor_pb2, common_pb2, quest_pb2
from egoanchor.runtime import CommandQueue, QuestStreamReceiver
from egoanchor.transport import AnchorCommandService, ZmqTopicSubscriber


class TransportRuntimeContractsTest(unittest.TestCase):
    def test_zmq_topic_store_keeps_latest_payload_per_topic(self) -> None:
        subscriber = ZmqTopicSubscriber(topics=["a", "b"])

        subscriber.store.update("a", b"old")
        subscriber.store.update("b", b"camera")
        subscriber.store.update("a", b"new")

        self.assertEqual(subscriber.get_latest_payload("a"), b"new")
        self.assertEqual(subscriber.get_latest_payload("b"), b"camera")
        stats = subscriber.get_stats()
        self.assertEqual(stats.received, 3)
        self.assertEqual(stats.latest_topic_names, ("a", "b"))

    def test_quest_stream_receiver_decodes_latest_payloads(self) -> None:
        receiver = QuestStreamReceiver()
        stereo = quest_pb2.QuestStereoFrame(header=common_pb2.MessageHeader(frame_id=11), left_image_jpeg=b"l")
        camera_info = quest_pb2.QuestCameraInfo(header=common_pb2.MessageHeader(frame_id=2), baseline_m=0.064)

        receiver.subscriber.poll_latest = lambda timeout_ms=0: {  # type: ignore[method-assign]
            QUEST_STEREO: stereo.SerializeToString(),
            QUEST_CAMERA_INFO: camera_info.SerializeToString(),
        }
        decoded = receiver.poll_latest(timeout_ms=0)
        stats = receiver.get_stats()

        self.assertIn(QUEST_STEREO, decoded)
        self.assertEqual(receiver.get_latest_stereo().header.frame_id, 11)
        self.assertAlmostEqual(receiver.get_latest_camera_info().baseline_m, 0.064)
        self.assertEqual(stats.decoded_stereo, 1)
        self.assertEqual(stats.latest_stereo_frame_id, 11)

    def test_anchor_command_service_enqueues_reset_and_detects_duplicate(self) -> None:
        class DummyClient:
            def __init__(self) -> None:
                self.handlers = {}

            def subscribe_request_handler(self, subject, handler) -> None:
                self.handlers[subject] = handler

        queue = CommandQueue()
        service = AnchorCommandService(DummyClient(), queue)  # type: ignore[arg-type]
        request = anchor_pb2.ResetTrackingRequest(
            header=common_pb2.MessageHeader(request_id="req-1", anchor_id="main")
        )

        ack = common_pb2.CommandAck()
        ack.ParseFromString(service._handle_reset(request.SerializeToString()))
        self.assertTrue(ack.accepted)
        self.assertEqual(ack.status, "ENQUEUED")
        self.assertEqual(len(queue), 1)
        command = queue.pop()
        self.assertEqual(command.command_type, "reset")
        self.assertEqual(command.request_id, "req-1")
        self.assertEqual(command.anchor_id, "main")

        duplicate = common_pb2.CommandAck()
        duplicate.ParseFromString(service._handle_reset(request.SerializeToString()))
        self.assertTrue(duplicate.accepted)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(duplicate.status, "DUPLICATE")
        self.assertEqual(len(queue), 0)


if __name__ == "__main__":
    unittest.main()
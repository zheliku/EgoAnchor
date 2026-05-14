import time
import unittest
import sys
from pathlib import Path

SRC_V2_DIR = Path(__file__).resolve().parents[2] / "src_v2"
if str(SRC_V2_DIR) not in sys.path:
    sys.path.append(str(SRC_V2_DIR))

from egoanchor.protocol.v1.anchor_pb2 import ResetTrackingRequest
from egoanchor.protocol.v1.common_pb2 import CommandAck, MessageHeader
from egoanchor.protocol.v1.quest_pb2 import QuestCameraInfo, QuestStereoFrame
from egoanchor.runtime import CommandDedupStore, CommandQueue, CommandType, LatestInputStore


class EgoAnchorV2RuntimeTests(unittest.TestCase):
    def test_latest_store_rejects_stale_stereo(self) -> None:
        store = LatestInputStore()
        self.assertTrue(store.put_stereo(QuestStereoFrame(header=MessageHeader(frame_id=10))))
        self.assertFalse(store.put_stereo(QuestStereoFrame(header=MessageHeader(frame_id=9))))

        state = store.get_input_state()
        self.assertEqual(state.latest_stereo_frame_id, 10)
        self.assertEqual(state.stereo_updates, 1)
        self.assertEqual(state.dropped_stale_stereo, 1)

    def test_camera_info_version_increments(self) -> None:
        store = LatestInputStore()
        store.put_camera_info(QuestCameraInfo(header=MessageHeader(message_id="a")))
        store.put_camera_info(QuestCameraInfo(header=MessageHeader(message_id="b")))
        self.assertEqual(store.get_camera_info_version(), 2)
        self.assertTrue(store.get_input_state().has_camera_info)

    def test_command_queue_prioritizes_reset(self) -> None:
        queue = CommandQueue()
        control = ResetTrackingRequest(header=MessageHeader(request_id="control", anchor_id="main"))
        reset = ResetTrackingRequest(header=MessageHeader(request_id="reset", anchor_id="main"))

        queue.accept(CommandType.CONTROL, control)
        queue.accept(CommandType.RESET, reset)

        first = queue.get_nowait()
        self.assertIsNotNone(first)
        self.assertEqual(first.command_type, CommandType.RESET)
        self.assertEqual(first.request_id, "reset")

    def test_dedup_returns_duplicate_copy(self) -> None:
        dedup = CommandDedupStore(ttl_ms=1000)
        ack = CommandAck(header=MessageHeader(request_id="req-1"), accepted=True, status="ACCEPTED")
        dedup.remember("req-1", ack)

        duplicate = dedup.get("req-1")
        self.assertIsNotNone(duplicate)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(duplicate.status, "ACCEPTED")

    def test_dedup_ttl_expires(self) -> None:
        dedup = CommandDedupStore(ttl_ms=5)
        dedup.remember("req-1", CommandAck(header=MessageHeader(request_id="req-1"), accepted=True))
        time.sleep(0.05)
        self.assertIsNone(dedup.get("req-1"))


if __name__ == "__main__":
    unittest.main()

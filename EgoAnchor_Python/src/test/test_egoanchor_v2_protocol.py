import unittest
import sys
from pathlib import Path

SRC_V2_DIR = Path(__file__).resolve().parents[2] / "src_v2"
if str(SRC_V2_DIR) not in sys.path:
    sys.path.append(str(SRC_V2_DIR))

from egoanchor.protocol.v1.anchor_pb2 import ResetTrackingRequest
from egoanchor.protocol.v1.common_pb2 import MessageHeader
from egoanchor.protocol.v1.quest_pb2 import QuestStereoFrame
from egoanchor.routing.protobuf_registry import ProtobufRegistry
from egoanchor.routing.subjects import SubjectRegistry


class EgoAnchorV2ProtocolTests(unittest.TestCase):
    def test_subject_registry_matches_protobuf_registry(self) -> None:
        subjects = SubjectRegistry.load()
        protobufs = ProtobufRegistry()

        for spec in subjects.all():
            self.assertTrue(protobufs.has_type(spec.protobuf), spec.subject)
            if spec.reply:
                self.assertTrue(protobufs.has_type(spec.reply), spec.subject)

    def test_parse_and_serialize_roundtrip(self) -> None:
        protobufs = ProtobufRegistry()
        request = ResetTrackingRequest(
            header=MessageHeader(request_id="req-1", anchor_id="main", schema_version="v1"),
            clear_filters=True,
            reason="unit-test",
        )

        payload = protobufs.serialize(request)
        parsed = protobufs.parse("protocol.v1.ResetTrackingRequest", payload)

        self.assertIsInstance(parsed, ResetTrackingRequest)
        self.assertEqual(parsed.header.request_id, "req-1")
        self.assertTrue(parsed.clear_filters)

    def test_stereo_subject_uses_latest_only(self) -> None:
        subjects = SubjectRegistry.load()
        spec = subjects.get("egoanchor.v1.quest.stereo")
        self.assertEqual(spec.protobuf, "protocol.v1.QuestStereoFrame")
        self.assertTrue(spec.latest_only)
        self.assertEqual(QuestStereoFrame.DESCRIPTOR.full_name, spec.protobuf)


if __name__ == "__main__":
    unittest.main()

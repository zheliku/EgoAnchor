"""v2 Protobuf 与 ZMQ 数据面基础测试。

这些测试不依赖 Quest 设备，也不启动 Unity。
目的：先保证共享 Protobuf 类型、topic 常量和 Python latest store 的基础行为可用。
"""

from __future__ import annotations

import unittest

from egoanchor.protocol import QUEST_STEREO, load_subjects
from egoanchor.protocol import common_pb2, quest_pb2
from egoanchor.transport import LatestQuestInputStore


class ProtoRoundtripTest(unittest.TestCase):
    def test_quest_stereo_roundtrip(self) -> None:
        """QuestStereoFrame 序列化后应能完整反序列化关键字段。"""

        msg = quest_pb2.QuestStereoFrame(
            header=common_pb2.MessageHeader(
                message_id="test-message",
                frame_id=42,
                unity_frame=1001,
                sender_mono_ms=1234.5,
                schema_version="v1",
            ),
            left_image_jpeg=b"left-bytes",
            right_image_jpeg=b"right-bytes",
            left_width=640,
            left_height=480,
            right_width=640,
            right_height=480,
            jpeg_quality=85,
        )

        decoded = quest_pb2.QuestStereoFrame()
        decoded.ParseFromString(msg.SerializeToString())

        self.assertEqual(decoded.header.frame_id, 42)
        self.assertEqual(decoded.left_image_jpeg, b"left-bytes")
        self.assertEqual(decoded.right_width, 640)
        self.assertEqual(decoded.jpeg_quality, 85)

    def test_subject_constants_match_contract_names(self) -> None:
        """Python topic 常量必须与 subjects.v1.json 中的 v2 名称一致。"""

        loaded = load_subjects()
        self.assertIn(QUEST_STEREO, loaded)
        self.assertEqual(loaded[QUEST_STEREO].transport, "zmq")
        self.assertEqual(loaded[QUEST_STEREO].protobuf, "protocol.v1.QuestStereoFrame")

    def test_latest_store_keeps_latest_frame(self) -> None:
        """LatestQuestInputStore 应以最新 stereo 覆盖旧 stereo。"""

        store = LatestQuestInputStore()
        first = quest_pb2.QuestStereoFrame(header=common_pb2.MessageHeader(frame_id=1))
        second = quest_pb2.QuestStereoFrame(header=common_pb2.MessageHeader(frame_id=2))

        store.update_stereo(first)
        store.update_stereo(second)
        stats = store.snapshot_stats()

        self.assertEqual(store.latest_stereo.header.frame_id, 2)
        self.assertEqual(stats.decoded_stereo, 2)
        self.assertEqual(stats.latest_stereo_frame_id, 2)


if __name__ == "__main__":
    unittest.main()

"""v2 Protobuf 与 ZMQ 数据面基础测试。

这些测试不依赖 Quest 设备，也不启动 Unity。
目的：先保证共享 Protobuf 类型、topic 常量和 Python latest store 的基础行为可用。
"""

from __future__ import annotations

import unittest

from egoanchor.perception import PoseObservation
from egoanchor.protocol import POSE_RESULT, QUEST_STEREO, load_subjects
from egoanchor.protocol import common_pb2, quest_pb2
from egoanchor.runtime import LatestQuestInputStore, pose_result_from_observation


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
        self.assertIn(POSE_RESULT, loaded)
        self.assertEqual(loaded[POSE_RESULT].transport, "nats")
        self.assertEqual(loaded[POSE_RESULT].protobuf, "protocol.v1.PoseResult")

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

    def test_pose_result_from_observation_roundtrip(self) -> None:
        """PoseObservation 应能映射为 PoseResult 并保持 frame_id/矩阵字段。"""

        matrix = tuple(float(i) for i in range(16))
        msg = pose_result_from_observation(
            PoseObservation(
                has_pose=True,
                phase="TRACK",
                frame_id=123,
                pose_matrix_cv_camera=matrix,
                stage=4,
                det_count=1,
                depth_valid_ratio=0.8,
                depth_valid_in_mask=0.7,
                fps=20.0,
                yolo_ms=1.0,
                depth_ms=2.0,
                cutie_ms=3.0,
                pose_ms=4.0,
            )
        )
        decoded = type(msg)()
        decoded.ParseFromString(msg.SerializeToString())

        self.assertTrue(decoded.has_pose)
        self.assertEqual(decoded.header.frame_id, 123)
        self.assertEqual(decoded.phase, "TRACK")
        self.assertEqual(list(decoded.pose_matrix_cv_camera.values), list(matrix))
        self.assertAlmostEqual(decoded.timing.total_ms, 10.0)

    def test_pose_result_invalid_matrix_downgrades_to_no_pose(self) -> None:
        """has_pose=true 但矩阵长度非法时应降级为 NO_POSE，避免发出破坏协议的包。"""

        msg = pose_result_from_observation(
            PoseObservation(
                has_pose=True,
                phase="BAD_MATRIX",
                frame_id=7,
                pose_matrix_cv_camera=(1.0, 2.0),
            )
        )

        self.assertFalse(msg.has_pose)
        self.assertEqual(msg.header.frame_id, 7)
        self.assertEqual(len(msg.pose_matrix_cv_camera.values), 0)
        self.assertEqual(msg.last_error.code, "NO_POSE")


if __name__ == "__main__":
    unittest.main()

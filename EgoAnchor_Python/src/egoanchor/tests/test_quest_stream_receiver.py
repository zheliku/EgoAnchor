"""Quest stream receiver latest cache 契约测试。"""

from __future__ import annotations

import unittest

from egoanchor.protocol import MessageHeader, QuestCameraInfo, QuestStereoFrame
from egoanchor.runtime import LatestQuestInputStore


class LatestQuestInputStoreTest(unittest.TestCase):
    """验证 Quest 输入 latest cache 的 session 边界语义。"""

    def test_new_camera_info_session_clears_old_stereo(self) -> None:
        """Unity 重启后 camera_info 先到时，不应继续保留旧 session 的 stereo。"""

        store = LatestQuestInputStore()
        old_stereo = QuestStereoFrame(header=MessageHeader(frame_id=5, session_id="old", client_id="quest"))
        new_camera_info = QuestCameraInfo(header=MessageHeader(frame_id=0, session_id="new", client_id="quest"))

        self.assertTrue(store.update_stereo(old_stereo))
        store.update_camera_info(new_camera_info)

        self.assertIsNone(store.latest_stereo)
        self.assertIsNone(store.latest_stereo_frame_id)
        self.assertEqual(store.latest_camera_info_frame_id, 0)
        self.assertEqual(store.latest_session_id, "new")
        self.assertEqual(store.stream_restarts, 1)

    def test_new_stereo_session_clears_old_camera_info(self) -> None:
        """Unity 重启后 stereo 先到时，不应继续复用旧 session 的 camera_info。"""

        store = LatestQuestInputStore()
        old_camera_info = QuestCameraInfo(header=MessageHeader(frame_id=5, session_id="old", client_id="quest"))
        old_stereo = QuestStereoFrame(header=MessageHeader(frame_id=5, session_id="old", client_id="quest"))
        new_stereo = QuestStereoFrame(header=MessageHeader(frame_id=0, session_id="new", client_id="quest"))

        store.update_camera_info(old_camera_info)
        self.assertTrue(store.update_stereo(old_stereo))
        self.assertTrue(store.update_stereo(new_stereo))

        self.assertIsNone(store.latest_camera_info)
        self.assertIsNone(store.latest_camera_info_frame_id)
        self.assertEqual(store.camera_info_version, 0)
        self.assertEqual(store.latest_stereo_frame_id, 0)
        self.assertEqual(store.latest_session_id, "new")
        self.assertEqual(store.stream_restarts, 1)

    def test_stereo_receive_timestamp_is_preserved(self) -> None:
        """latest stereo 的 Python 接收时刻应供 PoseResult 延迟字段使用。"""

        store = LatestQuestInputStore()
        stereo = QuestStereoFrame(header=MessageHeader(frame_id=5, session_id="unit", client_id="quest"))

        self.assertTrue(store.update_stereo(stereo, receive_mono_ms=1234.5))
        stats = store.snapshot_stats(received=1, invalid_multipart=0, zmq_errors=0)

        self.assertAlmostEqual(store.latest_stereo_receive_mono_ms, 1234.5)
        self.assertAlmostEqual(stats.latest_stereo_receive_mono_ms, 1234.5)


if __name__ == "__main__":
    unittest.main()

"""Protobuf header 工具函数契约测试。"""

from __future__ import annotations

import unittest

from egoanchor.protocol import MessageHeader, QuestCameraInfo, QuestStereoFrame, extract_client_id, extract_frame_id, extract_session_id


class HeaderUtilsTest(unittest.TestCase):
    """验证 Quest stereo/camera_info 共用 header 提取逻辑。"""

    def test_extracts_header_fields_from_stereo(self) -> None:
        """工具函数应从 stereo header 提取 frame/session/client。"""

        msg = QuestStereoFrame(header=MessageHeader(frame_id=42, session_id="session-a", client_id="quest"))

        self.assertEqual(extract_frame_id(msg), 42)
        self.assertEqual(extract_session_id(msg), "session-a")
        self.assertEqual(extract_client_id(msg), "quest")

    def test_missing_header_returns_empty_values(self) -> None:
        """缺少 header 时应返回 None 或空字符串，调用方无需捕获异常。"""

        msg = QuestCameraInfo()

        self.assertIsNone(extract_frame_id(msg))
        self.assertEqual(extract_session_id(msg), "")
        self.assertEqual(extract_client_id(msg), "")


if __name__ == "__main__":
    unittest.main()

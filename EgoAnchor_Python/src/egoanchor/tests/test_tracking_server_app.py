"""tracking_server app 层轻量行为测试。"""

from __future__ import annotations

import unittest

from egoanchor.app.tracking_server import should_show_waiting_frame


class TrackingServerAppTest(unittest.TestCase):
    """验证 OpenCV debug 窗口等待画面的显示策略。"""

    def test_waiting_frame_is_not_redrawn_after_dashboard_exists(self) -> None:
        """已有 dashboard 后 idle tick 不应重新覆盖 waiting 画面，避免 SAM3 阶段闪烁。"""

        self.assertTrue(should_show_waiting_frame(has_debug_frame=False))
        self.assertFalse(should_show_waiting_frame(has_debug_frame=True))


if __name__ == "__main__":
    unittest.main()

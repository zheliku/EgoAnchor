"""tracking_server app 层轻量行为测试。"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from egoanchor.app import run_tracking_server, should_show_waiting_frame


class _StopLoop(RuntimeError):
    """测试用异常，用于从 tracking_server 主循环中退出。"""


class _FakeRuntime:
    """测试用 runtime，只记录 tick 参数并立刻中止主循环。"""

    endpoint = "unit://endpoint"

    def __init__(self) -> None:
        """初始化调用记录。"""

        self.tick_return_debug_values: list[bool] = []
        self.closed = False

    def start(self) -> None:
        """测试中不需要真实启动网络和模型。"""

    def tick(self, return_debug: bool = False) -> SimpleNamespace:
        """记录 return_debug 参数，然后结束测试主循环。"""

        self.tick_return_debug_values.append(bool(return_debug))
        raise _StopLoop("stop test loop")

    def close(self) -> None:
        """记录 runtime 已经被关闭。"""

        self.closed = True


class TrackingServerAppTest(unittest.TestCase):
    """验证 OpenCV debug 窗口等待画面的显示策略。"""

    def test_waiting_frame_is_not_redrawn_after_dashboard_exists(self) -> None:
        """已有 dashboard 后 idle tick 不应重新覆盖 waiting 画面，避免 SAM3 阶段闪烁。"""

        self.assertTrue(should_show_waiting_frame(has_debug_frame=False))
        self.assertFalse(should_show_waiting_frame(has_debug_frame=True))

    def test_tracking_window_disabled_skips_opencv_window_calls(self) -> None:
        """关闭 tracking window 时不应调用 OpenCV 窗口 API，便于 Ubuntu headless 运行。"""

        fake_runtime = _FakeRuntime()
        cfg = SimpleNamespace(
            paths=SimpleNamespace(subjects_path="subjects.v1.json"),
            demo=SimpleNamespace(
                pose=SimpleNamespace(
                    debug_window_name="debug",
                    score_window_name="score",
                    debug_window_width=320,
                    debug_window_height=240,
                    score_window_width=320,
                    score_window_height=240,
                    wait_log_interval_s=999.0,
                )
            ),
            pipeline=SimpleNamespace(depth=SimpleNamespace(min_depth=0.1, max_depth=5.0)),
            debug=SimpleNamespace(enable_tracking_window=False),
        )
        app_globals = run_tracking_server.__globals__
        create_window = Mock()

        with (
            patch.dict(app_globals, {"load_config": lambda _path, object_name=None: cfg, "TrackingRuntime": lambda _cfg, _subjects: fake_runtime}),
            patch.object(app_globals["SubjectRegistry"], "load", return_value=object()),
            patch.object(app_globals["cv2"], "imshow") as imshow,
            patch.object(app_globals["cv2"], "waitKey") as wait_key,
            patch.dict(app_globals, {"_create_fixed_window": create_window}),
        ):
            with self.assertRaises(_StopLoop):
                run_tracking_server()

        create_window.assert_not_called()
        imshow.assert_not_called()
        wait_key.assert_not_called()
        self.assertEqual(fake_runtime.tick_return_debug_values, [False])
        self.assertTrue(fake_runtime.closed)


if __name__ == "__main__":
    unittest.main()

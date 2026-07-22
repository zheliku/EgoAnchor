"""tracking_server app 层轻量行为测试。"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from egoanchor.app import run_tracking_server, should_show_waiting_frame
from egoanchor.perception import FrameDiagnostics


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


class _SequenceRuntime:
    """测试用 runtime，按顺序返回多帧输出后中止主循环。"""

    endpoint = "unit://endpoint"

    def __init__(self, frame_count: int) -> None:
        """构造固定数量的新帧输出。"""

        self._remaining = int(frame_count)
        self.tick_return_debug_values: list[bool] = []
        self.closed = False

    def start(self) -> None:
        """测试中不需要真实启动网络和模型。"""

    def tick(self, return_debug: bool = False) -> SimpleNamespace:
        """返回一帧最小 pipeline 输出，耗尽后退出测试循环。"""

        self.tick_return_debug_values.append(bool(return_debug))
        if self._remaining <= 0:
            raise _StopLoop("stop test loop")
        self._remaining -= 1
        output = SimpleNamespace(diagnostics=FrameDiagnostics(), observation=object())
        return SimpleNamespace(pipeline_output=output, new_frame_processed=True)

    def close(self) -> None:
        """记录 runtime 已经被关闭。"""

        self.closed = True


class TrackingServerAppTest(unittest.TestCase):
    """验证 OpenCV debug 窗口等待画面的显示策略。"""

    def test_waiting_frame_is_not_redrawn_after_dashboard_exists(self) -> None:
        """已有 dashboard 后 idle tick 不应重新覆盖 waiting 画面，避免 SAM3 阶段闪烁。"""

        self.assertTrue(should_show_waiting_frame(has_debug_frame=False))
        self.assertFalse(should_show_waiting_frame(has_debug_frame=True))

    def test_snapshot_key_is_case_insensitive(self) -> None:
        """S 快照热键应同时接受大小写，且不与其他控制键混淆。"""

        is_snapshot_key = run_tracking_server.__globals__["_is_snapshot_key"]

        self.assertTrue(is_snapshot_key(ord("s")))
        self.assertTrue(is_snapshot_key(ord("S")))
        self.assertFalse(is_snapshot_key(ord("r")))

    def test_debug_snapshots_are_written_at_configured_resolution(self) -> None:
        """快照应重新生成独立高分辨率 PNG，而不是保存窗口缩放后的画面。"""

        save_snapshots = run_tracking_server.__globals__["_save_debug_snapshots"]
        output = SimpleNamespace(diagnostics=FrameDiagnostics(frame_id=42), observation=None)
        pose_cfg = SimpleNamespace(
            snapshot_output_dir="snapshots",
            snapshot_pose_width=320,
            snapshot_pose_height=180,
            snapshot_score_width=300,
            snapshot_score_height=240,
        )
        depth_cfg = SimpleNamespace(min_depth=0.1, max_depth=5.0)

        with TemporaryDirectory() as temporary_dir:
            pose_path, score_path = save_snapshots(output, pose_cfg, depth_cfg, Path(temporary_dir))
            pose_image = cv2.imread(str(pose_path), cv2.IMREAD_COLOR)
            score_image = cv2.imread(str(score_path), cv2.IMREAD_COLOR)

        self.assertEqual(pose_path.parent.name, "snapshots")
        self.assertIn("frame-42", pose_path.name)
        self.assertEqual(pose_image.shape[:2], (180, 320))
        self.assertEqual(score_image.shape[:2], (240, 300))

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

    def test_score_debug_rendering_is_rate_limited_independently(self) -> None:
        """评分窗口应按独立帧率上限重绘，避免每帧重复构建重型诊断矩阵。"""

        fake_runtime = _SequenceRuntime(frame_count=3)
        cfg = SimpleNamespace(
            paths=SimpleNamespace(subjects_path="subjects.v1.json"),
            demo=SimpleNamespace(
                pose=SimpleNamespace(
                    debug_window_name="debug",
                    score_window_name="score",
                    debug_window_width=320,
                    debug_window_height=240,
                    debug_window_max_fps=0.0,
                    score_window_width=320,
                    score_window_height=240,
                    score_window_max_fps=5.0,
                    wait_log_interval_s=999.0,
                )
            ),
            pipeline=SimpleNamespace(depth=SimpleNamespace(min_depth=0.1, max_depth=5.0)),
            debug=SimpleNamespace(enable_tracking_window=True),
        )
        app_globals = run_tracking_server.__globals__
        dashboard = Mock(return_value=np.zeros((240, 320, 3), dtype=np.uint8))
        score_view = Mock(return_value=np.zeros((240, 320, 3), dtype=np.uint8))

        with (
            patch.dict(
                app_globals,
                {
                    "load_config": lambda _path, object_name=None: cfg,
                    "TrackingRuntime": lambda _cfg, _subjects: fake_runtime,
                    "tile_pose_depth_dashboard": dashboard,
                    "make_score_debug_view": score_view,
                    "make_pose_waiting_image": lambda _width, _height, _title: np.zeros((240, 320, 3), dtype=np.uint8),
                    "_create_fixed_window": Mock(),
                    "_destroy_window_if_created": Mock(),
                },
            ),
            patch.object(app_globals["SubjectRegistry"], "load", return_value=object()),
            patch.object(app_globals["cv2"], "imshow"),
            patch.object(app_globals["cv2"], "waitKey", return_value=255),
            patch.object(app_globals["time"], "perf_counter", side_effect=[100.0 + index * 0.01 for index in range(20)]),
        ):
            with self.assertRaises(_StopLoop):
                run_tracking_server()

        self.assertEqual(dashboard.call_count, 3)
        self.assertEqual(score_view.call_count, 1)
        self.assertEqual(fake_runtime.tick_return_debug_values, [True, True, True, True])
        self.assertTrue(fake_runtime.closed)


if __name__ == "__main__":
    unittest.main()

"""TrackingRuntime 生命周期边界测试。"""

from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from egoanchor.config import load_config
from egoanchor.protocol import SubjectRegistry
from egoanchor.runtime import TrackingRuntime


class _LifecycleProbe:
    """记录 start/close 调用次数的测试替身。"""

    endpoint = "inproc://test"

    def __init__(self) -> None:
        """初始化调用计数。"""

        self.started = 0
        self.closed = 0
        self.events: list[tuple[str, object]] = []

    def start(self) -> None:
        """记录启动调用。"""

        self.started += 1

    def close(self) -> None:
        """记录关闭调用。"""

        self.closed += 1

    def event(self, event_type: str, **fields: object) -> None:
        """记录日志事件调用。"""

        self.events.append((event_type, fields))


class TrackingRuntimeLifecycleTest(unittest.TestCase):
    """验证 runtime 启动失败时不会遗留已启动资源。"""

    def test_start_cleans_started_resources_when_pipeline_build_fails(self) -> None:
        """pipeline 构建抛错时，应关闭已启动 receiver、publisher 和日志句柄。"""

        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config()
            cfg.runtime.logging.output_dir = tmp
            cfg.runtime.logging.eval_session_enabled = False
            cfg.network.message_plane.enabled = False
            runtime = TrackingRuntime(cfg, SubjectRegistry.load())
            receiver = _LifecycleProbe()
            publisher = _LifecycleProbe()
            log_writer = _LifecycleProbe()
            runtime.receiver = receiver
            runtime.pose_publisher = publisher
            runtime.log_writer = log_writer

            with patch("egoanchor.perception.build_quest_pose_pipeline", side_effect=RuntimeError("pipeline boom")):
                with self.assertRaisesRegex(RuntimeError, "pipeline boom"):
                    runtime.start()

            self.assertFalse(runtime.started)
            self.assertIsNone(runtime.pipeline)
            self.assertEqual(receiver.started, 1)
            self.assertEqual(receiver.closed, 1)
            self.assertEqual(publisher.started, 1)
            self.assertEqual(publisher.closed, 1)
            self.assertEqual(log_writer.closed, 1)


if __name__ == "__main__":
    unittest.main()

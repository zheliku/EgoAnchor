"""Python eval session 目录协调测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from egoanchor.config import load_config
from egoanchor.protocol import SubjectRegistry
from egoanchor.runtime import TrackingRuntime, create_eval_session


class EvalSessionCoordinatorTest(unittest.TestCase):
    """验证 Python 先创建可被 Unity 自动复用的 eval session 目录。"""

    def test_create_eval_session_writes_metadata_and_unique_session_dir(self) -> None:
        """同秒重复启动时应追加后缀，并写出 Unity 可读的 python_session.json。"""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            now = datetime(2026, 6, 2, 15, 57, 23)

            first = create_eval_session(root, "controller_right", now=now)
            second = create_eval_session(root, "controller_right", now=now)

            self.assertEqual(first.session_id, "20260602_155723_controller_right")
            self.assertEqual(second.session_id, "20260602_155723_controller_right_02")
            self.assertEqual(first.python_log_filename, "python_candidates.jsonl")
            self.assertTrue(first.session_dir.is_dir())

            metadata = json.loads(first.metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["session_id"], first.session_id)
            self.assertEqual(metadata["object_id"], "controller_right")
            self.assertEqual(metadata["python_log_filename"], first.python_log_filename)
            self.assertEqual(metadata["state"], "python_started")

    def test_tracking_runtime_uses_eval_session_dir_when_enabled(self) -> None:
        """启用 eval session 后，runtime JSONL 应直接写入共享 session 目录。"""

        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(object_name="controller_right")
            cfg.network.message_plane.enabled = False
            cfg.runtime.logging.eval_session_enabled = True
            cfg.runtime.logging.eval_output_dir = tmp
            runtime = TrackingRuntime(cfg, SubjectRegistry.load())

            try:
                runtime.log_writer.event("unit_test")
            finally:
                runtime.log_writer.close()

            session_dir = runtime.log_writer.logger.log_path.parent
            metadata_path = session_dir / "python_session.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

            self.assertEqual(runtime.session_id, session_dir.name)
            self.assertTrue(runtime.session_id.endswith("_controller_right"))
            self.assertEqual(metadata["python_log_filename"], "python_candidates.jsonl")
            self.assertEqual(metadata["events_log_filename"], "events.jsonl")
            self.assertTrue((session_dir / "events.jsonl").exists())
            self.assertTrue((session_dir / "python_candidates.jsonl").exists())
            self.assertEqual(metadata["object_id"], "controller_right")


if __name__ == "__main__":
    unittest.main()

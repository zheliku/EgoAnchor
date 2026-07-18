"""Python 评估 session 命名契约测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from egoanchor.runtime import create_eval_session


class EvalSessionTest(unittest.TestCase):
    """验证 session 元数据不能制造 schema-v2 文件名冲突。"""

    def test_default_schema_v2_filenames_are_distinct(self) -> None:
        """默认候选和事件日志必须使用不同的冻结文件名。"""

        with tempfile.TemporaryDirectory() as tmp:
            paths = create_eval_session(Path(tmp), "controller_right")

            self.assertEqual(paths.python_log_filename, "python_candidates.jsonl")
            self.assertEqual(paths.python_events_log_filename, "python_events.jsonl")
            metadata = paths.metadata_path.read_text(encoding="utf-8")
            self.assertIn('"python_log_filename": "python_candidates.jsonl"', metadata)
            self.assertIn('"python_events_log_filename": "python_events.jsonl"', metadata)

    def test_events_filename_cannot_be_used_for_candidates(self) -> None:
        """候选日志不得复用正式事件文件名。"""

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "python_candidates.jsonl"):
                create_eval_session(Path(tmp), "controller_right", python_log_filename="events.jsonl")


if __name__ == "__main__":
    unittest.main()

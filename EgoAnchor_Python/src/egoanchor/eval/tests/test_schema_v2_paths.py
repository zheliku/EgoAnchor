"""schema-v2 固定路径契约测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from egoanchor.eval.schema_v2 import EvalV2Paths


class SchemaV2PathsTest(unittest.TestCase):
    """验证正式评估文件名不再由 session id 或 glob 推断。"""

    def test_schema_v2_paths_are_fixed(self) -> None:
        """所有跨端文件必须使用计划冻结的固定名称。"""

        with tempfile.TemporaryDirectory() as tmp:
            paths = EvalV2Paths.for_session(Path(tmp) / "s01")

            self.assertEqual(paths.manifest.name, "manifest.json")
            self.assertEqual(paths.python_candidates.name, "python_candidates.jsonl")
            self.assertEqual(paths.python_events.name, "python_events.jsonl")
            self.assertEqual(paths.unity_events.name, "unity_events.jsonl")
            self.assertEqual(paths.unity_reference.name, "unity_reference.jsonl")
            self.assertEqual(paths.unity_admission.name, "unity_admission.jsonl")
            self.assertEqual(paths.unity_render.name, "unity_render.jsonl")
            self.assertEqual(paths.events.name, "events.jsonl")
            self.assertEqual(paths.audit_samples.name, "audit_samples")


if __name__ == "__main__":
    unittest.main()

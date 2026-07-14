"""schema-v2 QC 契约测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from egoanchor.eval.schema_v2 import load_session_v2, run_schema_qc
from egoanchor.eval.tests.test_schema_v2_reader import _write_minimal_session


class SchemaV2QcTest(unittest.TestCase):
    """验证采集前必须满足的结构性质量门禁。"""

    def test_complete_session_passes_qc(self) -> None:
        """完整的 render tick × variant 矩阵应通过 QC。"""

        with tempfile.TemporaryDirectory() as tmp:
            report = run_schema_qc(load_session_v2(_write_minimal_session(Path(tmp))))

            self.assertTrue(report.passed, report.errors)

    def test_missing_render_variant_fails_qc(self) -> None:
        """任一 tick 缺少固定变体时必须失败。"""

        with tempfile.TemporaryDirectory() as tmp:
            session_dir = _write_minimal_session(Path(tmp))
            render_path = session_dir / "unity_render.jsonl"
            render_path.write_text(render_path.read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8")

            report = run_schema_qc(load_session_v2(session_dir))

            self.assertFalse(report.passed)
            self.assertTrue(any("render tick" in error for error in report.errors))


if __name__ == "__main__":
    unittest.main()

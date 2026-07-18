"""Task 9 analyze CLI 的 Stage 2 输入边界测试。"""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from egoanchor.eval import cli as eval_cli


class AnalyzeCliTests(unittest.TestCase):
    """验证 analyze 的文件系统错误、数据错误和无产物门禁。"""

    def test_missing_xlsx_returns_io_error_without_output(self) -> None:
        """输入 workbook 不存在时返回一且不创建结果目录。"""

        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp) / "results"
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = eval_cli.main(
                    ["analyze", str(Path(tmp) / "missing.xlsx"), "--out", str(output_root)]
                )
            self.assertEqual(code, eval_cli.EXIT_IO_ERROR)
            self.assertFalse(output_root.exists())

    def test_incomplete_xlsx_returns_data_error_without_output(self) -> None:
        """schema/workbook 不完整时返回二且不发布任何 CSV。"""

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "task_1_complete.xlsx"
            workbook = Workbook()
            workbook.active.title = "manifest"
            workbook.save(source)
            output_root = Path(tmp) / "results"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = eval_cli.main(["analyze", str(source), "--out", str(output_root)])
            self.assertEqual(code, eval_cli.EXIT_DATA_ERROR)
            self.assertFalse(output_root.exists())


if __name__ == "__main__":
    unittest.main()

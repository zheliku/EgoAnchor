"""GPT v4 论文分析入口的边界与最小计算测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook  # type: ignore[import-untyped]

from egoanchor.eval import cli as eval_cli
from egoanchor.eval.gpt_v4 import iter_rows


class GptV4PipelineTests(unittest.TestCase):
    """冻结新管线只读取 Stage 1 XLSX 且不恢复旧阶段命令。"""

    def test_cli_replaces_old_analysis_stages_with_one_paper_build(self) -> None:
        """旧 analyze/publish/materialize 命令不得作为兼容层保留。"""

        self.assertEqual(eval_cli.STAGE_COMMANDS, ("qc", "preprocess", "build-paper"))

    def test_xlsx_reader_streams_selected_columns_from_stage_one_sheet(self) -> None:
        """新分析 reader 直接消费 Stage 1 sheet，不改写原始 workbook。"""

        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "task_1_complete.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "unity_render"
            sheet.append(("session_id", "variant_id", "render_mono_ms", "unused"))
            sheet.append(("session", "EgoAnchor", 123.5, "ignored"))
            workbook.save(path)
            before = path.read_bytes()

            rows = list(iter_rows(path, "unity_render", ("variant_id", "render_mono_ms")))

            self.assertEqual(
                rows,
                [{"variant_id": "EgoAnchor", "render_mono_ms": 123.5}],
            )
            self.assertEqual(path.read_bytes(), before)

    def test_build_paper_rejects_non_xlsx_input_before_writing(self) -> None:
        """论文入口拒绝 JSON/CSV，保持初始 XLSX 是唯一分析桥梁。"""

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "task_1.json"
            source.write_text("{}", encoding="utf-8")
            output = root / "output"

            code = eval_cli.main(
                [
                    "build-paper",
                    str(source),
                    "--out",
                    str(output),
                    "--paper-root",
                    str(root / "paper"),
                ]
            )

            self.assertEqual(code, eval_cli.EXIT_DATA_ERROR)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()

"""评估包入口和运行时依赖边界测试。"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import unittest
from pathlib import Path
from unittest import mock

from egoanchor.eval import PythonCandidateRow, SchemaV2Error
from egoanchor.eval import cli as eval_cli


EVAL_ROOT = Path(__file__).resolve().parents[1]
"""评估包根目录，用于检查旧实现是否已删除。"""

EXPECTED_COMMANDS = {
    "config",
    "sessions",
    "stage",
    "promote",
    "qc",
    "preprocess",
    "analyze",
    "copy-assets",
    "rebuild",
}
"""当前唯一人工入口的固定路径命令。"""


class EvalBoundaryTests(unittest.TestCase):
    """验证新包骨架、统一入口和 schema-v2 运行时边界。"""

    def test_schema_v2_remains_the_runtime_boundary(self) -> None:
        """schema-v2 的公开行类型仍可通过评估包级入口导入。"""

        self.assertIsNotNone(PythonCandidateRow)
        self.assertTrue(issubclass(SchemaV2Error, Exception))

    def test_old_analysis_paths_are_absent(self) -> None:
        """旧离线分析目录和单文件入口不得继续存在。"""

        for relative_path in (
            "analysis",
            "experiments",
            "metrics",
            "paper",
            "publishing",
            "figure_style.py",
            "excel.py",
        ):
            target = EVAL_ROOT / relative_path
            if target.is_dir():
                self.assertFalse(any(target.rglob("*.py")), relative_path)
            else:
                self.assertFalse(target.exists(), relative_path)

        for module_name in (
            "egoanchor.eval.experiments",
            "egoanchor.eval.metrics",
            "egoanchor.eval.paper",
            "egoanchor.eval.analysis",
            "egoanchor.eval.publishing",
        ):
            try:
                spec = importlib.util.find_spec(module_name)
            except ModuleNotFoundError:
                continue
            if spec is not None and spec.submodule_search_locations:
                self.assertFalse(
                    any(
                        path.is_file()
                        for location in spec.submodule_search_locations
                        for path in Path(location).glob("*.py")
                    ),
                    module_name,
                )

    def test_cli_exposes_only_fixed_path_workflow_commands(self) -> None:
        """统一 CLI 不再保留要求手工拼路径的旧命令。"""

        parser = eval_cli.build_parser()
        subparsers = next(
            action
            for action in parser._actions
            if getattr(action, "choices", None) is not None
        )
        self.assertEqual(set(subparsers.choices), EXPECTED_COMMANDS)

    def test_cli_without_arguments_prints_help(self) -> None:
        """无参数启动 CLI 时打印帮助并成功返回。"""

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = eval_cli.main([])

        self.assertEqual(result, eval_cli.EXIT_OK)
        self.assertIn("analyze", output.getvalue())

    def test_analyze_help_declares_current_workbook_input(self) -> None:
        """论文入口应明确读取当前五本 Stage 1 XLSX。"""

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                eval_cli.main(["analyze", "--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("当前五本 XLSX", output.getvalue())

    def test_stage_rejects_removed_directory_arguments(self) -> None:
        """stage 不再接受五个长目录名，防止旧入口继续被误用。"""

        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                eval_cli.build_parser().parse_args(["stage", "task_1_directory"])

        self.assertEqual(raised.exception.code, 2)

    def test_stage_accepts_short_version_selectors(self) -> None:
        """stage 接受统一版本、逐任务版本和对象筛选。"""

        args = eval_cli.build_parser().parse_args(
            ["stage", "--version", "v2", "--task-version", "3=v4", "--object", "cube"]
        )

        self.assertEqual(args.version, 2)
        self.assertEqual(args.task_version, ["3=v4"])
        self.assertEqual(args.object_name, "cube")

    def test_failed_qc_payload_returns_exit_code_two(self) -> None:
        """QC 完整报告为失败时，CLI 必须保留 JSON 并返回退出码二。"""

        output = io.StringIO()
        with mock.patch.object(eval_cli, "qc_current", return_value={"passed": False, "tasks": []}):
            with contextlib.redirect_stdout(output):
                result = eval_cli.main(["qc"])

        self.assertEqual(result, eval_cli.EXIT_DATA_ERROR)
        self.assertIn('"passed": false', output.getvalue())


if __name__ == "__main__":
    unittest.main()

"""Task 1 新评估包骨架和运行时依赖边界测试。"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import unittest
from pathlib import Path

from egoanchor.eval import PythonCandidateRow, SchemaV2Error
from egoanchor.eval import cli as eval_cli


EVAL_ROOT = Path(__file__).resolve().parents[1]
"""评估包根目录，用于检查旧实现是否已删除。"""

EXPECTED_COMMANDS = {
    "qc",
    "preprocess",
    "analyze",
    "publish",
    "materialize-paper",
}
"""Task 1 冻结的统一 CLI 子命令集合。"""


class TaskOneSkeletonTests(unittest.TestCase):
    """验证新包骨架、统一入口和 schema-v2 运行时边界。"""

    def test_schema_v2_remains_the_runtime_boundary(self) -> None:
        """schema-v2 的公开行类型仍可通过评估包级入口导入。"""

        self.assertIsNotNone(PythonCandidateRow)
        self.assertTrue(issubclass(SchemaV2Error, Exception))

    def test_old_analysis_paths_are_absent(self) -> None:
        """旧离线分析目录和单文件入口不得继续存在。"""

        for relative_path in (
            "experiments",
            "metrics",
            "paper",
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

    def test_cli_exposes_only_new_stage_commands(self) -> None:
        """统一 CLI 只暴露五个阶段命令。"""

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
        self.assertIn("materialize-paper", output.getvalue())


if __name__ == "__main__":
    unittest.main()

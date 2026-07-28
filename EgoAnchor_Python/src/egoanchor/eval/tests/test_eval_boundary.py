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
    "status",
    "validate",
    "analyze",
    "copy-assets",
    "data",
}
"""统一评估工程固定的五个生命周期入口。"""


class EvalBoundaryTests(unittest.TestCase):
    """验证新包骨架、统一入口和 schema-v2 运行时边界。"""

    def test_schema_v2_remains_the_runtime_boundary(self) -> None:
        """schema-v2 的公开行类型仍可通过评估包级入口导入。"""

        self.assertIsNotNone(PythonCandidateRow)
        self.assertTrue(issubclass(SchemaV2Error, Exception))

    def test_experiment_packages_replace_old_cross_cutting_paths(self) -> None:
        """实验包并列存在，旧 paper_analysis/workflows 源码入口已经删除。"""

        for relative_path in (
            "analysis",
            "metrics",
            "paper",
            "publishing",
            "paper_analysis",
            "workflows",
            "figure_style.py",
            "excel.py",
        ):
            target = EVAL_ROOT / relative_path
            if target.is_dir():
                self.assertFalse(any(target.rglob("*.py")), relative_path)
            else:
                self.assertFalse(target.exists(), relative_path)

        for module_name in (
            "egoanchor.eval.metrics",
            "egoanchor.eval.paper",
            "egoanchor.eval.analysis",
            "egoanchor.eval.publishing",
            "egoanchor.eval.paper_analysis",
            "egoanchor.eval.workflows",
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

        experiments_root = EVAL_ROOT / "experiments"
        for experiment in ("experiment_1_2", "experiment_3"):
            for module in ("data.py", "pipeline.py", "settings.py", "workflow.py"):
                self.assertTrue(
                    (experiments_root / experiment / module).is_file(),
                    f"{experiment}/{module}",
                )
            analysis_root = experiments_root / experiment / "analysis"
            self.assertTrue((analysis_root / "__init__.py").is_file())
            self.assertTrue(any(analysis_root.glob("*.py")))
        analysis_leaves = {
            "experiment_1_2": {
                "cache.py",
                "figures.py",
                "metrics.py",
                "paper.py",
                "xlsx.py",
            },
            "experiment_3": {
                "clmm.py",
                "contracts.py",
                "figures.py",
                "inference.py",
                "paper.py",
                "reader.py",
                "scoring.py",
                "summaries.py",
                "workbook.py",
            },
        }
        for experiment, leaves in analysis_leaves.items():
            root = experiments_root / experiment
            for leaf in leaves:
                self.assertFalse((root / leaf).exists(), f"{experiment}/{leaf}")
                self.assertTrue((root / "analysis" / leaf).is_file(), f"{experiment}/analysis/{leaf}")
        self.assertTrue((experiments_root / "workspace.py").is_file())

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
        self.assertIn("当前五任务活动批次", output.getvalue())

    def test_stage_rejects_removed_directory_arguments(self) -> None:
        """stage 不再接受五个长目录名，防止旧入口继续被误用。"""

        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                eval_cli.build_parser().parse_args(["stage", "task_1_directory"])

        self.assertEqual(raised.exception.code, 2)

    def test_all_removed_top_level_commands_are_rejected(self) -> None:
        """旧命令不保留别名或隐藏转发，避免新旧手册长期并存。"""

        for command in (
            "config",
            "sessions",
            "stage",
            "promote",
            "qc",
            "preprocess",
            "rebuild",
            "publish",
            "experiment3",
        ):
            with self.subTest(command=command), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    eval_cli.build_parser().parse_args([command])
                self.assertEqual(raised.exception.code, 2)

    def test_status_defaults_to_the_complete_workspace(self) -> None:
        """status 无目标时稳定显示 all，其他生命周期必须显式指定目标。"""

        arguments = eval_cli.build_parser().parse_args(["status"])

        self.assertEqual(arguments.target, "all")
        self.assertIs(arguments.handler, eval_cli._run_status)

    def test_copy_assets_without_target_keeps_the_established_exp12_default(self) -> None:
        """无目标 copy-assets 仍可直接复制实验一/二，实验三通过显式目标加入。"""

        arguments = eval_cli.build_parser().parse_args(["copy-assets"])

        self.assertEqual(arguments.target, "exp1-2")
        self.assertIs(arguments.handler, eval_cli._run_copy_assets)

    def test_formal_experiment3_analysis_rejects_path_and_synthetic_overrides(self) -> None:
        """正式 CLI 只读 TOML 固定路径，不暴露模拟数据后门。"""

        for option in ("--input", "--output-root", "--allow-synthetic"):
            with self.subTest(option=option), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    eval_cli.build_parser().parse_args(["analyze", "exp3", option, "value"])
                self.assertEqual(raised.exception.code, 2)

    def test_analyze_all_uses_explicit_experiment12_rebuild_flag(self) -> None:
        """联合重建参数明确归属实验一/二，不把 rebuild 伪装成共享统计动作。"""

        arguments = eval_cli.build_parser().parse_args(
            ["analyze", "all", "--rebuild-exp1-2"]
        )

        self.assertTrue(arguments.rebuild_exp1_2)
        self.assertEqual(arguments.target, "all")

    def test_stage_accepts_short_version_selectors(self) -> None:
        """stage 接受统一版本、逐任务版本和对象筛选。"""

        args = eval_cli.build_parser().parse_args(
            [
                "data",
                "exp1-2",
                "stage",
                "--version",
                "v2",
                "--task-version",
                "3=v4",
                "--object",
                "cube",
            ]
        )

        self.assertEqual(args.version, 2)
        self.assertEqual(args.task_version, ["3=v4"])
        self.assertEqual(args.object_name, "cube")

    def test_failed_qc_payload_returns_exit_code_two(self) -> None:
        """QC 完整报告为失败时，CLI 必须保留 JSON 并返回退出码二。"""

        output = io.StringIO()
        with mock.patch.object(
            eval_cli,
            "validate_workspace",
            return_value={"passed": False, "tasks": []},
        ):
            with contextlib.redirect_stdout(output):
                result = eval_cli.main(["validate", "exp1-2"])

        self.assertEqual(result, eval_cli.EXIT_DATA_ERROR)
        self.assertIn('"passed": false', output.getvalue())


if __name__ == "__main__":
    unittest.main()

"""schema-v2 顶层 CLI 的命令、返回码和论文发布路由测试。"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import egoanchor.eval.cli as eval_cli
from egoanchor.eval import SchemaQcReport
from egoanchor.eval.paper import FIGURE_FILES, LATEX_FILES


class EvalCliTest(unittest.TestCase):
    """验证 CLI 只暴露冻结命令并正确发布分析产物。"""

    def test_qc_prints_pure_json_and_returns_zero_or_two(self) -> None:
        """QC stdout 必须可直接解析，返回码只由 report.passed 决定。"""

        session = SimpleNamespace(session_id="synthetic-session")
        for passed, expected_code in ((True, eval_cli.EXIT_OK), (False, eval_cli.EXIT_DATA_ERROR)):
            report = SchemaQcReport(
                errors=[] if passed else ["synthetic failure"],
                warnings=["synthetic warning"],
                metrics={"variant_count": 8},
            )
            stdout = io.StringIO()
            with (
                patch.object(eval_cli, "load_session_v2", return_value=session),
                patch.object(eval_cli, "run_schema_qc", return_value=report),
                redirect_stdout(stdout),
            ):
                code = eval_cli.main(["qc", "synthetic-session"])

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, expected_code)
            self.assertEqual(payload["session_id"], "synthetic-session")
            self.assertEqual(payload["passed"], passed)

    def test_analysis_commands_load_sessions_and_publish_fixed_outputs(self) -> None:
        """两个分析命令均先加载 session，再发布 TeX/PDF 到论文固定目录。"""

        for command, experiment, runner_name in (
            ("analyze-exp1", "exp1", "run_exp1_system_characterization"),
            ("analyze-exp2", "exp2", "run_exp2_design_attribution"),
        ):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                session_dir = root / "session"
                session_dir.mkdir()
                output = root / "analysis"
                paper_root = root / "paper"
                session = SimpleNamespace(session_id=f"{experiment}-session")
                old_latex = paper_root / "generated" / LATEX_FILES[experiment][0]
                old_figure = (
                    paper_root
                    / "figures"
                    / "generated"
                    / FIGURE_FILES[experiment][0]
                )
                old_latex.parent.mkdir(parents=True)
                old_figure.parent.mkdir(parents=True)
                old_latex.write_text("old latex", encoding="utf-8")
                old_figure.write_text("old figure", encoding="utf-8")

                def fake_analysis(sessions, output_dir, config):
                    """模拟已由实验包覆盖的分析，并写论文发布契约要求的源文件。"""

                    self.assertEqual(sessions, [session])
                    self.assertIsNone(config)
                    destination = Path(output_dir)
                    destination.mkdir(parents=True, exist_ok=True)
                    (destination / f"{experiment}_session_qc.csv").write_text(
                        "passed\ntrue\n", encoding="utf-8"
                    )
                    for filename in (*LATEX_FILES[experiment], *FIGURE_FILES[experiment]):
                        (destination / filename).write_text(filename, encoding="utf-8")
                    return SimpleNamespace(output_dir=destination)

                with (
                    patch.object(eval_cli, "load_session_v2", return_value=session) as loader,
                    patch.object(eval_cli, runner_name, side_effect=fake_analysis),
                ):
                    code = eval_cli.main(
                        [
                            command,
                            str(session_dir),
                            "--out",
                            str(output),
                            "--paper-root",
                            str(paper_root),
                        ]
                    )

                self.assertEqual(code, eval_cli.EXIT_OK)
                loader.assert_called_once_with(session_dir)
                self.assertTrue((output / f"{experiment}_session_qc.csv").is_file())
                for filename in LATEX_FILES[experiment]:
                    self.assertTrue((paper_root / "generated" / filename).is_file())
                for filename in FIGURE_FILES[experiment]:
                    self.assertTrue(
                        (paper_root / "figures" / "generated" / filename).is_file()
                    )
                self.assertEqual(old_latex.read_text(encoding="utf-8"), LATEX_FILES[experiment][0])
                self.assertEqual(old_figure.read_text(encoding="utf-8"), FIGURE_FILES[experiment][0])

    def test_default_paper_root_resolution_is_deferred_to_publisher(self) -> None:
        """未传覆盖路径时 CLI 传 None，由 paper 包在发布阶段解析仓库。"""

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "analysis"
            session = SimpleNamespace(session_id="exp1-session")
            original_cwd = Path.cwd()
            try:
                os.chdir(root)
                with (
                    patch.object(eval_cli, "load_session_v2", return_value=session),
                    patch.object(eval_cli, "run_exp1_system_characterization"),
                    patch.object(eval_cli, "publish_analysis_outputs") as publish,
                ):
                    code = eval_cli.main(
                        ["analyze-exp1", "synthetic-session", "--out", str(output)]
                    )
            finally:
                os.chdir(original_cwd)

            self.assertEqual(code, eval_cli.EXIT_OK)
            publish.assert_called_once_with("exp1", output, None)

    def test_analysis_contract_failure_returns_two_and_does_not_publish(self) -> None:
        """分析 QC/契约失败必须返回 2，且不能发布旧或半成品结果。"""

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with (
                patch.object(eval_cli, "load_session_v2", return_value=SimpleNamespace()),
                patch.object(
                    eval_cli,
                    "run_exp2_design_attribution",
                    side_effect=ValueError("synthetic QC failure"),
                ),
                patch.object(eval_cli, "publish_analysis_outputs") as publish,
                redirect_stderr(io.StringIO()),
            ):
                code = eval_cli.main(
                    [
                        "analyze-exp2",
                        "synthetic-session",
                        "--out",
                        str(root / "analysis"),
                        "--paper-root",
                        str(root / "paper"),
                    ]
                )

            self.assertEqual(code, eval_cli.EXIT_DATA_ERROR)
            publish.assert_not_called()

    def test_filesystem_failure_returns_one(self) -> None:
        """session 或发布文件系统失败与数据 QC 失败使用不同返回码。"""

        with (
            patch.object(eval_cli, "load_session_v2", side_effect=OSError("synthetic IO")),
            redirect_stderr(io.StringIO()),
        ):
            code = eval_cli.main(["qc", "missing-session"])
        self.assertEqual(code, eval_cli.EXIT_IO_ERROR)

    def test_old_paper_outputs_do_not_hide_missing_analysis_sources(self) -> None:
        """旧目标文件存在时，缺失的新分析源仍必须返回文件系统失败。"""

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "analysis"
            paper_root = root / "paper"
            output.mkdir()
            for filename in LATEX_FILES["exp1"]:
                path = paper_root / "generated" / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("old", encoding="utf-8")
            for filename in FIGURE_FILES["exp1"]:
                path = paper_root / "figures" / "generated" / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("old", encoding="utf-8")

            with (
                patch.object(eval_cli, "load_session_v2", return_value=SimpleNamespace()),
                patch.object(eval_cli, "run_exp1_system_characterization"),
                redirect_stderr(io.StringIO()),
            ):
                code = eval_cli.main(
                    [
                        "analyze-exp1",
                        "synthetic-session",
                        "--out",
                        str(output),
                        "--paper-root",
                        str(paper_root),
                    ]
                )

            self.assertEqual(code, eval_cli.EXIT_IO_ERROR)
            self.assertEqual(
                (paper_root / "generated" / LATEX_FILES["exp1"][0]).read_text(
                    encoding="utf-8"
                ),
                "old",
            )

    def test_legacy_commands_are_not_registered(self) -> None:
        """旧 run_eval/batch_eval 名称必须由 argparse 直接拒绝。"""

        for command in ("run_eval", "batch_eval"):
            with self.subTest(command=command), self.assertRaises(SystemExit) as raised:
                with redirect_stderr(io.StringIO()):
                    eval_cli.main([command])
            self.assertEqual(raised.exception.code, eval_cli.EXIT_DATA_ERROR)


if __name__ == "__main__":
    unittest.main()

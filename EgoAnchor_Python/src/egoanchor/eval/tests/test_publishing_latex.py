"""Task 11 paper CSV 到四个 TeX 中间产物的契约测试。"""

from __future__ import annotations

import csv
import contextlib
import io
import os
import re
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from egoanchor.eval import CSV_TABLE_CONTRACTS, publish_artifacts, publish_latex
from egoanchor.eval import cli as eval_cli

from .test_publishing_figures import _write_fixture as _write_plot_fixture


def _contract(name: str):
    """按逻辑表名读取冻结 CSV 契约。"""

    return next(item for item in CSV_TABLE_CONTRACTS if item.name == name)


def _write_csv(path: Path, table_name: str, rows: list[dict[str, object]]) -> None:
    """按冻结列顺序写入 Task 11 测试 CSV。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    columns = _contract(table_name).column_names()
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in columns} for row in rows)


def _write_fixture(root: Path, *, invalid_macro: bool = False) -> None:
    """写入同时覆盖实验一/二的最小 paper CSV fixture。"""

    upstream_hash = "a" * 64
    _write_csv(
        root / "paper" / "numbers.csv",
        "numbers",
        [
            {
                "experiment": "exp1_system_characterization",
                "macro_name": "SessionCount" if not invalid_macro else "SessionCount2",
                "value": "5",
                "source_csv": "exp1/scenario_summary.csv",
                "source_sha256": upstream_hash,
            },
            {
                "experiment": "exp2_design_attribution",
                "macro_name": "VcdMeanRiskAurcMm",
                "value": "2.3843",
                "source_csv": "exp2/vcd_aurc.csv",
                "source_sha256": upstream_hash,
            },
        ],
    )
    _write_csv(
        root / "paper" / "tables.csv",
        "tables",
        [
            *(
                {
                    "experiment": "exp1_system_characterization",
                    "table_name": "exp1_scenario_summary",
                    "row_key": row_key,
                    "column_key": column,
                    "display_value": value,
                    "source_csv": "exp1/scenario_summary.csv",
                    "source_sha256": upstream_hash,
                }
                for row_key, values in {
                    "Arrival-Hold": ("33.6 [30.0, 35.0] mm", "7.2 [6.0, 8.0] mm", "110 [90, 130] ms", "9.1 [8.0, 10.0] mm", "4.1 [3.5, 5.0] deg", "12.2 [10.0, 15.0] mm"),
                    "Capture-Hold": ("12.0 [10.0, 13.0] mm", "5.0 [4.0, 6.0] mm", "100 [80, 120] ms", "7.5 [6.0, 9.0] mm", "3.8 [3.0, 4.5] deg", "10.0 [8.0, 12.0] mm"),
                    "One-Euro Anchor": ("10.0 [9.0, 11.0] mm", "4.0 [3.0, 5.0] mm", "90 [70, 110] ms", "6.4 [5.0, 8.0] mm", "3.2 [2.5, 4.0] deg", "8.0 [6.0, 10.0] mm"),
                    "EgoAnchor": ("[BEST]4.0 [3.0, 5.0] mm", "[BEST]3.0 [2.0, 4.0] mm", "[BEST]80 [60, 100] ms", "[BEST]5.0 [4.0, 6.0] mm", "[BEST]2.8 [2.0, 3.5] deg", "[BEST]6.0 [4.0, 8.0] mm"),
                }.items()
                for column, value in zip(
                    ("World P95 ↓", "HP--RMS ↓", "Response ↓", "Trans. residual ↓", "Rot. residual ↓", "Occlusion P95 ↓"),
                    values,
                )
            ),
            *(
                {
                    "experiment": "exp2_design_attribution",
                    "table_name": "exp2_mechanism_attribution",
                    "row_key": "VCD admission / occlusion",
                    "column_key": column,
                    "display_value": value,
                    "source_csv": "exp2/paired_summary.csv",
                    "source_sha256": upstream_hash,
                }
                for column, value in (
                    ("主指标", "Occlusion P95"),
                    ("Full median [IQR]", "1.0 [0.8, 1.2] mm"),
                    ("Ablated median [IQR]", "2.25 [1.3, 3.2] mm"),
                    ("Delta [IQR]（+/0/-）", "1.25 [0.5, 2.0] mm; 3/0/1"),
                    ("护栏 Delta [IQR]", "Recovery: 0 [0, 0] ms"),
                )
            ),
        ],
    )


class LatexPublishingTests(unittest.TestCase):
    """验证 TeX 发布的输入边界、宏命名、转义和 lineage。"""

    def test_publish_creates_four_tex_files_with_exact_csv_values(self) -> None:
        """四个固定文件必须包含 CSV 数值、表格和输入 hash。"""

        with tempfile.TemporaryDirectory() as tmp:
            csv_root = Path(tmp) / "csv"
            output = Path(tmp) / "generated"
            _write_fixture(csv_root)
            result = publish_latex(csv_root, output)
            self.assertEqual(
                set(result.tex_sha256),
                {"exp1_numbers.tex", "exp1_tables.tex", "exp2_numbers.tex", "exp2_tables.tex"},
            )
            exp1_numbers = (output / "exp1_numbers.tex").read_text(encoding="utf-8")
            exp1_table = (output / "exp1_tables.tex").read_text(encoding="utf-8")
            self.assertIn(r"\newcommand{\EAExpOneSessionCount}{5}", exp1_numbers)
            self.assertIn(result.input_csv_sha256["paper/numbers.csv"], exp1_numbers)
            exp2_table = (output / "exp2_tables.tex").read_text(encoding="utf-8")
            self.assertIn(r"Delta [IQR]（+/0/-）", exp2_table)
            self.assertIn("1.25 [0.5, 2.0] mm", exp2_table)
            self.assertIn(r"\textbf{4.0 [3.0, 5.0] mm}", exp1_table)
            self.assertIn(r"\begin{tabularx}{\textwidth}", exp2_table)
            self.assertIn(r"\scriptsize", exp2_table)
            self.assertIn("机制 / 场景", exp2_table)

    def test_generated_control_sequences_contain_no_digits(self) -> None:
        """所有自动生成控制序列必须只含 ASCII 字母。"""

        with tempfile.TemporaryDirectory() as tmp:
            csv_root = Path(tmp) / "csv"
            output = Path(tmp) / "generated"
            _write_fixture(csv_root)
            publish_latex(csv_root, output)
            text = "\n".join(path.read_text(encoding="utf-8") for path in output.glob("*.tex"))
            self.assertIsNone(re.search(r"\\[A-Za-z]*[0-9]", text))

    def test_invalid_macro_fails_without_output(self) -> None:
        """CSV 宏后缀含数字时返回契约错误且不发布半套 TeX。"""

        with tempfile.TemporaryDirectory() as tmp:
            csv_root = Path(tmp) / "csv"
            output = Path(tmp) / "generated"
            _write_fixture(csv_root, invalid_macro=True)
            with self.assertRaisesRegex(ValueError, "宏名"):
                publish_latex(csv_root, output)
            self.assertFalse(output.exists())

    def test_missing_paper_csv_fails_without_output(self) -> None:
        """缺 numbers 或 tables 时必须作为缺源失败且不发布。"""

        with tempfile.TemporaryDirectory() as tmp:
            csv_root = Path(tmp) / "csv"
            output = Path(tmp) / "generated"
            _write_fixture(csv_root)
            (csv_root / "paper" / "tables.csv").unlink()
            with self.assertRaises(FileNotFoundError):
                publish_latex(csv_root, output)
            self.assertFalse(output.exists())

    def test_cli_publish_creates_figures_and_tex(self) -> None:
        """统一 publish 命令必须同时发布两张当前组合图和四个 TeX。"""

        with tempfile.TemporaryDirectory() as tmp:
            csv_root = Path(tmp) / "csv"
            figure_output = Path(tmp) / "figures"
            tex_output = Path(tmp) / "generated"
            _write_plot_fixture(csv_root)
            _write_fixture(csv_root)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = eval_cli.main(
                    [
                        "publish",
                        str(csv_root),
                        "--out",
                        str(figure_output),
                        "--tex-out",
                        str(tex_output),
                    ]
                )
            self.assertEqual(code, eval_cli.EXIT_OK)
            self.assertEqual(len(list(figure_output.glob("*.pdf"))), 2)
            self.assertEqual(len(list(tex_output.glob("*.tex"))), 4)

    def test_joint_publish_failure_preserves_both_old_directories(self) -> None:
        """TeX 构建失败时新图也不得替换既有 Stage 3 产物。"""

        with tempfile.TemporaryDirectory() as tmp:
            csv_root = Path(tmp) / "csv"
            figure_output = Path(tmp) / "figures"
            tex_output = Path(tmp) / "generated"
            _write_plot_fixture(csv_root)
            _write_fixture(csv_root)
            publish_artifacts(csv_root, figure_output, tex_output)
            old_figure = (figure_output / "figure_manifest.json").read_bytes()
            old_tex = (tex_output / "exp1_numbers.tex").read_bytes()
            _write_fixture(csv_root, invalid_macro=True)
            with self.assertRaisesRegex(ValueError, "宏名"):
                publish_artifacts(csv_root, figure_output, tex_output)
            self.assertEqual((figure_output / "figure_manifest.json").read_bytes(), old_figure)
            self.assertEqual((tex_output / "exp1_numbers.tex").read_bytes(), old_tex)

    def test_output_directories_must_not_overlap(self) -> None:
        """图与 TeX 同目录或输出作为 CSV 祖先时必须在构建前拒绝。"""

        with tempfile.TemporaryDirectory() as tmp:
            csv_root = Path(tmp) / "csv"
            output = Path(tmp) / "artifacts"
            _write_plot_fixture(csv_root)
            _write_fixture(csv_root)
            with self.assertRaisesRegex(ValueError, "不得相同或互相嵌套"):
                publish_artifacts(csv_root, output, output)
            self.assertFalse(output.exists())
            with self.assertRaisesRegex(ValueError, "重叠"):
                publish_latex(csv_root, Path(tmp))
            self.assertTrue((csv_root / "paper" / "numbers.csv").is_file())

    def test_second_directory_commit_failure_rolls_back_both(self) -> None:
        """第二目录提交失败时必须恢复两侧旧产物并清理事务目录。"""

        with tempfile.TemporaryDirectory() as tmp:
            csv_root = Path(tmp) / "csv"
            figure_output = Path(tmp) / "figures"
            tex_output = Path(tmp) / "generated"
            _write_plot_fixture(csv_root)
            _write_fixture(csv_root)
            publish_artifacts(csv_root, figure_output, tex_output)
            old_figure = (figure_output / "figure_manifest.json").read_bytes()
            old_tex = (tex_output / "exp1_numbers.tex").read_bytes()
            real_replace = os.replace
            calls = 0

            def fail_second_commit(source, destination):
                """仅在备份两侧并提交第一目录后注入一次失败。"""

                nonlocal calls
                calls += 1
                if calls == 4:
                    raise OSError("injected second commit failure")
                return real_replace(source, destination)

            with mock.patch(
                "egoanchor.eval.publishing._atomic.os.replace",
                side_effect=fail_second_commit,
            ):
                with self.assertRaisesRegex(OSError, "injected"):
                    publish_artifacts(csv_root, figure_output, tex_output)
            self.assertEqual((figure_output / "figure_manifest.json").read_bytes(), old_figure)
            self.assertEqual((tex_output / "exp1_numbers.tex").read_bytes(), old_tex)
            residual = [
                path.name
                for path in Path(tmp).iterdir()
                if "-stage-" in path.name or "-backup-" in path.name
            ]
            self.assertEqual(residual, [])

    def test_atomic_publish_directories_do_not_use_restrictive_mkdtemp_acl(self) -> None:
        """图表和 TeX 正式目录必须从父目录继承 ACL。"""

        with tempfile.TemporaryDirectory() as tmp:
            csv_root = Path(tmp) / "csv"
            figure_output = Path(tmp) / "figures"
            tex_output = Path(tmp) / "generated"
            _write_plot_fixture(csv_root)
            _write_fixture(csv_root)
            with mock.patch(
                "tempfile.mkdtemp",
                side_effect=AssertionError("mkdtemp must not create publish directories"),
            ):
                publish_artifacts(csv_root, figure_output, tex_output)
            self.assertTrue((figure_output / "figure_manifest.json").is_file())
            self.assertTrue((tex_output / "exp1_numbers.tex").is_file())


if __name__ == "__main__":
    unittest.main()

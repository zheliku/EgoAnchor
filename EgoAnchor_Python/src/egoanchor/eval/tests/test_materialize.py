"""Task 12 Stage 4 TeX-only 主稿物化测试。"""

from __future__ import annotations

import contextlib
import hashlib
import io
import re
import tempfile
import unittest
from pathlib import Path

from egoanchor.eval import materialize_paper
from egoanchor.eval import cli as eval_cli


_MARKERS = (
    ("% EGOANCHOR-EXP-DATA:BEGIN", "% EGOANCHOR-EXP-DATA:END"),
    ("% EGOANCHOR-EXP-ONE-TABLE:BEGIN", "% EGOANCHOR-EXP-ONE-TABLE:END"),
    ("% EGOANCHOR-EXP-TWO-TABLE:BEGIN", "% EGOANCHOR-EXP-TWO-TABLE:END"),
)


def _write_sources(root: Path) -> None:
    """写入四个带 Stage 2 CSV lineage 的最小 TeX。"""

    root.mkdir(parents=True, exist_ok=True)
    generator = "; generator: egoanchor.eval.publishing.latex-v1\n"
    numbers_header = "% Source: paper/numbers.csv; SHA-256: " + "a" * 64 + generator
    tables_header = "% Source: paper/tables.csv; SHA-256: " + "b" * 64 + generator
    (root / "exp1_numbers.tex").write_text(
        numbers_header + r"\newcommand{\EAExpOneSessionCount}{5}" + "\n",
        encoding="utf-8",
    )
    (root / "exp2_numbers.tex").write_text(
        numbers_header + r"\newcommand{\EAExpTwoSessionCount}{3}" + "\n",
        encoding="utf-8",
    )
    (root / "exp1_tables.tex").write_text(
        tables_header
        + "% Table: exp1\\_scenario\\_summary\n"
        + "\\begin{tabular}{ll}\nA & B \\\\\n\\end{tabular}\n",
        encoding="utf-8",
    )
    (root / "exp2_tables.tex").write_text(
        tables_header
        + "% Table: exp2\\_component\\_deltas\n"
        + "\\begin{tabular}{ll}\nC & D \\\\\n\\end{tabular}\n",
        encoding="utf-8",
    )


def _manuscript() -> str:
    """返回含三个稳定受控区块的最小主稿。"""

    return """PREAMBLE
% EGOANCHOR-EXP-DATA:BEGIN
old macros
% EGOANCHOR-EXP-DATA:END
BODY ONE
% EGOANCHOR-EXP-ONE-TABLE:BEGIN
old table one
% EGOANCHOR-EXP-ONE-TABLE:END
BODY TWO
% EGOANCHOR-EXP-TWO-TABLE:BEGIN
old table two
% EGOANCHOR-EXP-TWO-TABLE:END
TAIL
"""


def _outside_blocks(text: str) -> str:
    """移除三个区块内部内容，用于比较人工正文。"""

    result = text
    for begin, end in _MARKERS:
        result = re.sub(
            re.escape(begin) + r".*?" + re.escape(end),
            begin + "\n" + end,
            result,
            flags=re.DOTALL,
        )
    return result


class MaterializeTests(unittest.TestCase):
    """验证 Stage 4 输入边界、幂等性、lineage 和失败原子性。"""

    def test_materializes_three_blocks_and_preserves_manual_text(self) -> None:
        """宏与两表分别进入三个区块，区块外正文必须逐字不变。"""

        with tempfile.TemporaryDirectory() as tmp:
            tex_root = Path(tmp) / "generated"
            manuscript = Path(tmp) / "paper.tex"
            _write_sources(tex_root)
            before = _manuscript()
            manuscript.write_text(before, encoding="utf-8")
            result = materialize_paper(tex_root, manuscript)
            after = manuscript.read_text(encoding="utf-8")
            self.assertEqual(_outside_blocks(before), _outside_blocks(after))
            self.assertIn(r"\newcommand{\EAExpOneSessionCount}{5}", after)
            self.assertIn(r"\begin{tabular}{ll}", after)
            self.assertEqual(result.block_count, 3)
            self.assertEqual(len(result.source_tex_sha256), 4)
            for digest in result.source_tex_sha256.values():
                self.assertIn(digest, after)
            first_data_line = after.split(_MARKERS[0][0], 1)[1].lstrip("\r\n").splitlines()[0]
            self.assertTrue(first_data_line.startswith("% Source CSV SHA-256:"))

    def test_repeated_materialization_has_zero_diff(self) -> None:
        """相同四个 TeX 重复物化必须得到相同主稿 hash 和字节。"""

        with tempfile.TemporaryDirectory() as tmp:
            tex_root = Path(tmp) / "generated"
            manuscript = Path(tmp) / "paper.tex"
            _write_sources(tex_root)
            manuscript.write_text(_manuscript(), encoding="utf-8")
            first = materialize_paper(tex_root, manuscript)
            first_bytes = manuscript.read_bytes()
            second = materialize_paper(tex_root, manuscript)
            self.assertEqual(manuscript.read_bytes(), first_bytes)
            self.assertEqual(second.manuscript_sha256, first.manuscript_sha256)
            self.assertEqual(
                second.manuscript_sha256,
                hashlib.sha256(first_bytes).hexdigest(),
            )

    def test_missing_marker_or_old_include_preserves_manuscript(self) -> None:
        """缺区块或残留 generated include 时必须失败且不修改文件。"""

        with tempfile.TemporaryDirectory() as tmp:
            tex_root = Path(tmp) / "generated"
            manuscript = Path(tmp) / "paper.tex"
            _write_sources(tex_root)
            missing = _manuscript().replace("% EGOANCHOR-EXP-TWO-TABLE:END", "")
            manuscript.write_text(missing, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "区块标记"):
                materialize_paper(tex_root, manuscript)
            self.assertEqual(manuscript.read_text(encoding="utf-8"), missing)
            legacy = _manuscript() + r"\input{generated/exp1_numbers.tex}" + "\n"
            manuscript.write_text(legacy, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "旧 generated"):
                materialize_paper(tex_root, manuscript)
            self.assertEqual(manuscript.read_text(encoding="utf-8"), legacy)

    def test_missing_tex_source_preserves_manuscript(self) -> None:
        """缺任一固定 TeX 时返回缺源错误且不修改主稿。"""

        with tempfile.TemporaryDirectory() as tmp:
            tex_root = Path(tmp) / "generated"
            manuscript = Path(tmp) / "paper.tex"
            _write_sources(tex_root)
            (tex_root / "exp2_tables.tex").unlink()
            before = _manuscript()
            manuscript.write_text(before, encoding="utf-8")
            with self.assertRaises(FileNotFoundError):
                materialize_paper(tex_root, manuscript)
            self.assertEqual(manuscript.read_text(encoding="utf-8"), before)

    def test_rejects_old_include_path_variants(self) -> None:
        """旧 include 的省略扩展名、相对前缀和反斜杠写法均须拒绝。"""

        variants = (
            r"\input{generated/exp1_numbers}",
            r"\input {./generated/exp2_tables.tex}",
            r"\IfFileExists{generated\exp1_tables.tex}{\input{ignored}}{}",
        )
        with tempfile.TemporaryDirectory() as tmp:
            tex_root = Path(tmp) / "generated"
            manuscript = Path(tmp) / "paper.tex"
            _write_sources(tex_root)
            for legacy in variants:
                before = _manuscript() + legacy + "\n"
                manuscript.write_text(before, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "旧 generated"):
                    materialize_paper(tex_root, manuscript)
                self.assertEqual(manuscript.read_text(encoding="utf-8"), before)

    def test_rejects_wrong_lineage_and_experiment_content(self) -> None:
        """固定 TeX 的 CSV、生成器和实验归属不得错配。"""

        with tempfile.TemporaryDirectory() as tmp:
            tex_root = Path(tmp) / "generated"
            manuscript = Path(tmp) / "paper.tex"
            _write_sources(tex_root)
            before = _manuscript()
            manuscript.write_text(before, encoding="utf-8")
            source = tex_root / "exp1_numbers.tex"
            valid = source.read_text(encoding="utf-8")
            for invalid in (
                valid.replace("paper/numbers.csv", "paper/tables.csv"),
                valid.replace("egoanchor.eval.publishing.latex-v1", "third-party"),
                valid.replace("EAExpOne", "EAExpTwoWrong"),
            ):
                source.write_text(invalid, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "lineage|实验归属"):
                    materialize_paper(tex_root, manuscript)
                self.assertEqual(manuscript.read_text(encoding="utf-8"), before)
            source.write_text(valid, encoding="utf-8")
            table = tex_root / "exp2_tables.tex"
            table.write_text(
                table.read_text(encoding="utf-8").replace(
                    "exp2\\_component\\_deltas",
                    "exp1\\_scenario\\_summary",
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "实验归属"):
                materialize_paper(tex_root, manuscript)

    def test_preserves_crlf_outside_controlled_blocks(self) -> None:
        """Windows CRLF 主稿的区块外字节必须保持不变。"""

        with tempfile.TemporaryDirectory() as tmp:
            tex_root = Path(tmp) / "generated"
            manuscript = Path(tmp) / "paper.tex"
            _write_sources(tex_root)
            before = _manuscript().replace("\n", "\r\n").encode("utf-8")
            manuscript.write_bytes(before)
            materialize_paper(tex_root, manuscript)
            after = manuscript.read_bytes()
            for manual_fragment in (b"PREAMBLE\r\n", b"BODY ONE\r\n", b"BODY TWO\r\n", b"TAIL\r\n"):
                self.assertIn(manual_fragment, after)

    def test_rejects_manuscript_inside_tex_input_tree(self) -> None:
        """Stage 4 输出不得写入 Stage 3 TeX 输入目录。"""

        with tempfile.TemporaryDirectory() as tmp:
            tex_root = Path(tmp) / "generated"
            _write_sources(tex_root)
            manuscript = tex_root / "paper.tex"
            before = _manuscript()
            manuscript.write_text(before, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "输入目录"):
                materialize_paper(tex_root, manuscript)
            self.assertEqual(manuscript.read_text(encoding="utf-8"), before)

    def test_cli_materializes_default_paper_paths(self) -> None:
        """materialize-paper 不接收 CSV 根目录并使用论文默认路径。"""

        with tempfile.TemporaryDirectory() as tmp:
            paper_root = Path(tmp) / "paper"
            _write_sources(paper_root / "generated")
            manuscript = paper_root / "egoanchor_cn_v6.tex"
            manuscript.write_text(_manuscript(), encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = eval_cli.main(
                    ["materialize-paper", "--paper-root", str(paper_root)]
                )
            self.assertEqual(code, eval_cli.EXIT_OK)
            self.assertIn(r"\EAExpTwoSessionCount", manuscript.read_text(encoding="utf-8"))

    def test_cli_maps_missing_source_and_invalid_contract_exit_codes(self) -> None:
        """缺源返回 1，TeX 或主稿契约失败返回 2。"""

        with tempfile.TemporaryDirectory() as tmp:
            paper_root = Path(tmp) / "paper"
            manuscript = paper_root / "egoanchor_cn_v6.tex"
            paper_root.mkdir(parents=True)
            manuscript.write_text(_manuscript(), encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(
                    eval_cli.main(["materialize-paper", "--paper-root", str(paper_root)]),
                    eval_cli.EXIT_IO_ERROR,
                )
            _write_sources(paper_root / "generated")
            manuscript.write_text(_manuscript().replace(_MARKERS[2][1], ""), encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(
                    eval_cli.main(["materialize-paper", "--paper-root", str(paper_root)]),
                    eval_cli.EXIT_DATA_ERROR,
                )

    def test_active_manuscript_uses_exp1_composite_figure(self) -> None:
        """正式主稿只引用实验一组合图，不再依赖已删除的三张旧图。"""

        repository_root = Path(__file__).resolve().parents[5]
        manuscript = (
            repository_root / "2026-EgoAnchor" / "egoanchor_cn_v6.tex"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "figures/generated/exp1_behavior_overview.pdf",
            manuscript,
        )
        for legacy_name in (
            "exp1_static_timeline.pdf",
            "exp1_motion_events.pdf",
            "exp1_occlusion_events.pdf",
        ):
            self.assertNotIn(legacy_name, manuscript)


if __name__ == "__main__":
    unittest.main()

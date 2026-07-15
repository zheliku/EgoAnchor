"""论文固定产物目录路由测试。"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from egoanchor.eval.paper import (
    FIGURE_FILES,
    LATEX_FILES,
    default_paper_root,
    publish_analysis_outputs,
    publish_latex_outputs,
)


def _write_analysis_outputs(directory: Path, experiment: str) -> None:
    """写入一组带可辨识内容的最小固定分析产物。"""

    directory.mkdir(parents=True, exist_ok=True)
    for filename in LATEX_FILES[experiment]:
        (directory / filename).write_text(f"% {filename}\n", encoding="utf-8")
    for filename in FIGURE_FILES[experiment]:
        (directory / filename).write_bytes(b"%PDF-1.4\n" + filename.encode("ascii"))


class EvalPaperOutputsTest(unittest.TestCase):
    """验证默认根目录、原子复制、缺文件和同源处理。"""

    def test_default_paper_root_does_not_depend_on_working_directory(self) -> None:
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as temp:
            try:
                os.chdir(temp)
                root = default_paper_root()
            finally:
                os.chdir(previous)
        self.assertEqual(root.name, "2026-EgoAnchor")
        self.assertTrue((root.parent / "EgoAnchor_Python").is_dir())

    def test_publish_routes_exp1_and_exp2_to_fixed_directories(self) -> None:
        for experiment in ("exp1", "exp2"):
            with self.subTest(experiment=experiment), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                analysis = root / "analysis"
                paper = root / "paper"
                _write_analysis_outputs(analysis, experiment)

                result = publish_analysis_outputs(experiment, analysis, paper)

                self.assertEqual(result.paper_root, paper.resolve())
                self.assertEqual(
                    [path.name for path in result.latex_files],
                    list(LATEX_FILES[experiment]),
                )
                self.assertEqual(
                    [path.name for path in result.figure_files],
                    list(FIGURE_FILES[experiment]),
                )
                for source_name in (*LATEX_FILES[experiment], *FIGURE_FILES[experiment]):
                    destination = (
                        paper / "generated" / source_name
                        if source_name.endswith(".tex")
                        else paper / "figures" / "generated" / source_name
                    )
                    self.assertTrue(destination.is_file(), source_name)
                    self.assertEqual(destination.read_bytes(), (analysis / source_name).read_bytes())
                self.assertEqual(list(paper.rglob("*.tmp")), [])

    def test_missing_file_fails_before_creating_partial_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            analysis = root / "analysis"
            paper = root / "paper"
            _write_analysis_outputs(analysis, "exp1")
            (analysis / FIGURE_FILES["exp1"][-1]).unlink()

            with self.assertRaisesRegex(FileNotFoundError, FIGURE_FILES["exp1"][-1]):
                publish_analysis_outputs("exp1", analysis, paper)

            self.assertFalse(paper.exists())

    def test_same_source_latex_publish_validates_and_skips_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            analysis = Path(temp)
            _write_analysis_outputs(analysis, "exp1")
            before = {
                name: (analysis / name).read_bytes()
                for name in LATEX_FILES["exp1"]
            }

            outputs = publish_latex_outputs("exp1", analysis, analysis)

            self.assertEqual(outputs, tuple(analysis.resolve() / name for name in LATEX_FILES["exp1"]))
            self.assertEqual(
                {name: (analysis / name).read_bytes() for name in LATEX_FILES["exp1"]},
                before,
            )
            self.assertEqual(list(analysis.glob(".*.tmp")), [])

    def test_unknown_experiment_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "仅允许"):
                publish_analysis_outputs("experiment-one", temp, Path(temp) / "paper")


if __name__ == "__main__":
    unittest.main()

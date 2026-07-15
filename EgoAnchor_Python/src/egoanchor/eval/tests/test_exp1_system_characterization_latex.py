"""实验一 LaTeX 宏与汇总表契约测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from egoanchor.eval.experiments.exp1_system_characterization import (
    VARIANTS,
    write_exp1_latex,
)


class Exp1LatexTest(unittest.TestCase):
    """验证稳定宏集合、单位换算、系统顺序和旧命名清理。"""

    def test_run_exp1_writes_stable_latex_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            metrics = {
                "translation_error_mm_median": 10.0,
                "translation_error_mm_p95": 20.0,
                "rotation_error_deg_median": 1.0,
                "rotation_error_deg_p95": 2.0,
                "display_coverage": 1.0,
                "output_coverage": 0.9,
                "observation_age_p50_ms": 20.0,
                "observation_age_p95_ms": 30.0,
            }
            summary = pd.DataFrame(
                [
                    {
                        "variant_label": variant,
                        "metric_name": metric_name,
                        "trial_count": 5,
                        "median": value,
                        "iqr": 0.0,
                        "p95": value,
                    }
                    for variant in reversed(VARIANTS)
                    for metric_name, value in metrics.items()
                ]
            )
            paths = write_exp1_latex(
                {"exp1_condition_summary": summary},
                root / "out",
            )

            self.assertEqual(
                [path.name for path in paths],
                ["exp1_numbers.tex", "exp1_tables.tex"],
            )
            numbers = paths[0].read_text(encoding="utf-8")
            table = paths[1].read_text(encoding="utf-8")

        expected_prefixes = (
            "EAExpOneArrivalHold",
            "EAExpOneCaptureHold",
            "EAExpOneOneEuroAnchor",
            "EAExpOneEgoAnchor",
        )
        for prefix in expected_prefixes:
            self.assertIn(f"\\providecommand{{\\{prefix}TranslationMedianMm}}{{10}}", numbers)
            self.assertIn(f"\\providecommand{{\\{prefix}DisplayCoveragePct}}{{100}}", numbers)
        self.assertNotIn("RQ", numbers + table)
        self.assertEqual(
            [table.index(variant) for variant in VARIANTS],
            sorted(table.index(variant) for variant in VARIANTS),
        )
        self.assertIn(r"\begin{tabular}{lrrrr}", table)
        self.assertIn(r"\bottomrule", table)


if __name__ == "__main__":
    unittest.main()

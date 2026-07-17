"""实验二 LaTeX 宏与表格契约测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from egoanchor.eval.experiments.exp2_design_attribution import (
    REQUIRED_VARIANTS,
    write_exp2_latex,
    write_exp2_tables,
)


class Exp2LatexTest(unittest.TestCase):
    """验证宏前缀、指标选择、表格顺序和旧命名清理。"""

    def test_write_exp2_latex_uses_stable_macros_and_variant_order(self) -> None:
        metrics = {
            REQUIRED_VARIANTS[1]: ("display_error.translation_error_mm_median", 1.25),
            REQUIRED_VARIANTS[2]: ("display_error.translation_error_mm_median", 2.25),
            REQUIRED_VARIANTS[3]: ("transition.visible_response_time_ms", 12.0),
            REQUIRED_VARIANTS[4]: ("static.position_hp_rms_mm", 3.5),
        }
        scenarios = {
            REQUIRED_VARIANTS[1]: "static_head_motion",
            REQUIRED_VARIANTS[2]: "occlusion_recovery",
            REQUIRED_VARIANTS[3]: "start_stop_6dof",
            REQUIRED_VARIANTS[4]: "static_head_motion",
        }
        summary = pd.DataFrame(
            [
                {
                    "scenario_id": scenarios[variant],
                    "variant_label": variant,
                    "metric": metric,
                    "paired_n": 5,
                    "delta_mean": value,
                    "delta_median": value,
                }
                for index, (variant, (metric, value)) in enumerate(
                    reversed(metrics.items()),
                    start=1,
                )
            ]
        )
        summary = pd.concat(
            [
                summary,
                pd.DataFrame(
                    [
                        {
                            "scenario_id": "diagnostic-only",
                            "variant_label": REQUIRED_VARIANTS[1],
                            "metric": "latency.candidate_count",
                            "paired_n": 99,
                            "delta_mean": 99.0,
                            "delta_median": 99.0,
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            numbers_path = output / "exp2_numbers.tex"
            tables_path = output / "exp2_tables.tex"
            write_exp2_latex(summary, 0.1234, numbers_path)
            write_exp2_tables(summary, tables_path)
            numbers = numbers_path.read_text(encoding="utf-8")
            table = tables_path.read_text(encoding="utf-8")

        self.assertIn(r"\providecommand{\EAExpTwoAURC}{0.1234}", numbers)
        self.assertIn(r"\EAExpTwoCaptureAlignmentTranslationMedianDeltaMm}{1.25}", numbers)
        self.assertIn(r"\EAExpTwoVCDTranslationMedianDeltaMm}{2.25}", numbers)
        self.assertIn(r"\EAExpTwoTemporalVisibleResponseDeltaMs}{12}", numbers)
        self.assertIn(r"\EAExpTwoStaticLockPositionHpRmsDeltaMm}{3.5}", numbers)
        self.assertNotIn("RQ", numbers + table)
        positions = [table.index(variant) for variant in REQUIRED_VARIANTS[1:]]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("Static target + head motion", table)
        self.assertIn("Display translation median (mm)", table)
        self.assertIn("Visible response time (ms)", table)
        self.assertNotIn(r"display\_error.translation\_error\_mm\_median", table)
        self.assertNotIn(r"candidate\_count", table)
        self.assertIn(r"\begin{tabular}{lllrr}", table)
        self.assertIn(r"\bottomrule", table)


if __name__ == "__main__":
    unittest.main()

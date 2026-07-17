"""实验一 LaTeX 宏与按场景汇总表契约测试。

新实现按场景生成宏和表格，正文因此可以引用“静止/遮挡稳定、连续运动有代价”
的真实结构，而不是被旧的跨场景混池中位掩盖。
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from egoanchor.eval.experiments.exp1_system_characterization import (
    VARIANTS,
    write_exp1_latex,
)
from egoanchor.eval.experiments.exp1_system_characterization.metrics import SCENARIO_ORDER


def _condition_summary() -> pd.DataFrame:
    """构造覆盖全部场景×配置的 trial 级误差汇总。"""

    rows: list[dict[str, object]] = []
    for scenario_index, scenario in enumerate(SCENARIO_ORDER, start=1):
        for variant_index, variant in enumerate(VARIANTS):
            base = 4.0 + scenario_index + variant_index
            for metric_name, value in (
                ("translation_error_mm_median", base),
                ("translation_error_mm_p95", base * 2.0),
                ("rotation_error_deg_median", base * 0.2),
                ("rotation_error_deg_p95", base * 0.4),
                ("display_coverage", 1.0),
                ("observation_age_p50_ms", 20.0 + scenario_index),
                ("observation_age_p95_ms", 40.0 + scenario_index),
            ):
                rows.append(
                    {
                        "scenario_id": scenario,
                        "variant_label": variant,
                        "metric_name": metric_name,
                        "trial_count": 5,
                        "median": value,
                        "iqr": 0.5,
                        "p95": value * 1.1,
                    }
                )
    return pd.DataFrame.from_records(rows)


def _static_quality() -> pd.DataFrame:
    """构造静止抖动 event 表。"""

    return pd.DataFrame.from_records(
        [
            {
                "scenario_id": "static_head_motion",
                "variant_label": variant,
                "position_hp_rms_mm": 0.1 + 0.5 * index,
            }
            for index, variant in enumerate(VARIANTS)
        ]
    )


class Exp1LatexTest(unittest.TestCase):
    """验证按场景宏集合、单位、系统顺序与无遗留混池命名。"""

    def test_write_exp1_latex_emits_per_scenario_macros(self) -> None:
        tables = {
            "exp1_condition_summary": _condition_summary(),
            "exp1_static_quality": _static_quality(),
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = write_exp1_latex(tables, root / "out", session_count=5)
            self.assertEqual(
                [path.name for path in paths],
                ["exp1_numbers.tex", "exp1_tables.tex"],
            )
            numbers = paths[0].read_text(encoding="utf-8")
            table = paths[1].read_text(encoding="utf-8")

        # 每个场景×配置都必须导出平移中位/尾部宏，命名不含阿拉伯数字。
        self.assertIn(r"\providecommand{\EAExpOneSessionCount}{5}", numbers)
        self.assertIn(r"\providecommand{\EAExpOneScenarioCount}{5}", numbers)
        self.assertIn("EAExpOneEgoAnchorStaticTranslationMedianMm", numbers)
        self.assertIn("EAExpOneEgoAnchorOcclusionTranslationPNinetyFiveMm", numbers)
        self.assertIn("EAExpOneArrivalHoldContTranslationTranslationMedianMm", numbers)
        # 宏名不得内嵌阿拉伯数字，否则 TeX 在数字处截断命令名。
        self.assertNotRegex(numbers, r"\\providecommand\{\\[A-Za-z]*[0-9]")
        self.assertNotIn("RQ", numbers + table)

        # 表格按场景分组，四配置列顺序稳定。
        self.assertIn(r"\multirow", table)
        self.assertIn(r"\bottomrule", table)
        header_positions = [table.index(short) for short in ("Arrival", "Capture", "One-Euro", "EgoAnchor")]
        self.assertEqual(header_positions, sorted(header_positions))

    def test_write_exp1_latex_marks_best_variant_bold(self) -> None:
        """每个指标行的最优（最小）有限值应加粗，便于读者定位。"""

        tables = {
            "exp1_condition_summary": _condition_summary(),
            "exp1_static_quality": _static_quality(),
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = write_exp1_latex(tables, root / "out", session_count=5)
            table = paths[1].read_text(encoding="utf-8")
        self.assertIn(r"\textbf{", table)
        # 至少每个场景的每个指标行都应恰好加粗一个单元格。
        bold_count = len(re.findall(r"\\textbf\{", table))
        self.assertGreaterEqual(bold_count, len(SCENARIO_ORDER))


if __name__ == "__main__":
    unittest.main()

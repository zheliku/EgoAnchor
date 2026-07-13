"""RQ1 analyze 薄封装测试。"""

from __future__ import annotations

import unittest

import pandas as pd

from egoanchor.eval.research.rq1 import (
    RQ1_CONDITIONS,
    filter_rq1_tables,
)


class FilterRq1TablesTest(unittest.TestCase):
    """RQ1 只保留 static_observation / occlusion_recovery 场景行。"""

    def test_keeps_only_rq1_conditions(self) -> None:
        """过滤掉非 RQ1 场景（如 translation）。"""

        tables = {
            "anchor_error_summary": pd.DataFrame(
                {
                    "condition": ["static_observation", "translation", "occlusion_recovery"],
                    "label": ["Full", "Full", "Full"],
                    "translation_median_m": [0.006, 0.03, 0.004],
                }
            ),
            "jitter_summary": pd.DataFrame(
                {"condition": ["static_observation", "rotation"], "label": ["Full", "Full"], "position_jitter_rms_m": [0.0004, 0.01]}
            ),
        }

        filtered = filter_rq1_tables(tables)

        self.assertEqual(set(filtered["anchor_error_summary"]["condition"]), set(RQ1_CONDITIONS) & {"static_observation", "occlusion_recovery"})
        self.assertNotIn("translation", set(filtered["anchor_error_summary"]["condition"]))
        self.assertNotIn("rotation", set(filtered["jitter_summary"]["condition"]))

    def test_table_without_condition_column_passes_through(self) -> None:
        """没有 condition 列的表原样保留。"""

        tables = {"misc": pd.DataFrame({"x": [1, 2]})}
        filtered = filter_rq1_tables(tables)
        self.assertEqual(len(filtered["misc"]), 2)


if __name__ == "__main__":
    unittest.main()

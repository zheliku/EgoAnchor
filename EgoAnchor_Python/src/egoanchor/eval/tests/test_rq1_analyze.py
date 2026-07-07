"""RQ1 analyze 薄封装测试。"""

from __future__ import annotations

import unittest

import pandas as pd

from egoanchor.eval.research.rq1.analyze import (
    RQ1_CONDITIONS,
    filter_rq1_tables,
    synthesize_occlusion_markers,
)


class SynthesizeOcclusionMarkersTest(unittest.TestCase):
    """从 rq1_metric 段起点合成遮挡事件 marker。"""

    def test_one_marker_per_contiguous_occlusion_run(self) -> None:
        """每个连续 occlusion_recovery 段生成一个 marker，mono_ms 取段首。"""

        output = pd.DataFrame(
            {
                "render_mono_ms": [0.0, 10.0, 20.0, 30.0, 40.0, 50.0],
                "rq1_metric": [
                    "static_observation",
                    "occlusion_recovery",
                    "occlusion_recovery",
                    "none",
                    "occlusion_recovery",
                    "occlusion_recovery",
                ],
            }
        )

        markers = synthesize_occlusion_markers(output)

        self.assertEqual(len(markers), 2)
        self.assertEqual(markers[0]["type"], "occlusion_recovery")
        self.assertAlmostEqual(markers[0]["mono_ms"], 10.0)
        self.assertAlmostEqual(markers[1]["mono_ms"], 40.0)

    def test_no_occlusion_returns_empty(self) -> None:
        """无遮挡段时返回空列表。"""

        output = pd.DataFrame(
            {"render_mono_ms": [0.0, 10.0], "rq1_metric": ["static_observation", "none"]}
        )
        self.assertEqual(synthesize_occlusion_markers(output), [])

    def test_missing_column_returns_empty(self) -> None:
        """缺少 rq1_metric 列时返回空列表，不抛异常。"""

        output = pd.DataFrame({"render_mono_ms": [0.0, 10.0]})
        self.assertEqual(synthesize_occlusion_markers(output), [])


class FilterRq1TablesTest(unittest.TestCase):
    """RQ1 只保留 static_observation / occlusion_recovery 场景行。"""

    def test_keeps_only_rq1_conditions(self) -> None:
        """过滤掉非 RQ1 场景（如 slow_translation）。"""

        tables = {
            "anchor_error_summary": pd.DataFrame(
                {
                    "condition": ["static_observation", "slow_translation", "occlusion_recovery"],
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
        self.assertNotIn("slow_translation", set(filtered["anchor_error_summary"]["condition"]))
        self.assertNotIn("rotation", set(filtered["jitter_summary"]["condition"]))

    def test_table_without_condition_column_passes_through(self) -> None:
        """没有 condition 列的表原样保留。"""

        tables = {"misc": pd.DataFrame({"x": [1, 2]})}
        filtered = filter_rq1_tables(tables)
        self.assertEqual(len(filtered["misc"]), 2)


if __name__ == "__main__":
    unittest.main()

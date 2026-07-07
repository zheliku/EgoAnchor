"""RQ1 analyze 薄封装测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from egoanchor.eval.research.rq1.analyze import (
    RQ1_CONDITIONS,
    filter_rq1_tables,
    synthesize_occlusion_markers,
    write_rq1_figure,
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


class WriteRq1FigureTest(unittest.TestCase):
    """RQ1 三联图导出：写 PDF/PNG，空数据不抛异常。"""

    def _detail(self) -> pd.DataFrame:
        """构造最小 anchor_error_detail（含 static 与 occlusion 两场景两变体）。"""

        rows = []
        for condition in ("static_observation", "occlusion_recovery"):
            for label in ("Full", "No-StaticLock"):
                for i in range(5):
                    rows.append(
                        {
                            "render_mono_ms": float(i * 10),
                            "condition": condition,
                            "label": label,
                            "translation_error_m": 0.005,
                        }
                    )
        return pd.DataFrame(rows)

    def test_writes_pdf_and_png(self) -> None:
        """有数据时写出 .pdf 与 .png，返回 PDF 路径。"""

        tables = {
            "anchor_error_detail": self._detail(),
            "jitter_summary": pd.DataFrame(
                {
                    "condition": ["static_observation", "static_observation"],
                    "label": ["Full", "No-StaticLock"],
                    "position_jitter_rms_m": [0.0003, 0.0013],
                }
            ),
            "slip_summary": pd.DataFrame(
                {
                    "condition": ["static_observation", "static_observation"],
                    "label": ["Full", "No-StaticLock"],
                    "slip_rms_px": [1.6, 1.8],
                }
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            out = write_rq1_figure(tables, Path(tmp) / "fig_rq1_static")
            self.assertTrue(out.with_suffix(".pdf").exists())
            self.assertTrue(out.with_suffix(".png").exists())

    def test_empty_tables_still_write_placeholders(self) -> None:
        """全空表也写出文件（占位面板），不抛异常。"""

        with tempfile.TemporaryDirectory() as tmp:
            out = write_rq1_figure({}, Path(tmp) / "fig_rq1_static")
            self.assertTrue(out.with_suffix(".pdf").exists())


if __name__ == "__main__":
    unittest.main()

"""实验一 PDF 产物测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from matplotlib.axes import Axes

from egoanchor.eval.experiments.exp1_system_characterization import (
    OUTPUT_FIGURES,
    VARIANTS,
    write_exp1_figures,
)


class Exp1FiguresTest(unittest.TestCase):
    """验证固定文件名、PDF 内容及系统绘制顺序。"""

    def test_run_exp1_writes_all_pdf_outputs_in_fixed_variant_order(self) -> None:
        calls: list[tuple[str, str]] = []
        original_bar = Axes.bar

        def record_bar(axes: Axes, *args: object, **kwargs: object) -> object:
            """记录图例类别，同时保留 Matplotlib 的真实 PDF 写出行为。"""

            calls.append((str(kwargs.get("label", "")), str(kwargs.get("color", ""))))
            return original_bar(axes, *args, **kwargs)

        with tempfile.TemporaryDirectory() as temp, patch.object(Axes, "bar", record_bar):
            root = Path(temp)
            reversed_variants = list(reversed(VARIANTS))
            tables = {
                "exp1_static_quality": pd.DataFrame(
                    {"variant_label": reversed_variants, "translation_error_mm_median": [40.0] * 4}
                ),
                "exp1_transition_response": pd.DataFrame(
                    {"variant_label": reversed_variants, "peak_translation_error_mm": [50.0] * 4}
                ),
                "exp1_occlusion_recovery": pd.DataFrame(
                    {"variant_label": reversed_variants, "display_availability": [0.9] * 4}
                ),
                "exp1_condition_summary": pd.DataFrame(
                    {
                        "variant_label": reversed_variants,
                        "metric_name": ["translation_error_mm_median"] * 4,
                        "median": [10.0] * 4,
                    }
                ),
            }
            paths = write_exp1_figures(pd.DataFrame(), tables, root / "out")

            self.assertEqual([path.name for path in paths], list(OUTPUT_FIGURES))
            for name in OUTPUT_FIGURES:
                path = root / "out" / name
                self.assertTrue(path.is_file(), name)
                self.assertEqual(path.read_bytes()[:5], b"%PDF-")
                self.assertGreater(path.stat().st_size, 1000)

        palette = ("#4C78A8", "#F58518", "#54A24B", "#E45756")
        expected_calls = list(zip(VARIANTS, palette, strict=True)) * len(OUTPUT_FIGURES)
        self.assertEqual(calls, expected_calls)


if __name__ == "__main__":
    unittest.main()

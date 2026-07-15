"""实验二 PDF 产物契约测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from matplotlib.axes import Axes

from egoanchor.eval.experiments.exp2_design_attribution import (
    REQUIRED_VARIANTS,
    write_exp2_figures,
)


_OUTPUT_FIGURES = (
    "exp2_component_delta.pdf",
    "exp2_alignment_effect.pdf",
    "exp2_temporal_synthesis_effect.pdf",
    "exp2_static_lock_tradeoff.pdf",
    "exp2_vcd_risk_coverage.pdf",
)


def _summary() -> pd.DataFrame:
    """构造逆序消融行，验证绘图不受输入顺序影响。"""

    rows: list[dict[str, object]] = []
    for index, variant in enumerate(reversed(REQUIRED_VARIANTS[1:]), start=1):
        rows.append(
            {
                "scenario_id": f"scenario-{index}",
                "variant_label": variant,
                "metric": "display_error.translation_error_mm_median",
                "paired_n": 4,
                "delta_mean": float(index),
                "delta_median": float(index),
            }
        )
    rows.extend(
        (
            {
                "scenario_id": "without_temporal_synthesis",
                "variant_label": REQUIRED_VARIANTS[3],
                "metric": "transition.visible_response_time_ms",
                "paired_n": 4,
                "delta_mean": 12.0,
                "delta_median": 12.0,
            },
            {
                "scenario_id": "without_static_lock",
                "variant_label": REQUIRED_VARIANTS[4],
                "metric": "static.position_hp_rms_mm",
                "paired_n": 4,
                "delta_mean": 3.5,
                "delta_median": 3.5,
            },
        )
    )
    return pd.DataFrame(rows)


class Exp2FiguresTest(unittest.TestCase):
    """验证五个 PDF 及全部类别图的冻结顺序与颜色。"""

    def test_write_exp2_figures_uses_fixed_variant_order_and_palette(self) -> None:
        calls: list[tuple[str, str]] = []
        original_bar = Axes.bar

        def record_bar(axes: Axes, *args: object, **kwargs: object) -> object:
            """记录类别图例和颜色，同时执行真实绘制。"""

            calls.append((str(kwargs.get("label", "")), str(kwargs.get("color", ""))))
            return original_bar(axes, *args, **kwargs)

        risk = pd.DataFrame(
            {"coverage": [0.5, 1.0], "selective_risk_mm": [10.0, 20.0]}
        )
        with tempfile.TemporaryDirectory() as temp, patch.object(Axes, "bar", record_bar):
            output = Path(temp)
            write_exp2_figures(_summary(), risk, output)
            for filename in _OUTPUT_FIGURES:
                path = output / filename
                self.assertTrue(path.is_file(), filename)
                self.assertEqual(path.read_bytes()[:5], b"%PDF-")
                self.assertGreater(path.stat().st_size, 1000)
            self.assertEqual(list(output.glob("*.png")), [])

        palette = ("#4C78A8", "#F58518", "#54A24B", "#E45756", "#72B7B2")
        colors = dict(zip(REQUIRED_VARIANTS, palette, strict=True))
        expected_variants = (
            *REQUIRED_VARIANTS,
            REQUIRED_VARIANTS[0],
            REQUIRED_VARIANTS[1],
            REQUIRED_VARIANTS[0],
            REQUIRED_VARIANTS[3],
            REQUIRED_VARIANTS[0],
            REQUIRED_VARIANTS[4],
        )
        self.assertEqual(calls, [(variant, colors[variant]) for variant in expected_variants])


if __name__ == "__main__":
    unittest.main()

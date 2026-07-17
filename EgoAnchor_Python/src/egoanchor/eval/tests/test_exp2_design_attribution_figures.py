"""实验二 PDF 产物契约测试。

新绘图层核心为组件归因热力图（替代单指标条形），另有三张单组件效应图和
VCD risk-coverage 曲线。测试验证固定文件名和有效 PDF 内容，不再依赖条形
图颜色调用次序（热力图用 Rectangle 而非 bar 绘制）。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from egoanchor.eval.experiments.exp2_design_attribution import (
    ABLATION_VARIANTS,
    BASELINE_VARIANT,
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
    """构造覆盖四个消融和多指标的配对差汇总。"""

    rows: list[dict[str, object]] = []
    for variant_index, variant in enumerate(ABLATION_VARIANTS):
        for metric_index, metric in enumerate(
            (
                "display_error.translation_error_mm_median",
                "display_error.translation_error_mm_p95",
                "static.position_hp_rms_mm",
                "transition.visible_response_time_ms",
            )
        ):
            rows.append(
                {
                    "scenario_id": f"scenario-{variant_index}",
                    "variant_label": variant,
                    "metric": metric,
                    "paired_n": 5,
                    "delta_mean": float(variant_index + metric_index) * 0.5,
                    "delta_median": float(variant_index + metric_index) * 0.5,
                }
            )
    return pd.DataFrame.from_records(rows)


class Exp2FiguresTest(unittest.TestCase):
    """验证五个 PDF 固定文件名与有效内容。"""

    def test_write_exp2_figures_emits_all_pdfs(self) -> None:
        risk = pd.DataFrame(
            {
                "coverage": [0.2, 0.5, 0.8, 1.0],
                "selective_risk_mm": [8.0, 10.0, 15.0, 20.0],
            }
        )
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            write_exp2_figures(_summary(), risk, output)
            for filename in _OUTPUT_FIGURES:
                path = output / filename
                self.assertTrue(path.is_file(), filename)
                self.assertEqual(path.read_bytes()[:5], b"%PDF-")
                self.assertGreater(path.stat().st_size, 1000)

    def test_write_exp2_figures_tolerates_empty_summary(self) -> None:
        """summary 缺失时仍应写出占位图，不抛异常。"""

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            write_exp2_figures(pd.DataFrame(), pd.DataFrame(), output)
            for filename in _OUTPUT_FIGURES:
                path = output / filename
                self.assertTrue(path.is_file(), filename)
                self.assertEqual(path.read_bytes()[:5], b"%PDF-")


if __name__ == "__main__":
    unittest.main()

"""实验一 PDF 产物测试。

新绘图层按场景组织，主图为 5 场景 × 3 指标网格，另有静止/起停/遮挡三张
复合时间线。测试验证固定文件名、有效 PDF 字节和最小内容规模，同时构造
``build_scenario_headline`` 所需的按场景输入表与逐帧 render 序列。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from egoanchor.eval.experiments.exp1_system_characterization import (
    OUTPUT_FIGURES,
    VARIANTS,
    write_exp1_figures,
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
    """构造静止/起停/持续场景的抖动 event 表。"""

    rows: list[dict[str, object]] = []
    for scenario in SCENARIO_ORDER:
        if scenario == "occlusion_recovery":
            continue
        for variant_index, variant in enumerate(VARIANTS):
            rows.append(
                {
                    "scenario_id": scenario,
                    "variant_label": variant,
                    "position_hp_rms_mm": 0.1 + 0.5 * variant_index,
                }
            )
    return pd.DataFrame.from_records(rows)


def _occlusion_recovery() -> pd.DataFrame:
    """构造遮挡场景逐更新跳变 event 表。"""

    return pd.DataFrame.from_records(
        [
            {
                "scenario_id": "occlusion_recovery",
                "variant_label": variant,
                "display_jump_p95_mm": 0.01 + 0.3 * index,
                "display_availability": 0.9,
            }
            for index, variant in enumerate(VARIANTS)
        ]
    )


def _render_frame() -> pd.DataFrame:
    """构造带逐帧 display/reference 位姿的最小 render 长表。"""

    rng = np.random.default_rng(0)
    rows: list[dict[str, object]] = []
    for scenario_index, scenario in enumerate(SCENARIO_ORDER, start=1):
        for tick in range(24):
            render_mono = 1000.0 * scenario_index + tick * 50.0
            reference_pos = [0.10, 0.20, 0.50]
            for variant_index, variant in enumerate(VARIANTS):
                jitter = (variant_index + 1) * 0.002
                display_pos = [
                    reference_pos[0] + rng.normal(0.0, jitter),
                    reference_pos[1] + rng.normal(0.0, jitter),
                    reference_pos[2] + rng.normal(0.0, jitter),
                ]
                rows.append(
                    {
                        "session_id": "s-fixture",
                        "experiment_id": "1_system_characterization",
                        "scenario_id": scenario,
                        "trial_id": f"trial-{scenario_index}",
                        "event_id": f"event-{scenario_index}",
                        "condition_id": variant,
                        "variant_id": variant,
                        "variant_label": variant,
                        "render_tick_id": f"tick-{scenario_index}-{tick}",
                        "render_mono_ms": render_mono,
                        "reference_pose_valid": True,
                        "has_display_pose": True,
                        "has_output_pose": True,
                        "reference_pos": reference_pos,
                        "reference_rot": [0.0, 0.0, 0.0, 1.0],
                        "display_pos": display_pos,
                        "display_rot": [0.0, 0.0, 0.0, 1.0],
                    }
                )
    return pd.DataFrame.from_records(rows)


class Exp1FiguresTest(unittest.TestCase):
    """验证固定文件名与有效 PDF 内容。"""

    def test_write_exp1_figures_emits_all_pdfs(self) -> None:
        tables = {
            "exp1_condition_summary": _condition_summary(),
            "exp1_static_quality": _static_quality(),
            "exp1_occlusion_recovery": _occlusion_recovery(),
        }
        render = _render_frame()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = write_exp1_figures(render, tables, root / "out")

            self.assertEqual({path.name for path in paths}, set(OUTPUT_FIGURES))
            for name in OUTPUT_FIGURES:
                path = root / "out" / name
                self.assertTrue(path.is_file(), name)
                self.assertEqual(path.read_bytes()[:5], b"%PDF-")
                self.assertGreater(path.stat().st_size, 1000)

    def test_write_exp1_figures_tolerates_empty_render(self) -> None:
        """render 缺失时仍应写出网格主图与占位时间线，不抛异常。"""

        tables = {
            "exp1_condition_summary": _condition_summary(),
            "exp1_static_quality": _static_quality(),
            "exp1_occlusion_recovery": _occlusion_recovery(),
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = write_exp1_figures(pd.DataFrame(), tables, root / "out")
            self.assertEqual({path.name for path in paths}, set(OUTPUT_FIGURES))
            for path in paths:
                self.assertEqual(path.read_bytes()[:5], b"%PDF-")


if __name__ == "__main__":
    unittest.main()

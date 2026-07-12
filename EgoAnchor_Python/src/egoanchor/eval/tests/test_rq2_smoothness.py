"""RQ2 运动平滑度指标（SPARC + jerk）单测。"""

import os
import unittest
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from egoanchor.eval.research.rq2.smoothness import (
    SMOOTHNESS_COLUMNS,
    compute_smoothness_summary,
    jerk_rms,
    sparc,
)


class TestSparc(unittest.TestCase):
    """SPARC 必须把平滑信号评为比阶梯信号更平滑（更接近 0）。"""

    def test_smooth_more_smooth_than_step(self):
        dt = 1.0 / 60.0
        t = np.arange(0.0, 4.0, dt)
        smooth = np.sin(2.0 * np.pi * 0.5 * t)
        # 8 Hz 采样零阶保持后重采样到 60 Hz：阶梯信号
        step_t = np.arange(0.0, 4.0, 1.0 / 8.0)
        step_vals = np.sin(2.0 * np.pi * 0.5 * step_t)
        idx = np.clip(np.searchsorted(step_t, t, side="right") - 1, 0, len(step_vals) - 1)
        step = step_vals[idx]
        self.assertGreater(sparc(smooth, dt), sparc(step, dt))

    def test_degenerate_returns_nan(self):
        self.assertTrue(np.isnan(sparc(np.zeros(3), 1.0 / 60.0)))
        self.assertTrue(np.isnan(sparc(np.array([1.0]), 1.0 / 60.0)))


class TestJerkRms(unittest.TestCase):
    """jerk RMS 对阶梯信号高于平滑信号。"""

    def test_step_more_jerky(self):
        dt = 1.0 / 60.0
        t = np.arange(0.0, 2.0, dt)
        smooth = np.column_stack([np.sin(t), np.zeros_like(t), np.zeros_like(t)])
        step = np.column_stack([np.round(np.sin(t) * 4) / 4, np.zeros_like(t), np.zeros_like(t)])
        self.assertGreater(jerk_rms(step, t), jerk_rms(smooth, t))

    def test_too_few_samples(self):
        self.assertTrue(np.isnan(jerk_rms(np.zeros((3, 3)), np.arange(3.0))))


class TestSmoothnessSummary(unittest.TestCase):
    """按 condition × label 分组产出稳定列。"""

    def test_columns_and_grouping(self):
        dt_ms = 1000.0 / 60.0
        n = 120
        rows = []
        for i in range(n):
            rows.append({
                "rq2_condition": "slow_translation",
                "rq2_trial_id": 1,
                "label": "Full",
                "render_mono_ms": i * dt_ms,
                "has_display_pose": True,
                "display_pos": [np.sin(i * dt_ms / 1000.0), 0.0, 0.0],
            })
        table = compute_smoothness_summary(pd.DataFrame(rows), session_id="s")
        self.assertEqual(list(table.columns), SMOOTHNESS_COLUMNS)
        self.assertEqual(len(table), 1)
        self.assertEqual(table.iloc[0]["label"], "Full")

    def test_empty_input(self):
        table = compute_smoothness_summary(pd.DataFrame())
        self.assertEqual(list(table.columns), SMOOTHNESS_COLUMNS)
        self.assertTrue(table.empty)


if __name__ == "__main__":
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    unittest.main()

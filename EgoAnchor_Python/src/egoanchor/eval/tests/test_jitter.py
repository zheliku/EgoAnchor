"""静止抖动指标单测。"""

from __future__ import annotations

import math
import unittest

import numpy as np
import pandas as pd

from egoanchor.eval.metrics import compute_jitter


def _yaw_quat(angle_deg: float) -> np.ndarray:
    """构造绕世界 z 轴旋转的 xyzw 四元数。"""

    half = math.radians(angle_deg) / 2.0
    return np.array([0.0, 0.0, math.sin(half), math.cos(half)], dtype=float)


def _pose_row(time_ms: float, gt_x: float, output_x: float, output_yaw: float) -> dict[str, object]:
    """构造一行可用于静止抖动分析的同步位姿。"""

    return {
        "condition": "static_observation",
        "label": "Full",
        "render_mono_ms": time_ms,
        "valid": True,
        "has_output_pose": True,
        "gt_pos": np.array([gt_x, 0.0, 0.0]),
        "output_pos": np.array([output_x, 0.0, 0.0]),
        "output_rot": _yaw_quat(output_yaw),
    }


class TestJitter(unittest.TestCase):
    """抖动滤波不得跨追踪缺口，也不得把持续运动当成静止。"""

    def test_time_gap_splits_position_and_rotation_filtering(self) -> None:
        rows = [
            _pose_row(index * 20.0, 0.0, 0.0, 0.0)
            for index in range(20)
        ]
        rows.extend(
            _pose_row(6000.0 + index * 20.0, 0.0, 0.5, 30.0)
            for index in range(20)
        )

        result = compute_jitter(pd.DataFrame.from_records(rows)).iloc[0]

        self.assertEqual(int(result["n"]), 40)
        self.assertLess(float(result["position_jitter_rms_m"]), 1e-9)
        self.assertLess(float(result["rotation_jitter_rms_deg"]), 1e-9)

    def test_all_moving_rows_are_insufficient(self) -> None:
        rows = [
            _pose_row(index * 20.0, 0.01 * index, 0.01 * index, 0.0)
            for index in range(20)
        ]

        result = compute_jitter(pd.DataFrame.from_records(rows)).iloc[0]

        self.assertTrue(bool(result["insufficient_data"]))
        self.assertEqual(int(result["n"]), 0)


if __name__ == "__main__":
    unittest.main()

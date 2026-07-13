"""RQ2 响应时序摘要单测。"""

from __future__ import annotations

import math
import unittest

import numpy as np
import pandas as pd

from egoanchor.eval.research.rq2 import RQ2Config, compute_response_summary


def _yaw_quat(angle_deg: float) -> np.ndarray:
    """构造绕世界 z 轴旋转的 xyzw 四元数。"""

    half = math.radians(angle_deg) / 2.0
    return np.array([0.0, 0.0, math.sin(half), math.cos(half)], dtype=float)


def _response_output(condition: str, lag_ms: float = 120.0) -> pd.DataFrame:
    """构造含非周期复合运动和已知显示滞后的单试次。"""

    interval_ms = 20.0
    times_ms = np.arange(0.0, 14_000.0, interval_ms)
    seconds = times_ms / 1000.0

    def motion(t: np.ndarray) -> np.ndarray:
        return np.sin(1.7 * t) + 0.45 * np.sin(4.1 * t + 0.3) + 0.15 * np.sin(7.3 * t)

    reference = motion(seconds)
    delayed = motion(np.maximum(0.0, seconds - lag_ms / 1000.0))
    rows: list[dict[str, object]] = []
    for index, render_ms in enumerate(times_ms):
        if condition == "rotation":
            gt_pos = np.zeros(3)
            display_pos = np.zeros(3)
            gt_rot = _yaw_quat(35.0 * reference[index])
            display_rot = _yaw_quat(35.0 * delayed[index])
        else:
            gt_pos = np.array([0.08 * reference[index], 0.0, 0.0])
            display_pos = np.array([0.08 * delayed[index], 0.0, 0.0])
            gt_rot = _yaw_quat(0.0)
            display_rot = _yaw_quat(0.0)
        rows.append(
            {
                "session_id": "synthetic",
                "render_mono_ms": render_ms,
                "render_unity_frame": 500 + index,
                "rq2_condition": condition,
                "rq2_trial_id": 1,
                "label": "Full",
                "analysis_motion": True,
                "gt_pose_valid": True,
                "gt_pose_fresh": True,
                "gt_pose_keep_alive": False,
                "gt_pos": gt_pos,
                "gt_rot": gt_rot,
                "has_output_pose": True,
                "has_display_pose": True,
                "display_pos": display_pos,
                "display_rot": display_rot,
                "anchor_state": "Streaming",
                "policy_action": "Apply",
                "policy_reason": "accepted",
                "observation_age_ms": 220.0 + index % 5,
                "smoothing_delay_ms": 290.0 + index % 7,
            }
        )
    return pd.DataFrame.from_records(rows)


class TestRQ2Response(unittest.TestCase):
    """响应摘要应区分记录时序与可辨识运动滞后。"""

    def test_recovers_positive_translation_lag(self) -> None:
        row = compute_response_summary(_response_output("translation")).iloc[0]

        self.assertEqual(row["lag_status"], "ok")
        self.assertAlmostEqual(float(row["empirical_lag_ms"]), 120.0, delta=25.0)
        self.assertAlmostEqual(float(row["observation_age_median_ms"]), 222.0)
        self.assertAlmostEqual(float(row["smoothing_delay_coverage"]), 1.0)

    def test_recovers_positive_rotation_lag(self) -> None:
        row = compute_response_summary(_response_output("rotation")).iloc[0]

        self.assertEqual(row["lag_status"], "ok")
        self.assertAlmostEqual(float(row["empirical_lag_ms"]), 120.0, delta=25.0)

    def test_low_excitation_is_not_reported_as_lag(self) -> None:
        output = _response_output("translation")
        output["gt_pos"] = output["gt_pos"].map(lambda _: np.zeros(3))
        output["display_pos"] = output["display_pos"].map(lambda _: np.zeros(3))

        row = compute_response_summary(output).iloc[0]

        self.assertTrue(np.isnan(float(row["empirical_lag_ms"])))
        self.assertEqual(row["lag_status"], "low_excitation")

    def test_small_valid_fragment_fails_trial_coverage(self) -> None:
        output = _response_output("translation")
        output.loc[250, "analysis_motion"] = False
        tail = output.index > 250
        output.loc[tail, "gt_pos"] = output.loc[tail, "gt_pos"].map(lambda _: np.zeros(3))
        output.loc[tail, "display_pos"] = output.loc[tail, "display_pos"].map(
            lambda _: np.zeros(3)
        )

        row = compute_response_summary(
            output,
            RQ2Config(min_lag_sample_coverage=0.50),
        ).iloc[0]

        self.assertTrue(np.isnan(float(row["empirical_lag_ms"])))
        self.assertEqual(row["lag_status"], "low_coverage")
        self.assertLess(float(row["lag_sample_coverage"]), 0.50)


if __name__ == "__main__":
    unittest.main()

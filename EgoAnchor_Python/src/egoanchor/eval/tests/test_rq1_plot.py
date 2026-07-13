"""RQ1 静止 XYZ-帧图单测。"""

from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from egoanchor.eval.research.rq1 import write_rq1_timelines


def _yaw_quat(angle_deg: float) -> np.ndarray:
    """构造绕世界 z 轴旋转的 xyzw 四元数。"""

    half = math.radians(angle_deg) / 2.0
    return np.array([0.0, 0.0, math.sin(half), math.cos(half)], dtype=float)


def _static_output() -> pd.DataFrame:
    """构造先未锁定、后连续锁定的同步双变体日志。"""

    rows: list[dict[str, object]] = []
    for sample in range(240):
        frame = 500 + sample
        reference_pos = np.array([0.1, -0.2, 0.4])
        reference_rot = _yaw_quat(15.0)
        for label in ("Full", "No-StaticLock"):
            noise = 0.0 if label == "Full" else 0.0015 * math.sin(sample * 0.4)
            display_pos = reference_pos + np.array([noise, -0.5 * noise, 0.25 * noise])
            display_rot = _yaw_quat(15.0 + (0.0 if label == "Full" else 1.5 * math.sin(sample * 0.3)))
            rows.append(
                {
                    "render_mono_ms": sample * 16.0,
                    "render_unity_frame": frame,
                    "rq1_metric": "static_observation",
                    "label": label,
                    "latest_static_locked": label == "Full" and sample >= 20,
                    "gt_pose_valid": True,
                    "gt_pos": reference_pos,
                    "gt_rot": reference_rot,
                    "has_display_pose": True,
                    "display_pos": display_pos,
                    "display_rot": display_rot,
                }
            )
    return pd.DataFrame.from_records(rows)


class TestRQ1Timeline(unittest.TestCase):
    """静止图应按锁定状态选窗并独立导出位置和旋转。"""

    def test_writes_two_fixed_frame_timelines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metadata = write_rq1_timelines(_static_output(), tmp, frame_count=120)

            destination = Path(tmp)
            self.assertTrue((destination / "fig_rq1_position_timeline.pdf").is_file())
            self.assertTrue((destination / "fig_rq1_rotation_timeline.pdf").is_file())
            self.assertTrue((destination / "fig_rq1_position_timeline.png").is_file())
            self.assertTrue((destination / "fig_rq1_rotation_timeline.png").is_file())
            self.assertEqual(int(metadata.iloc[0]["window_start_unity_frame"]), 520)
            self.assertEqual(int(metadata.iloc[0]["window_end_unity_frame"]), 639)
            self.assertEqual(int(metadata.iloc[0]["render_tick_count"]), 120)

    def test_empty_run_removes_stale_timelines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp)
            names = (
                "fig_rq1_position_timeline.pdf",
                "fig_rq1_position_timeline.png",
                "fig_rq1_rotation_timeline.pdf",
                "fig_rq1_rotation_timeline.png",
            )
            for name in names:
                (destination / name).write_bytes(b"stale")

            metadata = write_rq1_timelines(pd.DataFrame(), destination)

            self.assertTrue(metadata.empty)
            self.assertFalse(any((destination / name).exists() for name in names))


if __name__ == "__main__":
    unittest.main()

"""RQ2 XYZ-帧时间线纯绘图层单测。"""

from __future__ import annotations

import math
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from egoanchor.eval.research.rq2 import (
    RQ2Config,
    world_rotation_vectors_from_reference,
    write_rq2_timelines,
)


def _yaw_quat(angle_deg: float) -> np.ndarray:
    """构造绕世界 z 轴旋转的 xyzw 四元数。"""

    half = math.radians(angle_deg) / 2.0
    return np.array([0.0, 0.0, math.sin(half), math.cos(half)], dtype=float)


def _timeline_output() -> pd.DataFrame:
    """构造两类任务与三个不同速度的平移候选试次。"""

    rows: list[dict[str, object]] = []
    tick = 0
    specs = [
        ("translation", 1, 0.1),
        ("translation", 2, 0.4),
        ("translation", 3, 0.7),
        ("rotation", 4, 80.0),
    ]
    for condition, trial_id, speed in specs:
        for sample, seconds in enumerate(np.arange(0.0, 6.0, 0.05)):
            gt_pos = np.array([speed * seconds if condition == "translation" else 0.0, 0.02 * seconds, 0.0])
            gt_rot = _yaw_quat(speed * seconds if condition == "rotation" else 0.0)
            for label in ("Full", "ZOH"):
                held = math.floor(seconds * 10.0) / 10.0
                display_seconds = seconds if label == "Full" else held
                display_pos = np.array(
                    [speed * display_seconds if condition == "translation" else 0.0, 0.02 * display_seconds, 0.0]
                )
                display_rot = _yaw_quat(
                    speed * display_seconds if condition == "rotation" else 0.0
                )
                rows.append(
                    {
                        "session_id": "s1",
                        "tick_index": tick,
                        "render_unity_frame": 1000 + tick,
                        "render_mono_ms": trial_id * 10_000.0 + seconds * 1000.0,
                        "rq2_condition": condition,
                        "rq2_trial_id": trial_id,
                        "label": label,
                        "analysis_motion": True,
                        "gt_linear_speed_smooth_m_s": speed if condition == "translation" else 0.0,
                        "gt_angular_speed_smooth_deg_s": speed if condition == "rotation" else 0.0,
                        "gt_pose_valid": True,
                        "gt_pose_fresh": True,
                        "gt_pose_keep_alive": False,
                        "gt_pos": gt_pos,
                        "gt_rot": gt_rot,
                        "has_display_pose": True,
                        "display_pos": display_pos,
                        "display_rot": display_rot,
                    }
                )
            tick += 1
    return pd.DataFrame.from_records(rows)


class TestRQ2Timeline(unittest.TestCase):
    """时间线应保持旋转连续、固定放大并独立导出两张子图。"""

    def test_world_rotvec_uses_exact_common_reference_for_multiaxis_motion(self) -> None:
        from scipy.spatial.transform import Rotation

        rotations = Rotation.from_euler(
            "xyz",
            [[10.0, 5.0, 0.0], [20.0, 15.0, 5.0], [35.0, 20.0, 15.0]],
            degrees=True,
        ).as_quat()
        values = world_rotation_vectors_from_reference(rotations[0], rotations)
        reference = Rotation.from_quat(rotations[0])
        expected = (Rotation.from_quat(rotations) * reference.inv()).as_rotvec()

        np.testing.assert_allclose(values, expected, atol=1e-12)

    def test_writes_two_fixed_frame_subfigures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metadata = write_rq2_timelines(
                _timeline_output(),
                tmp,
                config=RQ2Config(zoom_frame_count=80),
            )

            destination = Path(tmp)
            self.assertTrue((destination / "fig_rq2_position_timeline.pdf").is_file())
            self.assertTrue((destination / "fig_rq2_rotation_timeline.pdf").is_file())
            self.assertTrue((destination / "fig_rq2_position_timeline.png").is_file())
            self.assertTrue((destination / "fig_rq2_rotation_timeline.png").is_file())
            self.assertEqual(len(metadata), 2)
            self.assertTrue((metadata["render_tick_count"] == 80).all())
            self.assertTrue((metadata["window_frame_span"] == 79).all())
            translation = metadata[metadata["condition"].eq("translation")].iloc[0]
            self.assertEqual(int(translation["rq2_trial_id"]), 2)

    def test_empty_run_removes_stale_timelines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp)
            names = (
                "fig_rq2_position_timeline.pdf",
                "fig_rq2_position_timeline.png",
                "fig_rq2_rotation_timeline.pdf",
                "fig_rq2_rotation_timeline.png",
            )
            for name in names:
                (destination / name).write_bytes(b"stale")

            metadata = write_rq2_timelines(pd.DataFrame(), destination)

            self.assertTrue(metadata.empty)
            self.assertFalse(any((destination / name).exists() for name in names))


if __name__ == "__main__":
    unittest.main()

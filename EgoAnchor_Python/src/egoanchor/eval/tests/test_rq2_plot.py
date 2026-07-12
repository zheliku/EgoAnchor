"""RQ2 实时轨迹 hero 图纯绘图层单测（不依赖 cv2）。"""

import os
import sys
import unittest
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from egoanchor.eval.research.rq2.plot import (
    write_rq2_dynamic_figure,
    write_rq2_hero_figure,
)


def _synthetic_output() -> pd.DataFrame:
    """构造含参考真值 / 完整锚定 / ZOH / 感知观测的最小实时轨迹。"""

    dt_ms = 1000.0 / 60.0
    rows: list[dict[str, object]] = []
    for condition, trial_id in (("fast_motion", 2), ("rotation", 3)):
        for i in range(480):
            t = i * dt_ms / 1000.0
            zoh_t = np.floor(t * 8.0) / 8.0
            gt_x = float(0.25 * np.sin(2.0 * np.pi * 0.45 * t))
            full_x = float(0.25 * np.sin(2.0 * np.pi * 0.45 * (t - 0.29)))
            zoh_x = float(0.25 * np.sin(2.0 * np.pi * 0.45 * (zoh_t - 0.22)))
            gt_angle = float(70.0 * np.sin(2.0 * np.pi * 0.32 * t))
            full_angle = float(70.0 * np.sin(2.0 * np.pi * 0.32 * (t - 0.29)))
            zoh_angle = float(70.0 * np.sin(2.0 * np.pi * 0.32 * (zoh_t - 0.22)))
            gt_pos = [gt_x, 0.1, 0.2]
            gt_rot = _yaw_quat(gt_angle)
            for label, display_x, display_angle in (
                ("Full", full_x, full_angle),
                ("Raw-ZOH", zoh_x, zoh_angle),
            ):
                has_raw = label == "Full" and i % 8 == 0
                rows.append(
                    {
                        "rq2_condition": condition,
                        "rq2_trial_id": trial_id,
                        "label": label,
                        "is_primary": label == "Full",
                        "render_mono_ms": i * dt_ms,
                        "source_frame_id": i // 8 if has_raw else -1,
                        "active_motion": True,
                        "has_display_pose": True,
                        "display_pos": [display_x, 0.1, 0.2],
                        "display_rot": _yaw_quat(display_angle),
                        "has_aligned_raw": has_raw,
                        "aligned_raw_pos": gt_pos if has_raw else None,
                        "aligned_raw_rot": gt_rot if has_raw else None,
                        "gt_pos": gt_pos,
                        "gt_rot": gt_rot,
                        "gt_pose_valid": True,
                        "gt_pose_fresh": True,
                        "gt_linear_speed_m_s": abs(
                            float(0.25 * 2.0 * np.pi * 0.45 * np.cos(2.0 * np.pi * 0.45 * t))
                        ),
                        "gt_linear_speed_smooth_m_s": abs(
                            float(0.25 * 2.0 * np.pi * 0.45 * np.cos(2.0 * np.pi * 0.45 * t))
                        ),
                        "gt_angular_speed_smooth_rad_s": abs(
                            float(
                                np.deg2rad(70.0)
                                * 2.0
                                * np.pi
                                * 0.32
                                * np.cos(2.0 * np.pi * 0.32 * t)
                            )
                        ),
                    }
                )
    return pd.DataFrame(rows)


def _yaw_quat(angle_deg: float) -> list[float]:
    """构造绕 z 轴旋转的 xyzw 四元数。"""

    half = np.deg2rad(angle_deg) / 2.0
    return [0.0, 0.0, float(np.sin(half)), float(np.cos(half))]


class TestHeroFigure(unittest.TestCase):
    """hero 图应在有合格 trial 时产出 PDF + PNG，空输入返回 None。"""

    def test_writes_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_rq2_hero_figure(_synthetic_output(), tmp)
            self.assertIsNotNone(path)
            self.assertTrue(Path(path).exists())
            self.assertTrue(
                (Path(tmp) / "rq2_hero_trajectory_preliminary.png").exists()
            )

    def test_empty_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(write_rq2_hero_figure(pd.DataFrame(), tmp))


def _synthetic_trial_summary() -> pd.DataFrame:
    """构造三类运动 Full/Raw-ZOH 各一行的最小 trial summary。"""

    rows = []
    presets = {
        "slow_translation": (1, 42.0, 8.2, 0.26, 0.85, 0.049, 0.116, 0.037, 0.077),
        "fast_motion": (2, 54.1, 8.1, 0.03, 0.86, 0.129, 0.236, 0.098, 0.208),
        "rotation": (3, 66.2, 9.5, 0.04, 0.86, 0.013, 0.039, 0.012, 0.032),
    }
    for condition, vals in presets.items():
        (
            trial_id,
            full_hz,
            zoh_hz,
            full_hold,
            zoh_hold,
            full_med,
            full_p95,
            zoh_med,
            zoh_p95,
        ) = vals
        rows.append(
            {
                "session_id": "synthetic",
                "condition": condition,
                "rq2_trial_id": trial_id,
                "label": "Full",
                "display_update_rate_hz": full_hz,
                "display_hold_fraction": full_hold,
                "display_translation_median_m": full_med,
                "display_translation_p95_m": full_p95,
                "display_rotation_median_deg": 30.7 if condition == "rotation" else 6.0,
                "display_rotation_p95_deg": 67.5 if condition == "rotation" else 15.0,
                "audit_accepted": True,
            }
        )
        rows.append(
            {
                "session_id": "synthetic",
                "condition": condition,
                "rq2_trial_id": trial_id,
                "label": "Raw-ZOH",
                "display_update_rate_hz": zoh_hz,
                "display_hold_fraction": zoh_hold,
                "display_translation_median_m": zoh_med,
                "display_translation_p95_m": zoh_p95,
                "display_rotation_median_deg": 24.6 if condition == "rotation" else 5.0,
                "display_rotation_p95_deg": 59.7 if condition == "rotation" else 13.0,
                "audit_accepted": True,
            }
        )
    return pd.DataFrame(rows)


class TestDynamicFigure(unittest.TestCase):
    """四面板合成图应在有合格 trial 时产出 PDF + PNG，空表返回 None。"""

    def test_writes_pdf(self):
        tables = {
            "rq2_trial_summary": _synthetic_trial_summary(),
            "rq2_motion_delay": pd.DataFrame(),
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = write_rq2_dynamic_figure(_synthetic_output(), tables, tmp)
            self.assertIsNotNone(path)
            self.assertTrue(Path(path).exists())
            self.assertTrue(
                (Path(tmp) / "fig_rq2_dynamic_preliminary.png").exists()
            )

    def test_empty_summary_returns_none(self):
        tables = {"rq2_trial_summary": pd.DataFrame(), "rq2_motion_delay": pd.DataFrame()}
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(
                write_rq2_dynamic_figure(_synthetic_output(), tables, tmp)
            )


if __name__ == "__main__":
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    unittest.main()

"""schema-v2 静止质量指标单测。"""

from __future__ import annotations

import math
import unittest

import pandas as pd

from egoanchor.eval.metrics import compute_static_metrics


def _yaw_quat(angle_deg: float) -> list[float]:
    """构造绕世界 z 轴旋转的 xyzw 四元数。"""

    half = math.radians(angle_deg) / 2.0
    return [0.0, 0.0, math.sin(half), math.cos(half)]


def _render_row(
    time_ms: float,
    *,
    display_x: float,
    reference_x: float = 0.0,
    display_yaw: float = 0.0,
    reference_yaw: float = 0.0,
    linear_speed: float = 0.0,
    angular_speed: float = 0.0,
    has_display_pose: bool = True,
) -> dict[str, object]:
    """构造一行完整的 schema-v2 静止分析 render 数据。"""

    return {
        "session_id": "session-1",
        "experiment_id": "experiment-1",
        "scenario_id": "static_head_motion",
        "trial_id": "trial-1",
        "event_id": "event-1",
        "condition_id": "condition-1",
        "variant_id": "egoanchor",
        "variant_label": "EgoAnchor",
        "render_mono_ms": time_ms,
        "reference_pose_valid": True,
        "reference_pos": [reference_x, 0.0, 0.0],
        "reference_rot": _yaw_quat(reference_yaw),
        "reference_linear_speed_m_s": linear_speed,
        "reference_angular_speed_deg_s": angular_speed,
        "has_display_pose": has_display_pose,
        "display_pos": [display_x, 0.0, 0.0] if has_display_pose else None,
        "display_rot": _yaw_quat(display_yaw) if has_display_pose else None,
    }


class StaticMetricsTest(unittest.TestCase):
    """静止指标必须同时揭示抖动、绝对错误和连续段内漂移。"""

    def test_static_mask_break_does_not_join_two_constant_runs(self) -> None:
        """动态行必须切断静止 run，两个常量台阶不能被高通当成抖动。"""

        rows = [_render_row(index * 20.0, display_x=0.0) for index in range(3)]
        rows.append(
            _render_row(60.0, display_x=0.5, linear_speed=1.0, angular_speed=30.0)
        )
        rows.extend(
            _render_row(80.0 + index * 20.0, display_x=0.5)
            for index in range(3)
        )

        result = compute_static_metrics(pd.DataFrame.from_records(rows)).iloc[0]

        self.assertEqual(int(result["segment_count"]), 2)
        self.assertEqual(int(result["n"]), 6)
        self.assertLess(float(result["position_hp_rms_mm"]), 1e-8)
        self.assertLess(float(result["position_drift_mm"]), 1e-8)

    def test_frozen_wrong_pose_has_low_hp_rms_but_large_absolute_error(self) -> None:
        """冻结在错误位置不能只凭低 HP-RMS 获得好的静止质量。"""

        rows = [
            _render_row(index * 20.0, display_x=0.5, display_yaw=20.0)
            for index in range(12)
        ]

        result = compute_static_metrics(pd.DataFrame.from_records(rows)).iloc[0]

        self.assertLess(float(result["position_hp_rms_mm"]), 1e-8)
        self.assertLess(float(result["rotation_hp_rms_deg"]), 1e-8)
        self.assertAlmostEqual(float(result["translation_error_mm_median"]), 500.0)
        self.assertAlmostEqual(float(result["rotation_error_deg_median"]), 20.0)
        self.assertAlmostEqual(float(result["position_drift_mm"]), 0.0)

    def test_missing_display_row_breaks_static_run(self) -> None:
        """hold 空窗中的无显示 tick 必须切段，不能被过滤后重新拼接。"""

        rows = [_render_row(index * 20.0, display_x=0.0) for index in range(3)]
        rows.append(_render_row(60.0, display_x=0.0, has_display_pose=False))
        rows.extend(
            _render_row(80.0 + index * 20.0, display_x=0.2)
            for index in range(3)
        )

        result = compute_static_metrics(pd.DataFrame.from_records(rows)).iloc[0]

        self.assertEqual(int(result["segment_count"]), 2)
        self.assertLess(float(result["position_hp_rms_mm"]), 1e-8)

    def test_all_moving_rows_are_insufficient(self) -> None:
        """参考持续运动时不应输出伪静止指标。"""

        rows = [
            _render_row(index * 20.0, display_x=0.01 * index, linear_speed=0.5)
            for index in range(20)
        ]

        result = compute_static_metrics(pd.DataFrame.from_records(rows)).iloc[0]

        self.assertTrue(bool(result["insufficient_data"]))
        self.assertEqual(int(result["n"]), 0)


if __name__ == "__main__":
    unittest.main()

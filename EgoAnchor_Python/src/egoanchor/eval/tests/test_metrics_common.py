"""eval/metrics 通用几何工具测试。"""

from __future__ import annotations

import math
import unittest

import numpy as np
import pandas as pd

from egoanchor.eval.metrics import (
    METRIC_GROUP_COLUMNS,
    angle_deg,
    compute_anchor_error,
    highpass,
    is_pose_vector,
    iter_metric_groups,
    mat_to_pos_quat,
    pose_error,
    pos_quat_to_mat,
    project_point,
    require_columns,
    slerp_lerp_resample,
)


class MetricsCommonTest(unittest.TestCase):
    """验证平台 reference 与 display pose 评估所需的基础几何运算。"""

    def test_pos_quat_matrix_round_trip(self) -> None:
        """pos/quat 与 4x4 矩阵往返应保持同一 Unity world pose。"""

        pos = np.array([0.1, -0.2, 0.3], dtype=float)
        quat = _axis_angle([0.0, 1.0, 0.0], 35.0)

        mat = pos_quat_to_mat(pos, quat)
        out_pos, out_quat = mat_to_pos_quat(mat)

        np.testing.assert_allclose(out_pos, pos, atol=1e-9)
        self.assertAlmostEqual(abs(float(np.dot(out_quat, quat))), 1.0, places=9)

    def test_pose_error_directly_compares_reference_and_display(self) -> None:
        """pose_error 应直接计算平台 reference 与 display pose 的平移和旋转误差。"""

        reference_pos = np.zeros(3, dtype=float)
        reference_rot = np.array([0.0, 0.0, 0.0, 1.0], dtype=float)
        display_pos = np.array([0.03, 0.0, 0.0], dtype=float)
        display_rot = _axis_angle([0.0, 0.0, 1.0], 90.0)

        translation_m, rotation_deg = pose_error(
            reference_pos,
            reference_rot,
            display_pos,
            display_rot,
        )

        self.assertAlmostEqual(translation_m, 0.03, places=9)
        self.assertAlmostEqual(rotation_deg, 90.0, places=9)

    def test_slerp_lerp_resample_interpolates_pose(self) -> None:
        """位姿重采样应线性插值位置并球面插值旋转。"""

        t_src = np.array([0.0, 1000.0], dtype=float)
        pos = np.array([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]], dtype=float)
        quat = np.array(
            [
                [0.0, 0.0, 0.0, 1.0],
                _axis_angle([0.0, 0.0, 1.0], 90.0),
            ],
            dtype=float,
        )

        out_pos, out_quat = slerp_lerp_resample(t_src, pos, quat, np.array([500.0]))

        np.testing.assert_allclose(out_pos[0], np.array([1.0, 0.0, 0.0]), atol=1e-9)
        self.assertAlmostEqual(angle_deg(out_quat[0]), 45.0, places=6)

    def test_highpass_removes_constant_signal(self) -> None:
        """高通滤波面对常量信号应输出接近零的残差。"""

        signal = np.ones((20, 3), dtype=float) * np.array([1.0, 2.0, 3.0])

        filtered = highpass(signal, dt=0.01, cutoff_hz=1.0)

        np.testing.assert_allclose(filtered, np.zeros_like(signal), atol=1e-8)

    def test_project_point_uses_world_camera_pose(self) -> None:
        """世界点应先转到相机局部系，再用 K 投影到像素坐标。"""

        k = np.array([[100.0, 0.0, 320.0], [0.0, 100.0, 240.0], [0.0, 0.0, 1.0]])
        w_t_cam = pos_quat_to_mat(np.zeros(3), np.array([0.0, 0.0, 0.0, 1.0]))

        uv = project_point(k, w_t_cam, np.array([1.0, 0.5, 2.0]))

        np.testing.assert_allclose(uv, np.array([370.0, 265.0]), atol=1e-9)

    def test_metric_groups_keep_trial_event_and_variant_isolated(self) -> None:
        """固定分组键必须隔离不同 event 和 variant，且上下文统一返回字符串。"""

        first = _metric_context(event_id="event-a", variant_id="arrival")
        second = _metric_context(event_id="event-b", variant_id="egoanchor")
        frame = pd.DataFrame.from_records([{**first, "value": 1}, {**second, "value": 2}])

        groups = list(iter_metric_groups(frame))

        self.assertEqual(len(groups), 2)
        self.assertEqual(set(groups[0][0]), set(METRIC_GROUP_COLUMNS))
        self.assertTrue(all(isinstance(value, str) for value in groups[0][0].values()))
        self.assertEqual(sum(len(group) for _, group in groups), 2)

    def test_require_columns_rejects_incomplete_metric_table(self) -> None:
        """缺少任一声明列时应立即失败，不能静默生成 NaN 指标。"""

        with self.assertRaisesRegex(ValueError, "missing"):
            require_columns(pd.DataFrame({"present": [1]}), ("present", "missing"), table_name="unit")

    def test_is_pose_vector_requires_finite_numeric_shape(self) -> None:
        """位姿向量必须长度正确、数值有限且不能由布尔值伪装。"""

        self.assertTrue(is_pose_vector([0.0, 1.0, 2.0], 3))
        self.assertFalse(is_pose_vector([0.0, float("nan"), 2.0], 3))
        self.assertFalse(is_pose_vector([True, False, True], 3))
        self.assertFalse(is_pose_vector([0.0, 1.0], 3))

    def test_anchor_error_uses_hold_last_display_pose(self) -> None:
        """runtime 无新输出但仍显示 hold-last 时，显示误差必须进入统计。"""

        row = {
            **_metric_context(),
            "render_tick_id": 5,
            "render_mono_ms": 120.0,
            "source_frame_id": 7,
            "reference_pose_valid": True,
            "reference_pos": [0.0, 0.0, 0.0],
            "reference_rot": [0.0, 0.0, 0.0, 1.0],
            "has_output_pose": False,
            "has_display_pose": True,
            "display_pos": [0.1, 0.0, 0.0],
            "display_rot": [0.0, 0.0, 0.0, 1.0],
            "anchor_state": "stale",
            "policy_action": "hold",
            "policy_reason": "hold_last",
        }

        detail, summary = compute_anchor_error(pd.DataFrame.from_records([row]))

        self.assertEqual(len(detail), 1)
        self.assertAlmostEqual(float(detail.iloc[0]["translation_error_mm"]), 100.0)
        self.assertEqual(len(summary), 1)
        self.assertEqual(summary.iloc[0]["event_id"], "event-1")
        self.assertAlmostEqual(float(summary.iloc[0]["translation_error_mm_median"]), 100.0)

    def test_anchor_error_summarizes_each_context_separately(self) -> None:
        """不同 event 的显示误差不得在帧级混合后汇总。"""

        rows = []
        for tick, event_id, offset in ((1, "event-a", 0.01), (2, "event-b", 0.20)):
            rows.append(
                {
                    **_metric_context(event_id=event_id),
                    "render_tick_id": tick,
                    "render_mono_ms": float(tick * 20),
                    "source_frame_id": tick,
                    "reference_pose_valid": True,
                    "reference_pos": [0.0, 0.0, 0.0],
                    "reference_rot": [0.0, 0.0, 0.0, 1.0],
                    "has_display_pose": True,
                    "display_pos": [offset, 0.0, 0.0],
                    "display_rot": [0.0, 0.0, 0.0, 1.0],
                }
            )

        _, summary = compute_anchor_error(pd.DataFrame.from_records(rows))

        self.assertEqual(len(summary), 2)
        by_event = summary.set_index("event_id")["translation_error_mm_median"]
        self.assertAlmostEqual(float(by_event["event-a"]), 10.0)
        self.assertAlmostEqual(float(by_event["event-b"]), 200.0)


def _axis_angle(axis: list[float], degrees: float) -> np.ndarray:
    """构造 xyzw 四元数。"""

    axis_arr = np.asarray(axis, dtype=float)
    axis_arr /= np.linalg.norm(axis_arr)
    half = math.radians(degrees) * 0.5
    return np.concatenate([axis_arr * math.sin(half), np.array([math.cos(half)])])


def _metric_context(
    *,
    event_id: str = "event-1",
    variant_id: str = "egoanchor",
) -> dict[str, str]:
    """构造一组完整的 schema-v2 指标上下文键。"""

    return {
        "session_id": "session-1",
        "experiment_id": "experiment-1",
        "scenario_id": "static",
        "trial_id": "trial-1",
        "event_id": event_id,
        "condition_id": "condition-1",
        "variant_id": variant_id,
        "variant_label": variant_id,
    }


if __name__ == "__main__":
    unittest.main()

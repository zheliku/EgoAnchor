"""eval/metrics 通用几何工具测试。"""

from __future__ import annotations

import math
import unittest

import numpy as np

from eval.metrics.common import (
    angle_deg,
    highpass,
    mat_to_pos_quat,
    pose_error,
    pos_quat_to_mat,
    project_point,
    slerp_lerp_resample,
)


class MetricsCommonTest(unittest.TestCase):
    """验证 Transform GT 直接评估所需的基础几何运算。"""

    def test_pos_quat_matrix_round_trip(self) -> None:
        """pos/quat 与 4x4 矩阵往返应保持同一 Unity world pose。"""

        pos = np.array([0.1, -0.2, 0.3], dtype=float)
        quat = _axis_angle([0.0, 1.0, 0.0], 35.0)

        mat = pos_quat_to_mat(pos, quat)
        out_pos, out_quat = mat_to_pos_quat(mat)

        np.testing.assert_allclose(out_pos, pos, atol=1e-9)
        self.assertAlmostEqual(abs(float(np.dot(out_quat, quat))), 1.0, places=9)

    def test_pose_error_directly_compares_gt_and_anchor(self) -> None:
        """pose_error 应直接计算 inv(W_T_GT) * W_T_Anchor 的平移和旋转误差。"""

        gt_pos = np.zeros(3, dtype=float)
        gt_rot = np.array([0.0, 0.0, 0.0, 1.0], dtype=float)
        anchor_pos = np.array([0.03, 0.0, 0.0], dtype=float)
        anchor_rot = _axis_angle([0.0, 0.0, 1.0], 90.0)

        translation_m, rotation_deg = pose_error(gt_pos, gt_rot, anchor_pos, anchor_rot)

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


def _axis_angle(axis: list[float], degrees: float) -> np.ndarray:
    """构造 xyzw 四元数。"""

    axis_arr = np.asarray(axis, dtype=float)
    axis_arr /= np.linalg.norm(axis_arr)
    half = math.radians(degrees) * 0.5
    return np.concatenate([axis_arr * math.sin(half), np.array([math.cos(half)])])


if __name__ == "__main__":
    unittest.main()

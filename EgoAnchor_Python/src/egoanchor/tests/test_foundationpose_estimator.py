"""FoundationPose 适配器轻量契约测试。"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

import numpy as np

from egoanchor.algorithms import FoundationPoseObjectEstimator


class FoundationPoseObjectEstimatorTest(unittest.TestCase):
    """验证适配器公开 facade 使用正确的 pose 语义。"""

    def test_render_pose_uses_centered_mesh_pose(self) -> None:
        """外部 object pose 渲染 centered mesh 前应乘以 inv(to_origin)。"""

        estimator = FoundationPoseObjectEstimator.__new__(FoundationPoseObjectEstimator)
        estimator.to_origin = np.eye(4, dtype=np.float64)
        estimator.to_origin[:3, 3] = np.array([-0.2, -0.1, 0.05], dtype=np.float64)
        pose = np.eye(4, dtype=np.float64)
        pose[:3, 3] = np.array([0.5, 0.0, 1.0], dtype=np.float64)

        render_pose = estimator._pose_for_centered_mesh(pose)

        expected = pose.copy()
        expected[:3, 3] = pose[:3, 3] - estimator.to_origin[:3, 3]
        self.assertTrue(np.allclose(render_pose, expected))

    def test_missing_mycpp_reports_build_command(self) -> None:
        """mycpp 未编译时应尽早提示专用 build task，避免后续空对象异常。"""

        with self.assertRaisesRegex(RuntimeError, "pixi run _build-fp"):
            FoundationPoseObjectEstimator._ensure_mycpp_available(SimpleNamespace(mycpp=None))


if __name__ == "__main__":
    unittest.main()

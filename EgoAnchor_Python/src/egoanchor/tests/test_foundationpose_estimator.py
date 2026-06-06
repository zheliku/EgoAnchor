"""FoundationPose 适配器轻量契约测试。"""

from __future__ import annotations

import unittest

import numpy as np

from egoanchor.algorithms.foundationpose_estimator import FoundationPoseObjectEstimator


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

        expected = pose @ np.linalg.inv(estimator.to_origin)
        self.assertTrue(np.allclose(render_pose, expected))


if __name__ == "__main__":
    unittest.main()

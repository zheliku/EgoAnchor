"""PoseResult 诊断字段映射测试。"""

from __future__ import annotations

import unittest

from egoanchor.perception import PoseObservation
from egoanchor.runtime import PoseResultFactory


class PoseResultFactoryTest(unittest.TestCase):
    """验证 perception observation 到共享 PoseResult 的字段契约。"""

    def test_build_carries_reliability_and_mask_depth_diagnostics(self) -> None:
        """PoseResult 必须携带 Unity anchor policy 所需的可靠性诊断。"""

        observation = PoseObservation(
            has_pose=True,
            phase="TRACK",
            frame_id=42,
            pose_matrix_cv_camera=(
                1.0,
                0.0,
                0.0,
                0.1,
                0.0,
                1.0,
                0.0,
                0.2,
                0.0,
                0.0,
                1.0,
                0.3,
                0.0,
                0.0,
                0.0,
                1.0,
            ),
            pose_source="TRACK",
            depth_valid_ratio=0.55,
            depth_valid_in_mask=0.37,
            mask_area_ratio=0.08,
            reliability_score=0.72,
            reliability_flags=("track_pose", "depth_medium"),
        )

        result = PoseResultFactory().build(observation)

        self.assertTrue(result.has_pose)
        self.assertAlmostEqual(result.reliability_score, 0.72, places=5)
        self.assertEqual(list(result.reliability_flags), ["track_pose", "depth_medium"])
        self.assertAlmostEqual(result.depth_valid_in_mask, 0.37, places=5)
        self.assertAlmostEqual(result.mask_area_ratio, 0.08, places=5)
        self.assertEqual(result.pose_source, "TRACK")


if __name__ == "__main__":
    unittest.main()

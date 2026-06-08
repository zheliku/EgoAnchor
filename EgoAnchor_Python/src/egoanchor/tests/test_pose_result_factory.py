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
            score_phase=1.0,
            score_reprojection=0.64,
            score_depth=0.91,
            score_jump=0.95,
            score_mask=1.0,
            score_reject=1.0,
            score_confidence=0.8,
            track_reprojection=0.64,
            render_quality_mask_iou=0.72,
            render_quality_depth_inlier=0.58,
            render_quality_depth_alignment=0.61,
            render_quality_area_ratio_score=0.44,
            render_quality_render_visible_ratio=0.83,
            render_quality_observed_visible_ratio=0.91,
            render_quality_depth_residual_m=0.018,
            render_quality_render_area_px=512,
            render_quality_expected=True,
            render_quality_status="valid",
            reliability_score=0.72,
            reliability_flags=("track_pose", "depth_medium"),
        )

        result = PoseResultFactory().build(observation)

        self.assertTrue(result.has_pose)
        self.assertAlmostEqual(result.reliability_score, 0.72, places=5)
        self.assertEqual(list(result.reliability_flags), ["track_pose", "depth_medium"])
        self.assertAlmostEqual(result.depth_valid_in_mask, 0.37, places=5)
        self.assertAlmostEqual(result.mask_area_ratio, 0.08, places=5)
        self.assertAlmostEqual(result.score_phase, 1.0, places=5)
        self.assertAlmostEqual(result.score_reprojection, 0.64, places=5)
        self.assertAlmostEqual(result.score_depth, 0.91, places=5)
        self.assertAlmostEqual(result.score_jump, 0.95, places=5)
        self.assertAlmostEqual(result.score_mask, 1.0, places=5)
        self.assertAlmostEqual(result.score_reject, 1.0, places=5)
        self.assertAlmostEqual(result.score_confidence, 0.8, places=5)
        self.assertAlmostEqual(result.track_reprojection, 0.64, places=5)
        self.assertAlmostEqual(result.render_quality_mask_iou, 0.72, places=5)
        self.assertAlmostEqual(result.render_quality_depth_inlier, 0.58, places=5)
        self.assertAlmostEqual(result.render_quality_depth_alignment, 0.61, places=5)
        self.assertAlmostEqual(result.render_quality_area_ratio_score, 0.44, places=5)
        self.assertAlmostEqual(result.render_quality_render_visible_ratio, 0.83, places=5)
        self.assertAlmostEqual(result.render_quality_observed_visible_ratio, 0.91, places=5)
        self.assertAlmostEqual(result.render_quality_depth_residual_m, 0.018, places=5)
        self.assertEqual(result.render_quality_render_area_px, 512)
        self.assertTrue(result.render_quality_expected)
        self.assertEqual(result.render_quality_status, "valid")
        self.assertEqual(result.pose_source, "TRACK")


if __name__ == "__main__":
    unittest.main()

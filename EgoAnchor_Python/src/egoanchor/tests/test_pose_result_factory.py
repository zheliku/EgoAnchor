"""PoseResult 诊断字段映射测试。"""

from __future__ import annotations

import unittest

import numpy as np

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
            server_receive_mono_ms=1234.5,
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
            color_reprojection=0.64,
            render_quality_mask_iou=0.72,
            render_quality_depth_inlier=0.58,
            render_quality_depth_alignment=0.61,
            render_quality_area_ratio_score=0.44,
            render_quality_render_visible_ratio=0.83,
            render_quality_observed_visible_ratio=0.91,
            render_quality_depth_residual_m=0.018,
            render_quality_render_area_px=512,
            render_quality_evaluated=True,
            render_quality_status="valid",
            reliability_score=0.72,
            reliability_flags=("track_pose", "depth_medium"),
        )

        result = PoseResultFactory().build(observation)

        self.assertTrue(result.has_pose)
        self.assertAlmostEqual(result.server_receive_mono_ms, 1234.5)
        self.assertGreater(result.server_publish_mono_ms, result.server_receive_mono_ms)
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
        self.assertAlmostEqual(result.color_reprojection, 0.64, places=5)
        self.assertAlmostEqual(result.render_quality_mask_iou, 0.72, places=5)
        self.assertAlmostEqual(result.render_quality_depth_inlier, 0.58, places=5)
        self.assertAlmostEqual(result.render_quality_depth_alignment, 0.61, places=5)
        self.assertAlmostEqual(result.render_quality_area_ratio_score, 0.44, places=5)
        self.assertAlmostEqual(result.render_quality_render_visible_ratio, 0.83, places=5)
        self.assertAlmostEqual(result.render_quality_observed_visible_ratio, 0.91, places=5)
        self.assertAlmostEqual(result.render_quality_depth_residual_m, 0.018, places=5)
        self.assertEqual(result.render_quality_render_area_px, 512)
        self.assertTrue(result.render_quality_evaluated)
        self.assertEqual(result.render_quality_status, "valid")
        self.assertEqual(result.pose_source, "TRACK")

    def test_build_accepts_numpy_pose_matrix(self) -> None:
        """PoseResultFactory 不应因 ndarray truth-value 规则丢弃有效 pose。"""

        pose = np.eye(4, dtype=np.float32)
        pose[0, 3] = 0.4
        observation = PoseObservation(
            has_pose=True,
            phase="TRACK",
            frame_id=7,
            pose_matrix_cv_camera=pose,  # type: ignore[arg-type]
            pose_source="TRACK",
        )

        result = PoseResultFactory().build(observation)

        self.assertTrue(result.has_pose)
        self.assertEqual(result.header.frame_id, 7)
        self.assertEqual(len(result.pose_matrix_cv_camera.values), 16)
        self.assertAlmostEqual(result.pose_matrix_cv_camera.values[3], 0.4, places=5)

    def test_build_rejects_non_finite_pose_matrix(self) -> None:
        """NaN/Inf pose matrix 不应通过协议发送给 Unity。"""

        pose = np.eye(4, dtype=np.float32)
        pose[0, 3] = np.nan
        observation = PoseObservation(
            has_pose=True,
            phase="TRACK",
            frame_id=8,
            pose_matrix_cv_camera=pose,  # type: ignore[arg-type]
            pose_source="TRACK",
            reliability_flags=("non_finite_pose",),
        )

        result = PoseResultFactory().build(observation)

        self.assertFalse(result.has_pose)
        self.assertEqual(result.last_error.code, "INVALID_POSE_MATRIX")
        self.assertEqual(list(result.pose_matrix_cv_camera.values), [])
        self.assertEqual(result.header.frame_id, 8)

    def test_build_rejects_unparseable_pose_matrix_without_raising(self) -> None:
        """矩阵元素不可转 float 时应返回 no-pose error，而不是让发布链路抛异常。"""

        observation = PoseObservation(
            has_pose=True,
            phase="TRACK",
            frame_id=9,
            pose_matrix_cv_camera=(1.0, 0.0, object(), 0.0),
            pose_source="TRACK",
        )

        result = PoseResultFactory().build(observation)

        self.assertFalse(result.has_pose)
        self.assertEqual(result.last_error.code, "INVALID_POSE_MATRIX")

    def test_build_replaces_non_finite_diagnostics_with_defaults(self) -> None:
        """诊断浮点进入 Protobuf 前应有限化，避免 Unity 收到 NaN/Inf。"""

        observation = PoseObservation(
            has_pose=False,
            phase="WAIT_DETECT",
            frame_id=10,
            reliability_score=float("nan"),
            color_reprojection=float("inf"),
            server_receive_mono_ms=float("inf"),
            total_ms=float("nan"),
            render_quality_render_area_px=float("nan"),  # type: ignore[arg-type]
        )

        result = PoseResultFactory().build(observation)

        self.assertFalse(result.has_pose)
        self.assertEqual(result.reliability_score, 0.0)
        self.assertEqual(result.color_reprojection, -1.0)
        self.assertEqual(result.server_receive_mono_ms, 0.0)
        self.assertEqual(result.timing.total_ms, 0.0)
        self.assertEqual(result.render_quality_render_area_px, 0)


if __name__ == "__main__":
    unittest.main()

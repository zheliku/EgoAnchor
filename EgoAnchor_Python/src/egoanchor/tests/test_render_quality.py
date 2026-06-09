"""渲染重投影与深度对齐纯数学评分测试。"""

from __future__ import annotations

import unittest

import cv2
import numpy as np

from egoanchor.reliability import DepthAlignmentChecker, RenderQualityChecker, ReprojectionChecker


class ReprojectionCheckerTest(unittest.TestCase):
    """验证重投影 checker 只处理可见交集区域的颜色相似度。"""

    def test_zncc_invariant_to_affine_lighting(self) -> None:
        """LAB ZNCC 应对整体亮度和颜色通道仿射变化保持高分。"""

        mask = np.ones((6, 6), dtype=bool)
        render_lab = self._lab_pattern()
        observed_lab = np.clip(render_lab.astype(np.float32) * np.array([1.15, 0.75, 1.10]) + np.array([12.0, 20.0, -8.0]), 0, 255)
        render_rgb = cv2.cvtColor(render_lab.astype(np.uint8), cv2.COLOR_LAB2RGB)
        observed_rgb = cv2.cvtColor(observed_lab.astype(np.uint8), cv2.COLOR_LAB2RGB)

        result = ReprojectionChecker._score_from_maps(
            render_rgb,
            observed_rgb,
            mask,
            mask,
            min_render_area_px=1,
        )

        self.assertTrue(result.valid)
        self.assertAlmostEqual(result.mask_iou, 1.0)
        self.assertGreater(result.color_similarity, 0.85)
        self.assertGreater(result.score, 0.85)
        self.assertTrue(result.color_valid)

    def test_zncc_flat_object_neutral(self) -> None:
        """整块纯色没有方差信号时，ZNCC 返回中性 0.5 且标记 color_valid=False 供评分层排除。"""

        mask = np.ones((4, 4), dtype=bool)
        render_rgb = np.full((4, 4, 3), (210, 80, 60), dtype=np.uint8)
        observed_rgb = np.full((4, 4, 3), (60, 210, 80), dtype=np.uint8)

        result = ReprojectionChecker._score_from_maps(
            render_rgb,
            observed_rgb,
            mask,
            mask,
            min_render_area_px=1,
        )

        self.assertTrue(result.valid)
        self.assertFalse(result.color_valid)
        self.assertAlmostEqual(result.color_similarity, 0.5)
        self.assertAlmostEqual(result.score, 0.5)

    def test_zncc_wrong_object_low(self) -> None:
        """空间颜色结构相反的错物体应得到低 ZNCC 分。"""

        mask = np.ones((6, 6), dtype=bool)
        render_lab = self._lab_pattern()
        observed_lab = np.flip(render_lab, axis=(0, 1))
        render_rgb = cv2.cvtColor(render_lab.astype(np.uint8), cv2.COLOR_LAB2RGB)
        observed_rgb = cv2.cvtColor(observed_lab.astype(np.uint8), cv2.COLOR_LAB2RGB)

        result = ReprojectionChecker._score_from_maps(
            render_rgb,
            observed_rgb,
            mask,
            mask,
            min_render_area_px=1,
        )

        self.assertTrue(result.valid)
        self.assertLess(result.color_similarity, 0.35)

    def test_reprojection_does_not_mix_area_into_color_score(self) -> None:
        """交集区域无方差时，面积比例仍只进 area_ratio_score 诊断。"""

        render_mask = np.array([[1, 1], [1, 1]], dtype=bool)
        observed_mask = np.array([[1, 0], [0, 0]], dtype=bool)
        rgb = np.full((2, 2, 3), 180, dtype=np.uint8)

        result = ReprojectionChecker._score_from_maps(
            rgb,
            rgb,
            render_mask,
            observed_mask,
            min_render_area_px=1,
        )

        self.assertTrue(result.valid)
        self.assertAlmostEqual(result.score, 0.5)
        self.assertAlmostEqual(result.area_ratio_score, 0.25)
        self.assertAlmostEqual(result.mask_iou, 0.25)
        self.assertAlmostEqual(result.render_visible_ratio, 0.25)
        self.assertAlmostEqual(result.observed_visible_ratio, 1.0)

    def test_no_overlap_keeps_color_penalty(self) -> None:
        """投影与观测完全不重叠是坏 pose 信号：score 必须为 0 且 color_valid 保持有效以保留惩罚。"""

        render_mask = np.array([[1, 1], [0, 0]], dtype=bool)
        observed_mask = np.array([[0, 0], [1, 1]], dtype=bool)
        rgb = np.full((2, 2, 3), 180, dtype=np.uint8)

        result = ReprojectionChecker._score_from_maps(
            rgb,
            rgb,
            render_mask,
            observed_mask,
            min_render_area_px=1,
        )

        self.assertTrue(result.valid)
        self.assertTrue(result.color_valid)
        self.assertAlmostEqual(result.score, 0.0)
        self.assertAlmostEqual(result.mask_iou, 0.0)

    @staticmethod
    def _lab_pattern() -> np.ndarray:
        """构造带空间结构的 LAB 色块，避免纯色 ZNCC 无方差。"""

        yy, xx = np.indices((6, 6), dtype=np.float32)
        return np.dstack(
            [
                60.0 + xx * 18.0 + yy * 4.0,
                105.0 + yy * 8.0,
                95.0 + xx * 6.0,
            ]
        ).astype(np.uint8)


class DepthAlignmentCheckerTest(unittest.TestCase):
    """验证 depth alignment 只处理渲染深度与观测深度残差。"""

    def test_depth_alignment_uses_adaptive_threshold(self) -> None:
        """距离越远，深度 inlier 阈值应按比例放宽。"""

        render_depth = np.ones((2, 2), dtype=np.float32)
        observed_depth = np.array([[1.004, 1.012], [1.018, 1.03]], dtype=np.float32)
        intersection = np.ones((2, 2), dtype=bool)

        close = DepthAlignmentChecker._score_from_maps(
            render_depth,
            observed_depth,
            intersection,
            pose_distance_m=0.24,
            depth_coverage=0.8,
            distance_ratio=0.02,
            min_inlier_thresh_m=0.005,
            min_depth_coverage=0.10,
        )
        far = DepthAlignmentChecker._score_from_maps(
            render_depth,
            observed_depth,
            intersection,
            pose_distance_m=1.0,
            depth_coverage=0.8,
            distance_ratio=0.02,
            min_inlier_thresh_m=0.005,
            min_depth_coverage=0.10,
        )

        self.assertTrue(close.valid)
        self.assertTrue(far.valid)
        self.assertAlmostEqual(close.inlier_thresh_m, 0.005)
        self.assertAlmostEqual(far.inlier_thresh_m, 0.02)
        self.assertLess(close.inlier_ratio, far.inlier_ratio)
        self.assertLess(close.score, far.score)

    def test_depth_coverage_insufficient_returns_neutral_score(self) -> None:
        """深度覆盖不足是输入信号不足，不应伪装成满分或强故障。"""

        depth = np.ones((2, 2), dtype=np.float32)
        result = DepthAlignmentChecker._score_from_maps(
            depth,
            depth,
            np.ones((2, 2), dtype=bool),
            pose_distance_m=0.5,
            depth_coverage=0.04,
            distance_ratio=0.02,
            min_inlier_thresh_m=0.005,
            min_depth_coverage=0.10,
        )

        self.assertFalse(result.valid)
        self.assertEqual(result.status, "depth_coverage_insufficient")
        self.assertAlmostEqual(result.score, 0.5)


class RenderQualityCheckerTest(unittest.TestCase):
    """验证一次渲染后会拆出重投影和深度两个质量信号。"""

    def test_render_quality_keeps_reprojection_and_depth_separate(self) -> None:
        """同一次渲染结果应分别产出 reprojection_score 与 depth_alignment_score。"""

        class FakeEstimator:
            cam_k = np.eye(3, dtype=np.float64)

            def render_color_depth_mask(self, pose_cv_camera, output_size, cam_k=None):
                lab = np.array(
                    [
                        [[80, 110, 100], [120, 115, 106], [150, 125, 112], [180, 135, 118]],
                        [[92, 118, 103], [132, 122, 109], [158, 130, 115], [188, 138, 121]],
                        [[104, 126, 106], [140, 130, 112], [168, 136, 118], [196, 142, 124]],
                        [[116, 134, 109], [148, 138, 115], [176, 144, 121], [204, 148, 127]],
                    ],
                    dtype=np.uint8,
                )
                color = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
                depth = np.ones((4, 4), dtype=np.float32)
                mask = np.ones((4, 4), dtype=bool)
                return color, depth, mask

        checker = RenderQualityChecker(downscale=1, min_render_area_px=1)
        pose = np.eye(4, dtype=np.float32)
        pose[2, 3] = 1.0
        observed_rgb, _, _ = FakeEstimator().render_color_depth_mask(pose, (4, 4))
        observed_depth = np.full((4, 4), 1.03, dtype=np.float32)
        observed_mask = np.ones((4, 4), dtype=bool)

        result = checker.evaluate(
            FakeEstimator(),
            pose,
            observed_rgb,
            observed_mask,
            observed_depth,
            depth_coverage=0.8,
        )

        self.assertTrue(result.reprojection_valid)
        self.assertAlmostEqual(result.reprojection_score, 1.0)
        self.assertLess(result.depth_alignment_score, result.reprojection_score)
        self.assertAlmostEqual(result.mask_iou, 1.0)
        self.assertGreater(result.depth_median_residual_m, 0.0)


if __name__ == "__main__":
    unittest.main()

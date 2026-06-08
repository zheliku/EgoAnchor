"""渲染重投影与深度对齐纯数学评分测试。"""

from __future__ import annotations

import unittest

import cv2
import numpy as np

from egoanchor.reliability import DepthAlignmentChecker, RenderQualityChecker, ReprojectionChecker


class ReprojectionCheckerTest(unittest.TestCase):
    """验证重投影 checker 只处理可见交集区域的颜色相似度。"""

    def test_reprojection_scores_lab_color_in_overlap(self) -> None:
        """mask 完全重合但颜色明显不同时，重投影分应被颜色项拉低。"""

        render_mask = np.array([[1, 1], [1, 1]], dtype=bool)
        observed_mask = np.array([[1, 1], [1, 1]], dtype=bool)
        render_rgb = np.full((2, 2, 3), (220, 40, 40), dtype=np.uint8)
        observed_same = render_rgb.copy()
        observed_diff = np.full((2, 2, 3), (40, 220, 40), dtype=np.uint8)

        same = ReprojectionChecker._score_from_maps(
            render_rgb,
            observed_same,
            render_mask,
            observed_mask,
            min_render_area_px=1,
        )
        diff = ReprojectionChecker._score_from_maps(
            render_rgb,
            observed_diff,
            render_mask,
            observed_mask,
            min_render_area_px=1,
        )

        self.assertTrue(same.valid)
        self.assertAlmostEqual(same.mask_iou, 1.0)
        self.assertAlmostEqual(same.color_similarity, 1.0)
        self.assertAlmostEqual(same.score, 1.0)
        self.assertTrue(diff.valid)
        self.assertAlmostEqual(diff.mask_iou, 1.0)
        self.assertLess(diff.color_similarity, same.color_similarity)
        self.assertLess(diff.score, same.score)

    def test_reprojection_does_not_mix_area_into_color_score(self) -> None:
        """交集区域颜色一致时，面积比例只进 area_ratio_score 诊断。"""

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
        self.assertAlmostEqual(result.score, 1.0)
        self.assertAlmostEqual(result.area_ratio_score, 0.25)
        self.assertAlmostEqual(result.mask_iou, 0.25)
        self.assertAlmostEqual(result.render_visible_ratio, 0.25)
        self.assertAlmostEqual(result.observed_visible_ratio, 1.0)

    def test_brightness_gain_invariant_stays_high(self) -> None:
        """同色相、仅整体亮度增益不同的渲染与真实图应保持高颜色分。"""

        mask = np.ones((4, 4), dtype=bool)
        render_rgb = np.full((4, 4, 3), 90, dtype=np.uint8)
        observed_rgb = np.full((4, 4, 3), 210, dtype=np.uint8)

        result = ReprojectionChecker._score_from_maps(
            render_rgb,
            observed_rgb,
            mask,
            mask,
            min_render_area_px=1,
        )

        self.assertGreater(result.color_similarity, 0.85)

    def test_double_peak_brightness_invariant(self) -> None:
        """黑白双峰物体中白面增亮、黑面不变时，颜色分应保持稳定。"""

        mask = np.ones((4, 4), dtype=bool)
        render_rgb = np.full((4, 4, 3), 40, dtype=np.uint8)
        render_rgb[:, 2:] = 190
        observed_rgb = np.full((4, 4, 3), 40, dtype=np.uint8)
        observed_rgb[:, 2:] = 235

        result = ReprojectionChecker._score_from_maps(
            render_rgb,
            observed_rgb,
            mask,
            mask,
            min_render_area_px=1,
        )

        self.assertGreater(result.color_similarity, 0.8)

    def test_white_balance_offset_invariant(self) -> None:
        """观测图整体暖偏时，应通过 a/b 中心化消除白平衡误罚。"""

        mask = np.ones((4, 4), dtype=bool)
        render_rgb = np.full((4, 4, 3), 150, dtype=np.uint8)
        render_lab = cv2.cvtColor(render_rgb, cv2.COLOR_RGB2LAB).astype(np.int16)
        observed_lab = render_lab.copy()
        observed_lab[..., 1] += 15
        observed_lab[..., 2] += 15
        observed_rgb = cv2.cvtColor(np.clip(observed_lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB)

        result = ReprojectionChecker._score_from_maps(
            render_rgb,
            observed_rgb,
            mask,
            mask,
            min_render_area_px=1,
        )

        self.assertGreater(result.color_similarity, 0.85)

    def test_wrong_object_hue_scores_low(self) -> None:
        """色相明显不同的错物体仍应被显著降分。"""

        mask = np.ones((4, 4), dtype=bool)
        render_rgb = np.full((4, 4, 3), (40, 40, 220), dtype=np.uint8)
        observed_rgb = np.full((4, 4, 3), (220, 120, 40), dtype=np.uint8)

        result = ReprojectionChecker._score_from_maps(
            render_rgb,
            observed_rgb,
            mask,
            mask,
            min_render_area_px=1,
        )

        self.assertLess(result.color_similarity, 0.4)


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
                color = np.full((2, 2, 3), 160, dtype=np.uint8)
                depth = np.ones((2, 2), dtype=np.float32)
                mask = np.ones((2, 2), dtype=bool)
                return color, depth, mask

        checker = RenderQualityChecker(downscale=1, min_render_area_px=1)
        pose = np.eye(4, dtype=np.float32)
        pose[2, 3] = 1.0
        observed_rgb = np.full((2, 2, 3), 160, dtype=np.uint8)
        observed_depth = np.full((2, 2), 1.03, dtype=np.float32)
        observed_mask = np.ones((2, 2), dtype=bool)

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

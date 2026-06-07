"""渲染一致性纯数学评分测试。"""

from __future__ import annotations

import unittest

import numpy as np

from egoanchor.reliability import RenderConsistencyChecker


class RenderConsistencyCheckerTest(unittest.TestCase):
    """验证渲染 mask/depth 与观测 mask/depth 的一致性分数。"""

    def test_score_from_maps_handles_overlap_extremes(self) -> None:
        """完全重叠应接近 1，不相交应为 0。"""

        render_mask = np.array([[1, 1], [0, 0]], dtype=bool)
        observed_mask = np.array([[1, 1], [0, 0]], dtype=bool)
        render_depth = np.array([[1.0, 1.0], [0.0, 0.0]], dtype=np.float32)
        observed_depth = np.array([[1.0, 1.0], [0.0, 0.0]], dtype=np.float32)

        full = RenderConsistencyChecker._score_from_maps(
            render_mask,
            observed_mask,
            render_depth,
            observed_depth,
            iou_weight=0.6,
            depth_weight=0.4,
            depth_inlier_thresh_m=0.02,
            min_render_area_px=1,
        )
        empty = RenderConsistencyChecker._score_from_maps(
            render_mask,
            np.array([[0, 0], [1, 1]], dtype=bool),
            render_depth,
            observed_depth,
            iou_weight=0.6,
            depth_weight=0.4,
            depth_inlier_thresh_m=0.02,
            min_render_area_px=1,
        )

        self.assertTrue(full.valid)
        self.assertAlmostEqual(full.mask_iou, 1.0)
        self.assertAlmostEqual(full.depth_inlier_ratio, 1.0)
        self.assertAlmostEqual(full.consistency, 1.0)
        self.assertTrue(empty.valid)
        self.assertAlmostEqual(empty.mask_iou, 0.0)
        self.assertAlmostEqual(empty.depth_inlier_ratio, 0.0)
        self.assertAlmostEqual(empty.consistency, 0.0)

    def test_score_from_maps_combines_iou_and_depth_inlier(self) -> None:
        """部分重叠时综合分应同时包含 IoU 与深度 inlier。"""

        render_mask = np.array([[1, 1], [0, 0]], dtype=bool)
        observed_mask = np.array([[1, 0], [1, 0]], dtype=bool)
        render_depth = np.array([[1.0, 1.0], [0.0, 0.0]], dtype=np.float32)
        observed_depth = np.array([[1.01, 0.0], [1.0, 0.0]], dtype=np.float32)

        result = RenderConsistencyChecker._score_from_maps(
            render_mask,
            observed_mask,
            render_depth,
            observed_depth,
            iou_weight=0.6,
            depth_weight=0.4,
            depth_inlier_thresh_m=0.02,
            min_render_area_px=1,
        )

        self.assertTrue(result.valid)
        self.assertAlmostEqual(result.mask_iou, 1.0 / 3.0)
        self.assertAlmostEqual(result.render_visible_ratio, 0.5)
        self.assertAlmostEqual(result.depth_inlier_ratio, 1.0)
        self.assertLess(result.consistency, 0.5)

    def test_score_from_maps_penalizes_occluded_observed_subset(self) -> None:
        """观测 mask 明显小于渲染 mask 时，即使深度匹配也应明显降分。"""

        render_mask = np.array([[1, 1], [1, 1]], dtype=bool)
        observed_mask = np.array([[1, 0], [1, 0]], dtype=bool)
        depth = np.ones((2, 2), dtype=np.float32)

        result = RenderConsistencyChecker._score_from_maps(
            render_mask,
            observed_mask,
            depth,
            depth,
            iou_weight=0.6,
            depth_weight=0.4,
            depth_inlier_thresh_m=0.02,
            min_render_area_px=1,
        )

        self.assertTrue(result.valid)
        self.assertAlmostEqual(result.render_visible_ratio, 0.5)
        self.assertAlmostEqual(result.depth_inlier_ratio, 1.0)
        self.assertLess(result.consistency, 0.7)
        self.assertEqual(result.render_mask.shape, render_mask.shape)
        self.assertEqual(result.observed_mask.shape, observed_mask.shape)

    def test_score_from_maps_caps_high_mask_score_when_depth_disagrees(self) -> None:
        """mask 完全贴合但表面深度明显不对时，不能继续给高一致性分。"""

        render_mask = np.array([[1, 1], [1, 1]], dtype=bool)
        observed_mask = np.array([[1, 1], [1, 1]], dtype=bool)
        render_depth = np.ones((2, 2), dtype=np.float32)
        observed_depth = np.full((2, 2), 1.12, dtype=np.float32)

        result = RenderConsistencyChecker._score_from_maps(
            render_mask,
            observed_mask,
            render_depth,
            observed_depth,
            iou_weight=0.6,
            depth_weight=0.4,
            depth_inlier_thresh_m=0.02,
            min_render_area_px=1,
        )

        self.assertTrue(result.valid)
        self.assertAlmostEqual(result.mask_iou, 1.0)
        self.assertAlmostEqual(result.observed_visible_ratio, 1.0)
        self.assertAlmostEqual(result.render_visible_ratio, 1.0)
        self.assertAlmostEqual(result.depth_inlier_ratio, 0.0)
        self.assertLess(result.depth_alignment_score, 0.2)
        self.assertLess(result.consistency, 0.35)

    def test_score_from_maps_marks_tiny_render_invalid(self) -> None:
        """渲染前景太小时只提供无效信号，避免触发重注册。"""

        render_mask = np.array([[1, 0], [0, 0]], dtype=bool)
        observed_mask = np.array([[1, 0], [0, 0]], dtype=bool)
        depth = np.array([[1.0, 0.0], [0.0, 0.0]], dtype=np.float32)

        result = RenderConsistencyChecker._score_from_maps(
            render_mask,
            observed_mask,
            depth,
            depth,
            iou_weight=0.6,
            depth_weight=0.4,
            depth_inlier_thresh_m=0.02,
            min_render_area_px=2,
        )

        self.assertFalse(result.valid)
        self.assertEqual(result.render_area_px, 1)


if __name__ == "__main__":
    unittest.main()

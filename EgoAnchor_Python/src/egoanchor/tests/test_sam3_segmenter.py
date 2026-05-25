"""SAM3 分割适配器轻量测试。"""

from __future__ import annotations

import unittest

import numpy as np

from egoanchor.algorithms.sam3_segmenter import disable_sam3_position_precompute, select_best_sam3_mask


class Sam3MaskSelectionTest(unittest.TestCase):
    """验证 SAM3 多实例输出会被收敛成单目标 mask。"""

    def test_selects_highest_score_non_empty_mask(self) -> None:
        """应选择最高置信度的非空 mask，而不是合并多个目标。"""

        masks = np.zeros((3, 4, 5), dtype=np.float32)
        masks[0, 0:2, 0:2] = 1.0
        masks[1, :, :] = 0.0
        masks[2, 1:4, 2:5] = 1.0
        scores = np.array([0.6, 0.95, 0.8], dtype=np.float32)

        mask_bw, selected_index, area_ratio = select_best_sam3_mask(masks, scores, (4, 5))

        self.assertEqual(selected_index, 2)
        self.assertEqual(mask_bw.dtype, np.uint8)
        self.assertEqual(mask_bw.shape, (4, 5))
        self.assertEqual(int(np.count_nonzero(mask_bw)), 9)
        self.assertAlmostEqual(area_ratio, 9 / 20)

    def test_empty_or_filtered_masks_return_empty_result(self) -> None:
        """没有有效 mask 时应返回空 mask 和 -1 下标。"""

        masks = np.zeros((2, 3, 4), dtype=np.float32)
        scores = np.array([0.7, 0.8], dtype=np.float32)

        mask_bw, selected_index, area_ratio = select_best_sam3_mask(masks, scores, (3, 4))

        self.assertEqual(selected_index, -1)
        self.assertEqual(int(np.count_nonzero(mask_bw)), 0)
        self.assertEqual(area_ratio, 0.0)


class Sam3PositionPrecomputeTest(unittest.TestCase):
    """验证可跳过 SAM3 初始化阶段的位置编码预计算慢路径。"""

    def test_disable_position_precompute_ignores_requested_resolution(self) -> None:
        """禁用后应把官方 1008 预计算请求改成按需计算。"""

        calls: list[int | None] = []

        class FakeBuilder:
            @staticmethod
            def _create_position_encoding(precompute_resolution: int | None = None) -> tuple[int | None]:
                calls.append(precompute_resolution)
                return (precompute_resolution,)

        disable_sam3_position_precompute(FakeBuilder)
        result = FakeBuilder._create_position_encoding(precompute_resolution=1008)

        self.assertEqual(result, (None,))
        self.assertEqual(calls, [None])


if __name__ == "__main__":
    unittest.main()

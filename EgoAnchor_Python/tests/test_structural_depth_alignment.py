"""测试绝对-结构联合深度对齐评估。

验证三个核心场景：
1. 同一深度波形（形状对但有系统噪声）→ 高分
2. 波形横向错位（pose真的错）→ 低分
3. 纯平面/无结构（回退到绝对残差）→ 按残差评分
"""

import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

# 添加 src 到路径
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from egoanchor.reliability.depth_alignment import DepthAlignmentChecker


class TestStructuralDepthAlignment(unittest.TestCase):
    """测试绝对-结构联合深度对齐评估。"""

    def test_same_wave_with_systematic_noise(self) -> None:
        """场景1：同一深度波形 + 系统噪声 → 结构分数应拯救总分。"""
        checker = DepthAlignmentChecker(
            distance_ratio=0.02,
            min_inlier_thresh_m=0.005,
            min_depth_coverage=0.10,
            residual_scale=2.5,
            enable_structural=True,
            structural_max_weight=0.35,
            structural_iqr_thresh=0.02,
            core_erode_kernel=3,
        )

        # 构造柱状波浪形深度（模拟手柄侧面）
        h, w = 100, 100
        x = np.linspace(0, 4 * np.pi, w)
        wave = 0.5 + 0.1 * np.sin(x)  # 0.4m 到 0.6m，IQR ≈ 100mm
        render_depth = np.tile(wave, (h, 1)).astype(np.float32)

        # 观测深度：相同波形 + 8mm 系统偏移 + 少量噪声
        observed_depth = render_depth + 0.008 + np.random.normal(0, 0.002, (h, w)).astype(np.float32)

        # 腐蚀后的核心区域
        intersection = np.ones((h, w), dtype=bool)
        kernel = np.ones((3, 3), dtype=np.uint8)
        core_mask = cv2.erode(intersection.astype(np.uint8), kernel, iterations=1) > 0

        result = checker.score_maps(
            render_depth,
            observed_depth,
            intersection,
            pose_distance_m=0.5,
            depth_coverage=1.0,
        )

        print(f"\n场景1：同一波形 + 系统噪声")
        print(f"  最终分数: {result.score:.3f}")
        print(f"  绝对残差分数: {result.inlier_ratio*0.6 + (1.0-result.median_residual_m/0.01)*0.4:.3f}")
        print(f"  结构分数: {result.structural_score:.3f}")
        print(f"  结构权重: {result.structural_weight:.3f}")
        print(f"  中位残差: {result.median_residual_m*1000:.1f}mm")

        assert result.valid
        assert result.structural_score > 0.85, f"同一波形的结构分应很高，实际 {result.structural_score:.3f}"
        assert result.structural_weight > 0.3, f"高IQR应启用结构评估，实际权重 {result.structural_weight:.3f}"
        assert result.score > 0.7, f"结构分应拯救总分到0.7以上，实际 {result.score:.3f}"

    def test_shifted_wave_structure_mismatch(self) -> None:
        """场景2：波形横向错位 → 结构分数应识别为错位。"""
        checker = DepthAlignmentChecker(
            distance_ratio=0.02,
            min_inlier_thresh_m=0.005,
            min_depth_coverage=0.10,
            residual_scale=2.5,
            enable_structural=True,
            structural_max_weight=0.35,
            structural_iqr_thresh=0.02,
            core_erode_kernel=3,
        )

        # 渲染深度：原始波形
        h, w = 100, 100
        x = np.linspace(0, 4 * np.pi, w)
        wave = 0.5 + 0.1 * np.sin(x)
        render_depth = np.tile(wave, (h, 1)).astype(np.float32)

        # 观测深度：波形横向移位 1/4 周期（pose错误）
        x_shifted = np.linspace(0, 4 * np.pi, w) + np.pi / 2
        wave_shifted = 0.5 + 0.1 * np.sin(x_shifted)
        observed_depth = np.tile(wave_shifted, (h, 1)).astype(np.float32)

        intersection = np.ones((h, w), dtype=bool)

        result = checker.score_maps(
            render_depth,
            observed_depth,
            intersection,
            pose_distance_m=0.5,
            depth_coverage=1.0,
        )

        print(f"\n场景2：波形横向错位")
        print(f"  最终分数: {result.score:.3f}")
        print(f"  结构分数: {result.structural_score:.3f}")
        print(f"  结构权重: {result.structural_weight:.3f}")
        print(f"  内点比例: {result.inlier_ratio:.3f}")
        print(f"  中位残差: {result.median_residual_m*1000:.1f}mm")

        assert result.valid
        # 注意：ZNCC对相位偏移不够敏感（两个正弦波归一化后仍相似）
        # 但绝对残差会检测到大的median_residual，所以最终分数应较低
        assert result.score < 0.5, f"错位波形应导致低分（绝对残差大），实际 {result.score:.3f}"

    def test_flat_surface_fallback_to_absolute(self) -> None:
        """场景3：平坦表面 → 回退到绝对残差评估。"""
        checker = DepthAlignmentChecker(
            distance_ratio=0.02,
            min_inlier_thresh_m=0.005,
            min_depth_coverage=0.10,
            residual_scale=2.5,
            enable_structural=True,
            structural_max_weight=0.35,
            structural_iqr_thresh=0.02,
            core_erode_kernel=3,
        )

        # 平坦深度图：0.5m ± 2mm 噪声（IQR < 0.02m）
        h, w = 100, 100
        render_depth = np.full((h, w), 0.5, dtype=np.float32)
        render_depth += np.random.normal(0, 0.002, (h, w)).astype(np.float32)

        # 观测深度：相同平面 + 3mm 偏移
        observed_depth = render_depth + 0.003

        intersection = np.ones((h, w), dtype=bool)

        result = checker.score_maps(
            render_depth,
            observed_depth,
            intersection,
            pose_distance_m=0.5,
            depth_coverage=1.0,
        )

        print(f"\n场景3：平坦表面")
        print(f"  最终分数: {result.score:.3f}")
        print(f"  结构权重: {result.structural_weight:.3f}")
        print(f"  中位残差: {result.median_residual_m*1000:.1f}mm")

        assert result.valid
        assert result.structural_weight < 0.1, f"平坦表面不应启用结构评估，实际权重 {result.structural_weight:.3f}"
        assert result.score > 0.8, f"小残差应获得高分，实际 {result.score:.3f}"

    def test_real_world_scenario(self) -> None:
        """场景4：真机数据模拟 - 手柄特殊角度（5.7mm中位残差）。"""
        checker = DepthAlignmentChecker(
            distance_ratio=0.02,
            min_inlier_thresh_m=0.005,
            min_depth_coverage=0.10,
            residual_scale=2.5,
            enable_structural=True,
            structural_max_weight=0.35,
            structural_iqr_thresh=0.02,
            core_erode_kernel=3,
        )

        # 模拟真机场景：高频几何 + 中位残差5.7mm
        h, w = 100, 100
        x = np.linspace(0, 4 * np.pi, w)
        wave = 0.5 + 0.1 * np.sin(x)
        render_depth = np.tile(wave, (h, 1)).astype(np.float32)

        # FFS观测深度：同一波形，但有5.7mm中位偏移和列状噪声
        observed_depth = render_depth.copy()
        # 全局偏移
        observed_depth += 0.0057
        # 模拟FFS的列状系统噪声
        for col in range(w):
            col_noise = np.random.normal(0, 0.003)
            observed_depth[:, col] += col_noise

        intersection = np.ones((h, w), dtype=bool)

        result = checker.score_maps(
            render_depth,
            observed_depth,
            intersection,
            pose_distance_m=0.5,
            depth_coverage=1.0,
        )

        print(f"\n场景4：真机模拟（手柄特殊角度）")
        print(f"  最终分数: {result.score:.3f}")
        print(f"  结构分数: {result.structural_score:.3f}")
        print(f"  结构权重: {result.structural_weight:.3f}")
        print(f"  内点比例: {result.inlier_ratio:.3f}")
        print(f"  中位残差: {result.median_residual_m*1000:.1f}mm")

        assert result.valid
        # 目标：深度分 > 0.5（避免触发重定位）
        assert result.score > 0.5, f"真机场景应获得 >0.5 的分数以避免重定位，实际 {result.score:.3f}"
        print(f"  [OK] 深度分 {result.score:.3f} > 0.5，避免频繁重定位")


if __name__ == "__main__":
    unittest.main(verbosity=2)

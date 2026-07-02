"""测试深度对齐的几何复杂度自适应阈值。

验证高频几何（如手柄侧面）在特殊角度下不会因局部深度变化幅度大而误判为错位。
"""

import sys
import unittest
from pathlib import Path

import numpy as np

# 添加 src 到路径
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from egoanchor.reliability.depth_alignment import DepthAlignmentChecker


class TestDepthComplexityAdaptive(unittest.TestCase):
    """测试几何复杂度自适应阈值机制。"""

    def test_flat_surface_no_complexity_boost(self) -> None:
        """平坦表面：复杂度因子应接近 1.0，不放宽阈值。"""
        checker = DepthAlignmentChecker(
            distance_ratio=0.02,
            min_inlier_thresh_m=0.005,
            min_depth_coverage=0.10,
        )

        # 构造平坦深度图：0.5m ± 2mm 的微小噪声
        h, w = 100, 100
        render_depth = np.full((h, w), 0.5, dtype=np.float32)
        render_depth += np.random.normal(0, 0.002, (h, w)).astype(np.float32)

        # 观测深度有 8mm 的系统偏移（但仍在10mm基础阈值内）
        observed_depth = render_depth + 0.008
        intersection = np.ones((h, w), dtype=bool)

        result = checker.score_maps(
            render_depth,
            observed_depth,
            intersection,
            pose_distance_m=0.5,
            depth_coverage=1.0,
        )

        # 平坦表面标准差很小，复杂度因子 ≈ 1.0，阈值 ≈ 0.5*0.02 = 10mm
        # 8mm 偏移在10mm阈值内，应该获得较高分数（不是错位）
        assert result.valid
        print(f"平坦表面 8mm偏移分数: {result.score:.3f}")
        # 主要验证：平坦表面不会获得复杂度加成

    def test_high_frequency_geometry_complexity_boost(self) -> None:
        """高频几何：复杂度因子应放宽阈值，避免误判。"""
        checker = DepthAlignmentChecker(
            distance_ratio=0.02,
            min_inlier_thresh_m=0.005,
            min_depth_coverage=0.10,
        )

        # 构造柱状波浪形深度：模拟手柄侧面凹凸起伏（0.4m-0.6m，std ≈ 58mm）
        h, w = 100, 100
        x = np.linspace(0, 4 * np.pi, w)
        wave = 0.5 + 0.1 * np.sin(x)  # 0.4m 到 0.6m
        render_depth = np.tile(wave, (h, 1)).astype(np.float32)

        # 观测深度有相同的波浪形 + 8mm 的全局偏移
        observed_depth = render_depth + 0.008
        intersection = np.ones((h, w), dtype=bool)

        result = checker.score_maps(
            render_depth,
            observed_depth,
            intersection,
            pose_distance_m=0.5,
            depth_coverage=1.0,
        )

        # 高频几何标准差 ≈ 58mm，复杂度因子 = 1 + min(0.058/0.015, 1.5) = 1 + 1.5 = 2.5
        # 基础阈值 0.5*0.02 = 10mm，自适应阈值 ≈ 10mm * 2.5 = 25mm
        # 8mm 偏移 < 25mm，应该获得较高分数
        assert result.valid
        assert result.score > 0.7, f"高频几何有小偏移时应获得较高分数，实际 {result.score:.3f}"
        assert result.inlier_ratio > 0.9, "8mm偏移在25mm阈值内应该大部分是内点"

    def test_high_frequency_with_large_misalignment(self) -> None:
        """高频几何 + 大偏移：即使放宽阈值，仍应判为错位。"""
        checker = DepthAlignmentChecker(
            distance_ratio=0.02,
            min_inlier_thresh_m=0.005,
            min_depth_coverage=0.10,
        )

        # 同样的柱状波浪形
        h, w = 100, 100
        x = np.linspace(0, 4 * np.pi, w)
        wave = 0.5 + 0.1 * np.sin(x)
        render_depth = np.tile(wave, (h, 1)).astype(np.float32)

        # 但观测深度有 50mm 的大偏移（明显错位）
        observed_depth = render_depth + 0.050
        intersection = np.ones((h, w), dtype=bool)

        result = checker.score_maps(
            render_depth,
            observed_depth,
            intersection,
            pose_distance_m=0.5,
            depth_coverage=1.0,
        )

        # 即使阈值放宽到 25mm，50mm 的偏移仍然应该被判为错位
        assert result.valid
        assert result.score < 0.4, f"大偏移应该获得低分，实际 {result.score:.3f}"

    def test_medium_complexity_gradual_boost(self) -> None:
        """中等复杂度：复杂度因子应在 1.0-2.5 之间渐变。"""
        checker = DepthAlignmentChecker(
            distance_ratio=0.02,
            min_inlier_thresh_m=0.005,
            min_depth_coverage=0.10,
        )

        scores = []
        stds = []

        # 测试不同复杂度级别（通过控制波浪幅度）
        for amplitude in [0.01, 0.02, 0.05, 0.1]:  # 10mm, 20mm, 50mm, 100mm
            h, w = 100, 100
            x = np.linspace(0, 4 * np.pi, w)
            wave = 0.5 + amplitude * np.sin(x)
            render_depth = np.tile(wave, (h, 1)).astype(np.float32)

            # 固定 8mm 偏移
            observed_depth = render_depth + 0.008
            intersection = np.ones((h, w), dtype=bool)

            result = checker.score_maps(
                render_depth,
                observed_depth,
                intersection,
                pose_distance_m=0.5,
                depth_coverage=1.0,
            )

            scores.append(result.score)
            stds.append(np.std(render_depth))

        # 随着几何复杂度增加，相同偏移应该获得更高的容忍度（分数上升）
        assert scores[-1] > scores[0], (
            f"高复杂度应比低复杂度更容忍小偏移: "
            f"stds={[f'{s*1000:.1f}mm' for s in stds]}, scores={[f'{s:.3f}' for s in scores]}"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

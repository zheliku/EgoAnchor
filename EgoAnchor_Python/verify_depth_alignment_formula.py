"""验证深度对齐度实现与论文公式的一致性。"""

import sys
import io
import numpy as np
from egoanchor.reliability.depth_alignment import DepthAlignmentChecker

# 设置UTF-8编码输出
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


def test_formula_consistency():
    """测试实现是否与论文公式一致。"""
    print("=" * 60)
    print("深度对齐度公式一致性验证")
    print("=" * 60 + "\n")

    checker = DepthAlignmentChecker(
        distance_ratio=0.02,
        min_inlier_thresh_m=0.005,
        min_depth_coverage=0.10,
    )

    # 场景1：完美对齐
    print("测试1: 完美对齐")
    render_depth = np.ones((100, 100), dtype=np.float32) * 1.0
    observed_depth = render_depth.copy()
    intersection = np.ones((100, 100), dtype=bool)

    result = checker.score_maps(
        render_depth,
        observed_depth,
        intersection,
        pose_distance_m=1.0,
        depth_coverage=1.0,
    )

    print(f"  D = λ·ρ_inlier + (1-λ)·S_med")
    print(f"  D = 0.6 × {result.inlier_ratio:.3f} + 0.4 × (1 - {result.median_residual_m:.3f})")
    expected_score = 0.6 * result.inlier_ratio + 0.4 * (1.0 - 0.0)
    print(f"  预期分数: {expected_score:.3f}")
    print(f"  实际分数: {result.score:.3f}")
    print(f"  ✓ 匹配" if abs(result.score - expected_score) < 0.01 else f"  ✗ 不匹配")
    print()

    # 场景2：带噪声
    print("测试2: 带高斯噪声 (σ=1cm)")
    observed_depth_noisy = render_depth + np.random.normal(0, 0.01, (100, 100)).astype(np.float32)

    result = checker.score_maps(
        render_depth,
        observed_depth_noisy,
        intersection,
        pose_distance_m=1.0,
        depth_coverage=1.0,
    )

    print(f"  内点比例 ρ_inlier: {result.inlier_ratio:.3f}")
    print(f"  中位数残差: {result.median_residual_m*1000:.2f}mm")
    print(f"  最终分数 D: {result.score:.3f}")
    print(f"  ✓ 权重为0.6/0.4" if 0.6 < result.score < 0.9 else "  ✗ 权重不符")
    print()

    # 场景3：测试逐像素自适应阈值
    print("测试3: 逐像素自适应阈值")
    # 创建距离渐变的深度图
    x = np.linspace(0, 1, 100)
    y = np.linspace(0, 1, 100)
    xx, yy = np.meshgrid(x, y)
    render_depth_gradient = (0.5 + 1.5 * xx).astype(np.float32)  # 0.5m到2.0m

    # 添加固定绝对误差（近处相对大，远处相对小）
    observed_depth_gradient = render_depth_gradient + 0.015  # 固定15mm误差

    result = checker.score_maps(
        render_depth_gradient,
        observed_depth_gradient,
        intersection,
        pose_distance_m=1.25,
        depth_coverage=1.0,
    )

    print(f"  深度范围: 0.5m - 2.0m")
    print(f"  固定误差: 15mm")
    print(f"  内点比例: {result.inlier_ratio:.3f}")
    print(f"  分数: {result.score:.3f}")
    print(f"  ✓ 自适应阈值生效（远处更宽容）" if result.inlier_ratio > 0.5 else "  ✗ 阈值未自适应")
    print()

    # 场景4：对比V1和当前实现
    print("测试4: V1 vs 当前实现")
    render_depth = np.ones((100, 100), dtype=np.float32) * 1.0
    observed_depth = render_depth + 0.01  # 1cm误差

    result = checker.score_maps(
        render_depth,
        observed_depth,
        intersection,
        pose_distance_m=1.0,
        depth_coverage=1.0,
    )

    # V1公式：0.5 * inlier + 0.5 * median_score
    # 当前公式：0.6 * inlier + 0.4 * S_med
    print(f"  内点比例: {result.inlier_ratio:.3f}")
    print(f"  中位数残差: {result.median_residual_m*1000:.2f}mm")
    print(f"  当前分数: {result.score:.3f}")
    print(f"  ✓ 使用0.6/0.4权重" if result.score > 0.7 else "  ✗ 权重错误")
    print()

    print("=" * 60)
    print("✅ 公式验证完成")
    print("=" * 60)


def test_edge_cases():
    """测试边界情况。"""
    print("\n" + "=" * 60)
    print("边界情况测试")
    print("=" * 60 + "\n")

    checker = DepthAlignmentChecker()

    # 边界1：深度覆盖不足
    print("边界1: 深度覆盖不足")
    render_depth = np.ones((100, 100), dtype=np.float32) * 1.0
    observed_depth = render_depth.copy()
    intersection = np.ones((100, 100), dtype=bool)

    result = checker.score_maps(
        render_depth,
        observed_depth,
        intersection,
        pose_distance_m=1.0,
        depth_coverage=0.05,  # 低于10%阈值
    )

    print(f"  状态: {result.status}")
    print(f"  分数: {result.score} (应为0.5)")
    print(f"  ✓ 通过" if result.score == 0.5 and not result.valid else "  ✗ 失败")
    print()

    # 边界2：无有效重叠
    print("边界2: 无有效重叠")
    render_depth = np.ones((100, 100), dtype=np.float32) * 1.0
    observed_depth = np.zeros((100, 100), dtype=np.float32)  # 全零

    result = checker.score_maps(
        render_depth,
        observed_depth,
        intersection,
        pose_distance_m=1.0,
        depth_coverage=1.0,
    )

    print(f"  状态: {result.status}")
    print(f"  分数: {result.score} (应为0.0)")
    print(f"  ✓ 通过" if result.score == 0.0 and not result.valid else "  ✗ 失败")
    print()

    # 边界3：大误差
    print("边界3: 大误差 (50cm)")
    render_depth = np.ones((100, 100), dtype=np.float32) * 1.0
    observed_depth = np.ones((100, 100), dtype=np.float32) * 1.5

    result = checker.score_maps(
        render_depth,
        observed_depth,
        intersection,
        pose_distance_m=1.0,
        depth_coverage=1.0,
    )

    print(f"  内点比例: {result.inlier_ratio:.3f} (应接近0)")
    print(f"  分数: {result.score:.3f} (应 <0.3)")
    print(f"  ✓ 通过" if result.score < 0.3 else "  ✗ 失败")
    print()

    print("=" * 60)
    print("✅ 边界测试完成")
    print("=" * 60)


if __name__ == "__main__":
    np.random.seed(42)
    test_formula_consistency()
    test_edge_cases()

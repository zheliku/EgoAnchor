"""OpenCV pose HUD 诊断文本测试。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from egoanchor.diagnostics import colorize_depth, draw_pose_hud as draw_hud, make_score_debug_view, tile_pose_depth_dashboard
from egoanchor.perception import FrameDiagnostics, PoseObservation


class DebugViewTest(unittest.TestCase):
    """验证 HUD 暴露真机联调需要直接看的关键分数。"""

    def test_hud_prints_depth_alignment_score(self) -> None:
        """HUD 应显示 depth 对齐子分，避免只看到最终 reliability score。"""

        image = np.zeros((120, 320, 3), dtype=np.uint8)
        diagnostics = FrameDiagnostics(depth_valid_in_mask=0.2, depth_valid_ratio=0.5)
        observation = PoseObservation(
            has_pose=True,
            phase="TRACK",
            pose_source="TRACK",
            reliability_score=0.73,
            score_depth=0.65,
        )
        texts: list[str] = []

        with patch("egoanchor.diagnostics.debug_view.cv2.putText") as put_text:
            put_text.side_effect = lambda img, text, *args, **kwargs: texts.append(str(text)) or img
            draw_hud(image, observation, diagnostics)

        self.assertTrue(any("depthScore=0.65" in text for text in texts))

    def test_score_debug_view_prints_score_breakdown(self) -> None:
        """独立评分窗口应显示所有评分子分和渲染质量分解。"""

        diagnostics = FrameDiagnostics(
            score_reprojection=0.42,
            score_depth=0.65,
            score_mask=0.9,
            color_reprojection=0.42,
            render_quality_mask_iou=0.3,
            render_quality_area_ratio_score=0.25,
            render_quality_render_visible_ratio=0.5,
            render_quality_observed_visible_ratio=0.6,
            render_quality_depth_inlier=0.7,
            render_quality_depth_alignment=0.65,
            render_quality_status="render_invalid",
            render_quality_render_area_px=0,
            render_quality_ms=4.0,
        )
        observation = PoseObservation(
            has_pose=True,
            phase="TRACK",
            pose_source="TRACK",
            reliability_score=0.2,
            reliability_flags=("reprojection_low",),
        )
        texts: list[str] = []

        with patch("egoanchor.diagnostics.debug_view.cv2.putText") as put_text:
            put_text.side_effect = lambda img, text, *args, **kwargs: texts.append(str(text)) or img
            view = make_score_debug_view(diagnostics, observation, width=640, height=360)

        self.assertEqual(view.shape[:2], (360, 640))
        self.assertTrue(any("score=0.20" in text for text in texts))
        self.assertTrue(any("reproj=0.42" in text for text in texts))
        self.assertTrue(any("depth=0.65" in text for text in texts))
        self.assertTrue(any("mask=0.90" in text for text in texts))
        self.assertTrue(any("track_reproj=0.42" in text for text in texts))
        self.assertTrue(any("area=0.25" in text for text in texts))
        self.assertTrue(any("renderCov=0.50" in text for text in texts))
        self.assertTrue(any("obsCov=0.60" in text for text in texts))
        self.assertTrue(any("depthIn=0.70" in text for text in texts))
        self.assertTrue(any("depthAlign=0.65" in text for text in texts))
        self.assertTrue(any("status=render_invalid" in text for text in texts))

    def test_score_debug_view_reserves_top_banner(self) -> None:
        """评分窗口顶部应保留文本横幅，不让 2x3 诊断矩阵压住文字。"""

        mask = np.ones((16, 16), dtype=bool)
        diagnostics = FrameDiagnostics(
            render_quality_observed_rgb=np.full((16, 16, 3), 255, dtype=np.uint8),
            render_quality_render_rgb=np.full((16, 16, 3), 180, dtype=np.uint8),
            render_quality_render_mask=mask,
            render_quality_observed_mask=mask,
            render_quality_render_depth=np.ones((16, 16), dtype=np.float32),
            render_quality_observed_depth=np.ones((16, 16), dtype=np.float32),
        )

        view = make_score_debug_view(diagnostics, None, width=640, height=360)
        expected_banner_h = 4 * 24 + 7 * 20 + 36

        self.assertLess(float(np.mean(view[5])), 20.0)
        self.assertLess(float(np.mean(view[expected_banner_h - 6])), 20.0)
        self.assertGreater(float(np.mean(view[expected_banner_h + 8])), 20.0)

    def test_pose_dashboard_reserves_top_banner(self) -> None:
        """主调试窗口顶部应保留 HUD 横幅，四宫格画面从横幅下方开始。"""

        left = np.full((109, 160, 3), 255, dtype=np.uint8)
        right = np.full((109, 160, 3), 255, dtype=np.uint8)
        diagnostics = FrameDiagnostics(left_bgr=left, right_bgr=right)

        view = tile_pose_depth_dashboard(diagnostics, None, width=640, height=360)
        expected_banner_h = 5 * 24 + 22
        row_h = (360 - expected_banner_h) // 2
        label_y = expected_banner_h + row_h - 30

        self.assertEqual(view.shape[:2], (360, 640))
        self.assertLess(float(np.mean(view[5])), 20.0)
        self.assertLess(float(np.mean(view[expected_banner_h - 6])), 20.0)
        self.assertGreater(float(np.mean(view[expected_banner_h + 8, 160])), 200.0)
        self.assertLess(float(np.mean(view[label_y + 2, :320])), 50.0)

    def test_pose_dashboard_depth_panel_preserves_depth_color_inside_mask(self) -> None:
        """主窗口 depth 面板只画细轮廓，不用半透明填充覆盖物体内部深度颜色。"""

        depth = np.ones((79, 320), dtype=np.float32)
        mask = np.ones((79, 320), dtype=bool)
        diagnostics = FrameDiagnostics(depth=depth, mask=mask)

        view = tile_pose_depth_dashboard(diagnostics, None, width=640, height=360, min_depth=0.1, max_depth=5.0)
        expected_depth = colorize_depth(depth, min_depth=0.1, max_depth=5.0)
        expected_banner_h = 5 * 24 + 22
        row_h = (360 - expected_banner_h) // 2
        sample_y = expected_banner_h + row_h + 40
        sample_x = 160

        np.testing.assert_allclose(view[sample_y, sample_x], expected_depth[40, sample_x], atol=1)

    def test_score_debug_view_has_color_and_depth_matrix(self) -> None:
        """评分窗口应包含颜色投影（Color projection）与深度对比的 2x3 矩阵。"""

        mask = np.ones((24, 24), dtype=bool)
        yy, xx = np.indices((24, 24), dtype=np.uint8)
        render_rgb = np.dstack([40 + xx * 4, 80 + yy * 3, 180 - xx * 2]).astype(np.uint8)
        observed_rgb = np.clip(render_rgb.astype(np.float32) * 0.75 + 35.0, 0, 255).astype(np.uint8)
        diagnostics = FrameDiagnostics(
            render_quality_observed_rgb=observed_rgb,
            render_quality_render_rgb=render_rgb,
            render_quality_render_mask=mask,
            render_quality_observed_mask=mask,
            render_quality_render_depth=np.ones((24, 24), dtype=np.float32),
            render_quality_observed_depth=np.ones((24, 24), dtype=np.float32),
        )
        texts: list[str] = []

        with patch("egoanchor.diagnostics.debug_view.cv2.putText") as put_text:
            put_text.side_effect = lambda img, text, *args, **kwargs: texts.append(str(text)) or img
            view = make_score_debug_view(diagnostics, None, width=720, height=480)

        self.assertEqual(view.shape[:2], (480, 720))
        self.assertTrue(any("RGB: green render / cyan Cutie" in text for text in texts))
        self.assertTrue(any("render RGB on checkerboard" in text for text in texts))
        self.assertTrue(any("LAB residual on RGB ZNCC=" in text for text in texts))
        self.assertTrue(any("render projected depth" in text for text in texts))
        self.assertTrue(any("FFS observed depth" in text for text in texts))
        self.assertTrue(any("depth diff:" in text for text in texts))
        self.assertTrue(any("low" == text for text in texts))
        self.assertTrue(any("high" == text for text in texts))
        self.assertTrue(any(text.startswith("p95=") for text in texts))

    def test_score_debug_depth_row_matches_rgb_order(self) -> None:
        """深度行应与 RGB 行一样按观测、渲染、残差从左到右排列。"""

        mask = np.ones((24, 24), dtype=bool)
        diagnostics = FrameDiagnostics(
            render_quality_observed_rgb=np.full((24, 24, 3), 255, dtype=np.uint8),
            render_quality_render_rgb=np.full((24, 24, 3), 180, dtype=np.uint8),
            render_quality_render_mask=mask,
            render_quality_observed_mask=mask,
            render_quality_render_depth=np.ones((24, 24), dtype=np.float32),
            render_quality_observed_depth=np.ones((24, 24), dtype=np.float32),
        )
        labels: list[tuple[str, tuple[int, int]]] = []

        with patch("egoanchor.diagnostics.debug_view.cv2.putText") as put_text:
            def record_label(img: np.ndarray, text: str, org: tuple[int, int], *args, **kwargs) -> np.ndarray:
                labels.append((str(text), org))
                return img

            put_text.side_effect = record_label
            make_score_debug_view(diagnostics, None, width=720, height=480)

        ffs_x = min(org[0] for text, org in labels if "FFS observed depth" in text)
        render_x = min(org[0] for text, org in labels if "render projected depth" in text)
        residual_x = min(org[0] for text, org in labels if "depth diff:" in text)

        self.assertLess(ffs_x, render_x)
        self.assertLess(render_x, residual_x)

    def test_score_debug_view_keeps_panel_labels_below_images(self) -> None:
        """评分窗口 panel 标签应位于独立标签条，不写进图像内容。"""

        mask = np.ones((24, 24), dtype=bool)
        diagnostics = FrameDiagnostics(
            render_quality_observed_rgb=np.full((24, 24, 3), (32, 96, 220), dtype=np.uint8),
            render_quality_render_rgb=np.full((24, 24, 3), (160, 80, 30), dtype=np.uint8),
            render_quality_render_mask=mask,
            render_quality_observed_mask=mask,
            render_quality_render_depth=np.ones((24, 24), dtype=np.float32),
            render_quality_observed_depth=np.full((24, 24), 1.02, dtype=np.float32),
        )

        view = make_score_debug_view(diagnostics, None, width=720, height=480)
        banner_h = 4 * 24 + 7 * 20 + 36
        row_h = (480 - banner_h) // 2
        label_y = banner_h + row_h - 30

        self.assertGreater(float(np.mean(view[banner_h + 12, 40:200])), 30.0)
        self.assertLess(float(np.mean(view[label_y + 2, :240])), 50.0)

    def test_score_debug_view_preserves_observed_rgb_inside_mask(self) -> None:
        """观测 RGB 面板只画轮廓，不用半透明高亮遮住物体原始颜色。"""

        observed_rgb = np.full((24, 24, 3), (32, 96, 220), dtype=np.uint8)
        render_rgb = np.full((24, 24, 3), (160, 80, 30), dtype=np.uint8)
        mask = np.ones((24, 24), dtype=bool)
        diagnostics = FrameDiagnostics(
            render_quality_observed_rgb=observed_rgb,
            render_quality_render_rgb=render_rgb,
            render_quality_render_mask=mask,
            render_quality_observed_mask=mask,
            render_quality_render_depth=np.ones((24, 24), dtype=np.float32),
            render_quality_observed_depth=np.ones((24, 24), dtype=np.float32),
        )

        view = make_score_debug_view(diagnostics, None, width=720, height=480)
        banner_h = 4 * 24 + 7 * 20 + 36
        sample_bgr = view[banner_h + 36, 120]

        np.testing.assert_allclose(sample_bgr, np.array([220, 96, 32], dtype=np.uint8), atol=3)

    def test_score_debug_view_default_size_matches_config(self) -> None:
        """评分窗口工具默认尺寸应与 defaults.toml 中的 960x800 保持一致。"""

        view = make_score_debug_view(FrameDiagnostics(), None)

        self.assertEqual(view.shape[:2], (800, 960))


if __name__ == "__main__":
    unittest.main()

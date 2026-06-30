"""分割后端配置契约测试。"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from egoanchor.config import load_config
from egoanchor.perception import normalize_segmenter_type, should_show_mask_snapshot


class SegmenterConfigTest(unittest.TestCase):
    """验证 YOLOE 默认值和 SAM3 可切换配置。"""

    def test_default_segmenter_remains_yoloe26(self) -> None:
        """默认 mask 后端必须保持 YOLOE-26，避免改变主线行为。"""

        cfg = load_config()

        self.assertEqual(cfg.module.segmenter.type, "yoloe26")
        self.assertEqual(cfg.module.segmenter.confidence_threshold, 0.2)
        self.assertFalse(hasattr(cfg.module.yoloe, "conf"))
        self.assertFalse(hasattr(cfg.module.sam3, "confidence_threshold"))
        self.assertFalse(hasattr(cfg.module.sam3, "mask_threshold"))
        self.assertEqual(cfg.module.sam3.repo_path, "sam3")
        self.assertEqual(cfg.module.sam3.checkpoint_path, "sam3/assets/sam3_ckpt/sam3.pt")
        self.assertTrue(cfg.module.sam3.async_segmentation)

    def test_render_quality_defaults_do_not_include_auto_re_register_knobs(self) -> None:
        """渲染质量检测只输出评分信号，不保留 Python 内部重注册开关。"""

        cfg = load_config()

        self.assertTrue(cfg.reliability.render_quality.enabled)
        self.assertFalse(hasattr(cfg.reliability.render_quality, "mode"))
        self.assertFalse(hasattr(cfg.reliability.render_quality, "re_register_threshold"))
        self.assertFalse(hasattr(cfg.reliability.render_quality, "min_track_frames"))
        self.assertEqual(cfg.reliability.render_quality.warmup_frames, 3)
        self.assertFalse(hasattr(cfg.reliability.render_quality, "geometry_weight"))
        self.assertFalse(hasattr(cfg.reliability.render_quality, "color_weight"))
        self.assertAlmostEqual(cfg.reliability.render_quality.depth_distance_ratio, 0.02)
        self.assertAlmostEqual(cfg.reliability.render_quality.depth_min_inlier_thresh_m, 0.005)
        self.assertAlmostEqual(cfg.reliability.render_quality.depth_min_coverage, 0.10)
        self.assertAlmostEqual(cfg.reliability.render_quality.color_l_weight, 0.3)
        self.assertFalse(hasattr(cfg.reliability.render_quality, "color_inlier_thresh"))

    def test_pose_score_defaults_match_geometric_core_plan(self) -> None:
        """Pose score 默认配置应使用几何合取核和有界调制参数。"""

        cfg = load_config()

        self.assertAlmostEqual(cfg.reliability.pose_score.geo_floor, 0.05)
        self.assertAlmostEqual(cfg.reliability.pose_score.reproj_weight, 0.2)
        self.assertAlmostEqual(cfg.reliability.pose_score.depth_weight, 0.8)

    def test_pose_debug_uses_score_window_without_stereo_window(self) -> None:
        """pose debug 应使用独立评分窗口，不再配置旧 stereo 辅助窗口。"""

        cfg = load_config()

        self.assertEqual(cfg.demo.pose.score_window_name, "EgoAnchor Score Debug")
        self.assertEqual(cfg.demo.pose.score_window_width, 960)
        self.assertEqual(cfg.demo.pose.score_window_height, 800)
        self.assertAlmostEqual(cfg.demo.pose.debug_window_max_fps, 20.0)
        self.assertAlmostEqual(cfg.demo.pose.score_window_max_fps, 6.0)
        self.assertFalse(hasattr(cfg.demo.pose, "stereo_window_name"))

    def test_headless_tracking_disables_mask_snapshot_window(self) -> None:
        """关闭 tracking window 时也应关闭 register mask snapshot 弹窗。"""

        self.assertFalse(
            should_show_mask_snapshot(
                configured_snapshot=True,
                tracking_window_enabled=False,
            )
        )
        self.assertTrue(
            should_show_mask_snapshot(
                configured_snapshot=True,
                tracking_window_enabled=True,
            )
        )
        self.assertFalse(
            should_show_mask_snapshot(
                configured_snapshot=False,
                tracking_window_enabled=True,
            )
        )

    def test_normalize_segmenter_type_accepts_sam3(self) -> None:
        """工厂层应接受 sam3 作为显式分割后端。"""

        self.assertEqual(normalize_segmenter_type(SimpleNamespace(type="SAM3")), "sam3")

    def test_normalize_segmenter_type_rejects_unknown_backend(self) -> None:
        """未知分割后端应尽早报错。"""

        with self.assertRaisesRegex(ValueError, "未知分割后端"):
            normalize_segmenter_type(SimpleNamespace(type="unknown"))


if __name__ == "__main__":
    unittest.main()

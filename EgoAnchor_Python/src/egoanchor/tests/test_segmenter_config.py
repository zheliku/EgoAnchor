"""分割后端配置契约测试。"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from egoanchor.config import load_config
from egoanchor.perception.pipeline_factory import normalize_segmenter_type


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

    def test_render_consistency_defaults_are_shadow_mode(self) -> None:
        """渲染一致性默认必须关闭，开启后也先只做 score_only。"""

        cfg = load_config()

        self.assertFalse(cfg.reliability.consistency.enabled)
        self.assertEqual(cfg.reliability.consistency.mode, "score_only")
        self.assertAlmostEqual(cfg.reliability.consistency.re_register_threshold, 0.35)
        self.assertEqual(cfg.reliability.consistency.min_track_frames, 2)
        self.assertEqual(cfg.reliability.consistency.warmup_frames, 3)

    def test_normalize_segmenter_type_accepts_sam3(self) -> None:
        """工厂层应接受 sam3 作为显式分割后端。"""

        self.assertEqual(normalize_segmenter_type(SimpleNamespace(type="SAM3")), "sam3")

    def test_normalize_segmenter_type_rejects_unknown_backend(self) -> None:
        """未知分割后端应尽早报错。"""

        with self.assertRaisesRegex(ValueError, "未知分割后端"):
            normalize_segmenter_type(SimpleNamespace(type="unknown"))


if __name__ == "__main__":
    unittest.main()

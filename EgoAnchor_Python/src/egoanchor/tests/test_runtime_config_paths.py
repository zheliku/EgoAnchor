"""运行配置路径契约测试。"""

from __future__ import annotations

import unittest

from egoanchor.config import load_config
from egoanchor.protocol import SubjectRegistry, default_subjects_path


class RuntimeConfigPathsTest(unittest.TestCase):
    """验证默认配置不会回退到旧权重目录。"""

    def test_yoloe_weights_live_under_unified_weights_dir(self) -> None:
        """YOLOE-26 与 mobileclip2 默认权重都应从 EgoAnchor_Python/weights 读取。"""

        cfg = load_config()

        self.assertEqual(cfg.module.yoloe.model_path, "weights/yoloe-26l-seg.pt")
        self.assertEqual(cfg.module.yoloe.mobileclip2_path, "weights/mobileclip2_b.ts")

    def test_foundationpose_logging_is_disabled_by_default(self) -> None:
        """FoundationPose 默认不应向 console 输出第三方库内部日志。"""

        cfg = load_config()

        self.assertFalse(cfg.module.foundationpose.enable_logging)
        self.assertFalse(hasattr(cfg.module.foundationpose, "suppress_output"))

    def test_subjects_path_is_python_project_local(self) -> None:
        """默认 subject registry 应随 EgoAnchor_Python 一起迁移，不依赖父级仓库。"""

        cfg = load_config()

        self.assertFalse(hasattr(cfg.paths, "repo_root"))
        self.assertTrue(cfg.paths.subjects_path.is_file())
        self.assertTrue(cfg.paths.subjects_path.is_relative_to(cfg.paths.python_root))
        self.assertEqual(default_subjects_path(), cfg.paths.subjects_path)
        registry = SubjectRegistry.load(cfg.paths.subjects_path)
        self.assertIn("egoanchor.v1.pose.result", registry.names())
        default_registry = SubjectRegistry.load()
        self.assertIn("egoanchor.v1.pose.result", default_registry.names())


if __name__ == "__main__":
    unittest.main()

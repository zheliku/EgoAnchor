"""对象配置覆盖契约测试。"""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from egoanchor.config import load_config, load_object_override


class ConfigOverlayTest(unittest.TestCase):
    """验证 defaults、对象配置和临时覆盖文件的合并顺序。"""

    def test_load_object_override_applies_object_fields(self) -> None:
        """按对象名加载时，应覆盖 prompt、mesh、对称和可选分割后端。"""

        cfg = load_config(object_name="earphone")

        self.assertEqual(cfg.module.segmenter.type, "sam3")
        self.assertEqual(cfg.module.segmenter.prompt, "small pink rounded rectangular earphone charging case")
        self.assertEqual(cfg.module.foundationpose.mesh_path, "data/model/earphone.glb")
        self.assertEqual(cfg.module.foundationpose.symmetry_mode, "none")

    def test_config_file_can_override_selected_object(self) -> None:
        """显式 TOML 覆盖文件应在对象配置之后应用，便于临时调参。"""

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "override.toml"
            config_path.write_text(
                textwrap.dedent(
                    """
                    [module.segmenter]
                    prompt = "temporary prompt"
                    """
                ).strip(),
                encoding="utf-8",
            )

            cfg = load_config(config_path, object_name="blue_mouse")

        self.assertEqual(cfg.module.segmenter.prompt, "temporary prompt")
        self.assertEqual(cfg.module.foundationpose.mesh_path, "data/model/blue_mouse.glb")

    def test_unknown_object_name_fails_fast(self) -> None:
        """未知对象名应立即报错，避免悄悄退回默认 cube。"""

        with self.assertRaisesRegex(KeyError, "未知对象配置"):
            load_object_override("missing_object")


if __name__ == "__main__":
    unittest.main()

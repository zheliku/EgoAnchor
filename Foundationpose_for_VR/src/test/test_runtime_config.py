from __future__ import annotations

import tempfile
import unittest
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
    sys.path.append(str(SRC_DIR))

from config.runtime_config import (
    DEFAULT_CONFIG_PATH,
    PROJECT_DIR,
    load_runtime_config,
    namespace_to_dict,
    validate_unknown_keys,
)


class RuntimeConfigTests(unittest.TestCase):
    def test_load_default_runtime_config(self) -> None:
        cfg = load_runtime_config()

        self.assertEqual(cfg.config_path, DEFAULT_CONFIG_PATH)
        self.assertEqual(cfg.server.run_stage, 4)
        self.assertEqual(cfg.network.receiver.listen_port, 15557)
        self.assertEqual(cfg.network.sender.port, 15556)
        self.assertIn(cfg.module.segmenter.type, {"sam3", "yoloe26"})
        self.assertTrue(cfg.debug.local_debug)
        self.assertTrue(cfg.debug.show_mask_snapshot)

    def test_path_fields_are_project_relative(self) -> None:
        cfg = load_runtime_config()

        self.assertEqual(cfg.project_dir, PROJECT_DIR)
        self.assertTrue(Path(cfg.pipeline.calibration.camera_cache_dir).is_absolute())
        self.assertTrue(Path(cfg.module.sam3.checkpoint_path).is_absolute())
        self.assertTrue(Path(cfg.module.foundationpose.mesh_path).is_absolute())
        self.assertEqual(
            Path(cfg.pipeline.calibration.camera_cache_dir),
            (PROJECT_DIR / "Calibration" / "cache").resolve(),
        )

    def test_unknown_key_raises_clear_error(self) -> None:
        data = namespace_to_dict(load_runtime_config())
        data.pop("config_path", None)
        data.pop("project_dir", None)
        data["module"]["sam3"]["intervel_sec"] = 1.0

        with self.assertRaisesRegex(ValueError, "Unknown config key: module.sam3.intervel_sec"):
            validate_unknown_keys(data)

    def test_missing_section_raises_clear_error(self) -> None:
        data = namespace_to_dict(load_runtime_config())
        data.pop("config_path", None)
        data.pop("project_dir", None)
        data.pop("server")

        with self.assertRaisesRegex(ValueError, "Missing config section: server"):
            validate_unknown_keys(data)

    def test_empty_optional_trt_paths_remain_empty(self) -> None:
        cfg = load_runtime_config()
        self.assertEqual(cfg.module.ffs.trt_feature_engine_path, "")
        self.assertEqual(cfg.module.ffs.trt_post_engine_path, "")
        self.assertEqual(cfg.module.foundationpose.debug_dir, "")

    def test_can_load_absolute_config_path(self) -> None:
        source = DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_path = Path(tmp_dir) / "runtime.toml"
            temp_path.write_text(source, encoding="utf-8")
            cfg = load_runtime_config(temp_path)
            self.assertEqual(cfg.config_path, temp_path)


if __name__ == "__main__":
    unittest.main()

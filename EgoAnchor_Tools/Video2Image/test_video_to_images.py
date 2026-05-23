"""video_to_images.py 的轻量行为测试。"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import cv2
import numpy as np


SCRIPT_PATH = Path(__file__).with_name("video_to_images.py")


def load_script_module():
    """按文件路径加载脚本，避免依赖项目包路径。"""

    spec = importlib.util.spec_from_file_location("video_to_images", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载脚本: {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class VideoToImagesTests(unittest.TestCase):
    """验证抽帧规则和图片写出行为。"""

    def test_should_export_frame_by_interval_and_time_range(self):
        """只导出时间范围内且满足帧间隔的帧。"""

        module = load_script_module()
        indices = module.select_frame_indices(
            frame_count=12,
            fps=6.0,
            start_seconds=0.5,
            end_seconds=1.7,
            frame_interval=3,
            target_fps=0.0,
            max_images=0,
        )

        self.assertEqual(indices, [3, 6, 9])

    def test_should_extract_images_and_manifest(self):
        """从真实短视频写出图片和 manifest。"""

        module = load_script_module()
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            video_path = tmp_path / "sample.mp4"
            output_dir = tmp_path / "frames"
            writer = cv2.VideoWriter(
                str(video_path),
                cv2.VideoWriter_fourcc(*"mp4v"),
                5.0,
                (32, 24),
            )
            self.assertTrue(writer.isOpened(), "测试视频写入器未打开")
            for i in range(5):
                frame = np.full((24, 32, 3), i * 40, dtype=np.uint8)
                writer.write(frame)
            writer.release()

            result = module.extract_video_to_images(
                video_path=video_path,
                output_dir=output_dir,
                output_prefix="frame",
                image_extension="jpg",
                jpg_quality=90,
                png_compression=3,
                start_seconds=0.0,
                end_seconds=0.0,
                frame_interval=2,
                target_fps=0.0,
                max_images=0,
                overwrite_output=True,
                write_manifest=True,
            )

            exported = sorted(output_dir.glob("*.jpg"))
            self.assertEqual(result.exported_count, 3)
            self.assertEqual([path.name for path in exported], ["frame_000000.jpg", "frame_000002.jpg", "frame_000004.jpg"])

            manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["exported_count"], 3)
            self.assertEqual([item["frame_index"] for item in manifest["frames"]], [0, 2, 4])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import time
import unittest
from pathlib import Path
from unittest import mock
import sys

import numpy as np

SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
    sys.path.append(str(SRC_DIR))

from modules.sam3_masker import AsyncSam3Masker, Sam3MaskResult, Sam3Masker


class _FakeProcessor:
    def __init__(self, model, resolution=1008, device="cpu", confidence_threshold=0.5):
        self.output = model["output"]

    def set_image(self, image, state=None):
        state = {} if state is None else state
        state["image_size"] = image.size
        return state

    def set_text_prompt(self, state, prompt):
        return dict(self.output)


class Sam3MaskerTest(unittest.TestCase):
    def _make_masker(self, output: dict) -> Sam3Masker:
        checkpoint = Path(__file__).resolve()
        with mock.patch("pathlib.Path.exists", return_value=True):
            with mock.patch("torch.cuda.is_available", return_value=False):
                with mock.patch.dict(
                    "sys.modules",
                    {
                        "sam3": mock.Mock(),
                        "sam3.model": mock.Mock(),
                        "sam3.model_builder": mock.Mock(
                            build_sam3_image_model=mock.Mock(return_value={"output": output})
                        ),
                        "sam3.model.sam3_image_processor": mock.Mock(
                            Sam3Processor=_FakeProcessor
                        ),
                    },
                ):
                    return Sam3Masker(
                        checkpoint_path=checkpoint,
                        prompt="white cube",
                        device="cpu",
                        sam3_root=checkpoint.parent,
                        max_det=1,
                    )

    def test_selects_highest_score_mask_and_draws_overlay(self) -> None:
        masks = np.zeros((2, 4, 5), dtype=np.float32)
        masks[0, 0:2, 0:2] = 1.0
        masks[1, 1:4, 2:5] = 1.0
        output = {
            "masks": masks,
            "scores": np.array([0.2, 0.9], dtype=np.float32),
            "boxes": np.array([[0, 0, 2, 2], [2, 1, 5, 4]], dtype=np.float32),
        }
        masker = self._make_masker(output)
        image = np.zeros((4, 5, 3), dtype=np.uint8)

        result = masker.infer(image, source_frame_id=7, source_timestamp_ms=123.0)

        self.assertEqual(result.det_count, 1)
        self.assertEqual(result.selected_index, 1)
        self.assertEqual(result.source_frame_id, 7)
        self.assertEqual(result.mask_bw.shape, image.shape[:2])
        self.assertEqual(result.overlay.shape, image.shape)
        self.assertGreater(result.mask_area_ratio, 0.0)
        self.assertAlmostEqual(result.score, 0.9, places=5)

    def test_empty_detection_returns_zero_mask(self) -> None:
        output = {
            "masks": np.zeros((0, 4, 5), dtype=np.float32),
            "scores": np.zeros((0,), dtype=np.float32),
            "boxes": np.zeros((0, 4), dtype=np.float32),
        }
        masker = self._make_masker(output)
        image = np.zeros((4, 5, 3), dtype=np.uint8)

        result = masker.infer(image)

        self.assertEqual(result.det_count, 0)
        self.assertEqual(result.selected_index, -1)
        self.assertEqual(int(np.count_nonzero(result.mask_bw)), 0)
        self.assertEqual(result.boxes_xyxy.shape, (0, 4))


class _SlowFakeMasker:
    def __init__(self, delay: float = 0.05):
        self.delay = delay

    def infer(self, image_bgr, source_frame_id=None, source_timestamp_ms=None):
        time.sleep(self.delay)
        return Sam3MaskResult(
            overlay=image_bgr.copy(),
            mask_bw=np.ones(image_bgr.shape[:2], dtype=np.uint8) * 255,
            det_count=1,
            infer_ms=self.delay * 1000.0,
            prompt="fake",
            selected_index=0,
            mask_area_ratio=1.0,
            score=1.0,
            source_frame_id=source_frame_id,
            source_timestamp_ms=source_timestamp_ms,
        )


class AsyncSam3MaskerTest(unittest.TestCase):
    def test_busy_submit_is_dropped_and_latest_updates(self) -> None:
        async_masker = AsyncSam3Masker(
            masker_factory=_SlowFakeMasker,
            masker_kwargs={"delay": 0.08},
            min_interval_sec=0.0,
        )
        image = np.zeros((8, 8, 3), dtype=np.uint8)
        async_masker.start()
        try:
            self.assertTrue(async_masker.submit(image, frame_id=1, timestamp_ms=10.0))
            self.assertFalse(async_masker.submit(image, frame_id=2, timestamp_ms=20.0))

            deadline = time.time() + 2.0
            latest = None
            version = 0
            while time.time() < deadline:
                latest, version = async_masker.get_latest()
                if latest is not None:
                    break
                time.sleep(0.01)

            self.assertIsNotNone(latest)
            self.assertEqual(version, 1)
            self.assertEqual(latest.source_frame_id, 1)
            stats = async_masker.get_stats()
            self.assertEqual(stats["submitted"], 1)
            self.assertEqual(stats["completed"], 1)
            self.assertGreaterEqual(stats["dropped"], 1)
        finally:
            async_masker.stop(timeout=1.0)

        self.assertFalse(async_masker._thread and async_masker._thread.is_alive())


if __name__ == "__main__":
    unittest.main()

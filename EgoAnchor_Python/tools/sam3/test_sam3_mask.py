"""SAM3 RealSense 工具轻量测试。"""

from __future__ import annotations

import time
import unittest
from pathlib import Path
import sys

import numpy as np


TOOL_DIR = Path(__file__).resolve().parent
PYTHON_DIR = TOOL_DIR.parents[1]
SRC_DIR = PYTHON_DIR / "src"
for path in (TOOL_DIR, SRC_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from egoanchor.algorithms import SegmenterResult
from sam3_mask import AsyncSam3Worker, WorkerSnapshot, compose_live_overlay


class _FakeSegmenter:
    """测试用假分割器，不加载 SAM3。"""

    def infer(self, image_bgr: np.ndarray) -> SegmenterResult:
        """返回固定 mask，并模拟一小段推理耗时。"""

        time.sleep(0.01)
        mask = np.zeros(image_bgr.shape[:2], dtype=np.uint8)
        mask[1:3, 1:3] = 255
        return SegmenterResult(
            overlay_bgr=image_bgr.copy(),
            mask_bw=mask,
            det_count=1,
            infer_ms=10.0,
            prompt=["fake"],
            selected_index=0,
            mask_area_ratio=float(np.count_nonzero(mask)) / float(mask.size),
        )


class AsyncSam3WorkerTest(unittest.TestCase):
    """验证后台推理 worker 不阻塞提交侧。"""

    def test_worker_keeps_latest_result(self) -> None:
        """提交帧后应能异步得到最新推理结果。"""

        worker = AsyncSam3Worker(_FakeSegmenter())
        worker.start()
        try:
            worker.submit(np.zeros((8, 8, 3), dtype=np.uint8), timestamp_ms=1.0)
            deadline = time.perf_counter() + 1.0
            snapshot = worker.snapshot()
            while snapshot.result is None and time.perf_counter() < deadline:
                time.sleep(0.01)
                snapshot = worker.snapshot()

            self.assertIsNotNone(snapshot.result)
            self.assertEqual(snapshot.completed, 1)
            self.assertFalse(snapshot.busy)
        finally:
            worker.stop()


class LiveOverlayTest(unittest.TestCase):
    """验证 OpenCV 主窗口始终以实时相机帧作为底图。"""

    def test_compose_live_overlay_uses_current_frame_as_background(self) -> None:
        """已有 SAM3 结果时，mask 外区域仍应来自当前 RealSense 帧。"""

        live_frame = np.full((128, 128, 3), (30, 120, 210), dtype=np.uint8)
        stale_overlay = np.zeros_like(live_frame)
        mask = np.zeros(live_frame.shape[:2], dtype=np.uint8)
        mask[80:96, 80:96] = 255
        result = SegmenterResult(
            overlay_bgr=stale_overlay,
            mask_bw=mask,
            det_count=1,
            infer_ms=25.0,
            prompt=["fake"],
            selected_index=0,
            mask_area_ratio=float(np.count_nonzero(mask)) / float(mask.size),
        )
        snapshot = WorkerSnapshot(
            result=result,
            timestamp_ms=100.0,
            busy=False,
            submitted=2,
            completed=1,
            dropped=1,
            error="",
        )

        overlay = compose_live_overlay(live_frame, snapshot, prompt=["fake"])

        np.testing.assert_array_equal(overlay[116, 116], live_frame[116, 116])
        self.assertFalse(np.array_equal(overlay[88, 88], live_frame[88, 88]))


if __name__ == "__main__":
    unittest.main()

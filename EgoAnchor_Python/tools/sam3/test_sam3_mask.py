"""SAM3 RealSense 工具轻量测试。"""

from __future__ import annotations

import time
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np


TOOL_DIR = Path(__file__).resolve().parent
PYTHON_DIR = TOOL_DIR.parents[1]
SRC_DIR = PYTHON_DIR / "src"
for path in (TOOL_DIR, SRC_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from egoanchor.algorithms import SegmenterResult
from sam3_mask import AsyncSam3Worker, WorkerSnapshot, compose_live_overlay, compose_mask_view


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
            selected_score=0.75,
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
            selected_score=0.82,
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


class MaskViewTest(unittest.TestCase):
    """验证 mask 调试窗口会在 mask 旁边显示检测结果分数。"""

    def test_compose_mask_view_adds_selected_score_panel_next_to_mask(self) -> None:
        """mask 视图右侧应增加信息栏，并显示当前选中 mask 的 score。"""

        mask = np.zeros((32, 48), dtype=np.uint8)
        mask[8:16, 12:24] = 255
        result = SegmenterResult(
            overlay_bgr=np.zeros((32, 48, 3), dtype=np.uint8),
            mask_bw=mask,
            det_count=1,
            infer_ms=12.0,
            prompt=["fake"],
            selected_index=0,
            selected_score=0.91,
            mask_area_ratio=float(np.count_nonzero(mask)) / float(mask.size),
        )

        view = compose_mask_view(mask, result)

        self.assertEqual(view.shape, (32, 208, 3))
        np.testing.assert_array_equal(view[12, 16], np.array([255, 255, 255], dtype=np.uint8))
        self.assertGreater(int(np.count_nonzero(view[:, 48:])), 0)

    def test_compose_mask_view_draws_selected_score_text(self) -> None:
        """信息栏应绘制模型返回的 selected_score，而不是配置阈值。"""

        result = SegmenterResult(
            overlay_bgr=np.zeros((32, 48, 3), dtype=np.uint8),
            mask_bw=np.zeros((32, 48), dtype=np.uint8),
            det_count=1,
            infer_ms=12.0,
            prompt=["fake"],
            selected_index=0,
            selected_score=0.91,
            mask_area_ratio=0.0,
        )
        drawn_text: list[str] = []

        def record_text(*args: object, **kwargs: object) -> None:
            drawn_text.append(str(args[1]))

        with patch("sam3_mask.cv2.putText", side_effect=record_text):
            compose_mask_view(result.mask_bw, result)

        self.assertIn("0.91", drawn_text)


if __name__ == "__main__":
    unittest.main()

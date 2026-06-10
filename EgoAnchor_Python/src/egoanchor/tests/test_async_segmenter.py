"""异步分割 worker 契约测试。"""

from __future__ import annotations

import time
import unittest

import numpy as np

from egoanchor.algorithms import SegmenterResult
from egoanchor.perception import AsyncSegmenterJob, AsyncSegmenterWorker, DecodedQuestStereoFrame


class _InstantSegmenter:
    """单测用分割器，立即返回固定空 mask 结果。"""

    def infer(self, image_bgr: np.ndarray, prompt: str | list[str] | None = None) -> SegmenterResult:
        """返回可区分的成功分割结果。"""

        mask = np.ones(image_bgr.shape[:2], dtype=np.uint8)
        return SegmenterResult(
            overlay_bgr=image_bgr.copy(),
            mask_bw=mask,
            det_count=1,
            infer_ms=0.0,
            prompt=["unit"],
            selected_index=0,
            mask_area_ratio=1.0,
        )


def _make_job(frame_id: int) -> AsyncSegmenterJob:
    """构造一条最小异步分割任务。"""

    image = np.zeros((2, 2, 3), dtype=np.uint8)
    decoded = DecodedQuestStereoFrame(
        frame_id=frame_id,
        sender_mono_ms=None,
        unity_frame=None,
        left_bgr=image,
        right_bgr=image,
    )
    return AsyncSegmenterJob(decoded=decoded, session_id="unit", left_bgr=image, right_bgr=image, generation=0)


class AsyncSegmenterWorkerTest(unittest.TestCase):
    """验证异步分割 worker 的 latest-only 状态语义。"""

    def test_snapshot_busy_until_completed_result_is_consumed(self) -> None:
        """已有未消费结果时 worker 不应显示为 idle，否则 HUD 会误导提交状态。"""

        worker = AsyncSegmenterWorker(_InstantSegmenter())
        worker.start()
        try:
            self.assertTrue(worker.submit(_make_job(1)))
            deadline = time.perf_counter() + 1.0
            snapshot = worker.snapshot()
            while time.perf_counter() < deadline:
                snapshot = worker.snapshot()
                if snapshot.completed > 0:
                    break
                time.sleep(0.005)

            self.assertEqual(snapshot.completed, 1)
            self.assertTrue(snapshot.busy)
            self.assertFalse(worker.submit(_make_job(2)))
            self.assertEqual(worker.snapshot().dropped, 1)
            self.assertIsNotNone(worker.take_completed())
            self.assertFalse(worker.snapshot().busy)
        finally:
            worker.stop()


if __name__ == "__main__":
    unittest.main()

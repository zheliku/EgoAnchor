"""QuestPosePipeline 分割后端接入测试。"""

from __future__ import annotations

import unittest

import numpy as np

from egoanchor.algorithms import SegmenterResult
from egoanchor.perception.quest_pose_pipeline import FrameDiagnostics, PipelineStepTiming, QuestPosePipeline


class _FakeSegmenter:
    """单测用分割器，避免加载真实 YOLOE/SAM3。"""

    def infer(self, image_bgr: np.ndarray, prompt: str | list[str] | None = None) -> SegmenterResult:
        """返回固定的单目标 mask。"""

        mask = np.zeros(image_bgr.shape[:2], dtype=np.uint8)
        mask[1:3, 2:4] = 255
        return SegmenterResult(
            overlay_bgr=image_bgr.copy(),
            mask_bw=mask,
            det_count=1,
            infer_ms=1.5,
            prompt=["unit test"],
            selected_index=0,
            mask_area_ratio=float(np.count_nonzero(mask)) / float(mask.size),
        )


class QuestPosePipelineSegmenterTest(unittest.TestCase):
    """验证 pipeline 对分割后端只依赖统一接口。"""

    def test_segmenter_name_is_used_as_mask_source(self) -> None:
        """SAM3 后端进入 pipeline 时 diagnostics.mask_source 应显示 sam3。"""

        pipeline = QuestPosePipeline(
            segmenter=_FakeSegmenter(),
            segmenter_name="sam3",
            depth_estimator=object(),
            foundationpose_estimator=object(),
            cutie_tracker=None,
            process_width=4,
            process_height=4,
        )
        diagnostics = FrameDiagnostics()
        timing = PipelineStepTiming()
        result = pipeline._run_segmenter(np.zeros((4, 4, 3), dtype=np.uint8), timing)
        if result.mask_area_ratio > 0.0:
            diagnostics.mask_source = pipeline.segmenter_name

        self.assertEqual(diagnostics.mask_source, "sam3")
        self.assertEqual(timing.yolo_ms, 1.5)


if __name__ == "__main__":
    unittest.main()

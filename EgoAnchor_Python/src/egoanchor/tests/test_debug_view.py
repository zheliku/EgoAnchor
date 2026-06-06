"""OpenCV pose HUD 诊断文本测试。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from egoanchor.diagnostics import draw_pose_hud as draw_hud, make_score_debug_view
from egoanchor.perception import FrameDiagnostics, PoseObservation


class DebugViewTest(unittest.TestCase):
    """验证 HUD 暴露真机联调需要直接看的关键分数。"""

    def test_hud_prints_depth_quality_score(self) -> None:
        """HUD 应显示 depth 子分，避免只看到最终 reliability score。"""

        image = np.zeros((120, 320, 3), dtype=np.uint8)
        diagnostics = FrameDiagnostics(depth_valid_in_mask=0.2, depth_valid_ratio=0.5)
        observation = PoseObservation(
            has_pose=True,
            phase="TRACK",
            pose_source="TRACK",
            reliability_score=0.73,
            depth_quality_score=0.65,
        )
        texts: list[str] = []

        with patch("egoanchor.diagnostics.debug_view.cv2.putText") as put_text:
            put_text.side_effect = lambda img, text, *args, **kwargs: texts.append(str(text)) or img
            draw_hud(image, observation, diagnostics)

        self.assertTrue(any("depthScore=0.65" in text for text in texts))

    def test_score_debug_view_prints_score_breakdown(self) -> None:
        """独立评分窗口应显示所有评分子分和一致性分解。"""

        diagnostics = FrameDiagnostics(
            score_phase=1.0,
            score_consistency=0.42,
            score_depth=0.65,
            score_jump=0.8,
            score_mask=0.9,
            score_reject=1.0,
            track_consistency=0.42,
            consistency_mask_iou=0.3,
            consistency_render_visible_ratio=0.5,
            consistency_depth_inlier=0.7,
            consistency_status="render_invalid",
            consistency_render_area_px=0,
            consistency_ms=4.0,
        )
        observation = PoseObservation(
            has_pose=True,
            phase="TRACK",
            pose_source="TRACK",
            reliability_score=0.2,
            reliability_flags=("consistency_low",),
        )
        texts: list[str] = []

        with patch("egoanchor.diagnostics.debug_view.cv2.putText") as put_text:
            put_text.side_effect = lambda img, text, *args, **kwargs: texts.append(str(text)) or img
            view = make_score_debug_view(diagnostics, observation, width=640, height=360)

        self.assertEqual(view.shape[:2], (360, 640))
        self.assertTrue(any("phase=1.00" in text for text in texts))
        self.assertTrue(any("cons=0.42" in text for text in texts))
        self.assertTrue(any("visible=0.50" in text for text in texts))
        self.assertTrue(any("status=render_invalid" in text for text in texts))


if __name__ == "__main__":
    unittest.main()

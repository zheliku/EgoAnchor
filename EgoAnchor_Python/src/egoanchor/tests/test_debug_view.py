"""OpenCV pose HUD 诊断文本测试。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from egoanchor.diagnostics.debug_view import draw_hud
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


if __name__ == "__main__":
    unittest.main()

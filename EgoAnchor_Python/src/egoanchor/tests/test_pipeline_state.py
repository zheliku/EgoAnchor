"""Quest pose pipeline 时序状态测试。"""

from __future__ import annotations

import unittest

import numpy as np

from egoanchor.perception import PipelineTrackingState


class PipelineTrackingStateTest(unittest.TestCase):
    """验证 reset/calibration 代数和跟踪状态清理语义。"""

    def test_bump_generation_clears_tracking_history(self) -> None:
        """进入新代时应清空所有依赖上一目标的状态。"""

        state = PipelineTrackingState(
            generation=4,
            has_registered=True,
            cutie_ready=True,
            last_pose=np.eye(4),
            frames_since_register=5,
            last_sender_mono_ms=123.0,
        )

        state.bump_generation()

        self.assertEqual(state.generation, 5)
        self.assertFalse(state.has_registered)
        self.assertFalse(state.cutie_ready)
        self.assertIsNone(state.last_pose)
        self.assertFalse(hasattr(state, "tracked_mask_lost_count"))
        self.assertFalse(hasattr(state, "low_reprojection_count"))
        self.assertEqual(state.frames_since_register, 0)
        self.assertIsNone(state.last_sender_mono_ms)

    def test_clear_registration_preserves_frame_time(self) -> None:
        """普通 track loss 应能清空注册状态，同时保留帧时间历史。"""

        state = PipelineTrackingState(
            generation=4,
            has_registered=True,
            cutie_ready=True,
            last_pose=np.eye(4),
            frames_since_register=5,
            last_sender_mono_ms=123.0,
        )

        state.clear_registration()

        self.assertEqual(state.generation, 4)
        self.assertFalse(state.has_registered)
        self.assertFalse(state.cutie_ready)
        self.assertIsNone(state.last_pose)
        self.assertFalse(hasattr(state, "tracked_mask_lost_count"))
        self.assertFalse(hasattr(state, "low_reprojection_count"))
        self.assertEqual(state.frames_since_register, 0)
        self.assertEqual(state.last_sender_mono_ms, 123.0)


if __name__ == "__main__":
    unittest.main()

"""PoseObservation 可靠性评分测试。"""

from __future__ import annotations

import unittest

from egoanchor.perception import PoseObservation
from egoanchor.reliability import score_depth_quality, score_observation_breakdown


class PoseQualityTest(unittest.TestCase):
    """验证可靠性评分不再在正常 depth/mask 下坍缩为常数 1。"""

    def test_score_uses_render_consistency_as_primary_signal(self) -> None:
        """低渲染一致性应显著降低分数并写入 consistency_low。"""

        high_score, high_flags = self._score_and_flags(self._track_observation(track_consistency=0.9))
        low_score, low_flags = self._score_and_flags(self._track_observation(track_consistency=0.3))

        self.assertGreater(high_score, 0.75)
        self.assertLess(low_score, high_score)
        self.assertLess(low_score, 0.5)
        self.assertNotIn("consistency_low", high_flags)
        self.assertIn("consistency_low", low_flags)

    def test_score_marks_missing_consistency_without_penalty(self) -> None:
        """未启用一致性检测时应标记无信号，但不额外降分。"""

        score, flags = self._score_and_flags(self._track_observation(track_consistency=-1.0))

        self.assertGreater(score, 0.85)
        self.assertIn("no_consistency_signal", flags)

    def test_score_penalizes_expected_missing_consistency(self) -> None:
        """开启一致性检测后若 TRACK 阶段仍无信号，不应继续给接近 1 的高分。"""

        score, flags = self._score_and_flags(
            self._track_observation(track_consistency=-1.0, consistency_expected=True)
        )

        self.assertLess(score, 0.75)
        self.assertIn("consistency_missing_expected", flags)

    def test_score_penalizes_depth_and_near_jump(self) -> None:
        """低 mask 内有效深度和接近跳变阈值都应让分数展开。"""

        stable_score, _ = self._score_and_flags(
            self._track_observation(track_consistency=0.9, depth_valid_in_mask=0.35)
        )
        depth_score, depth_flags = self._score_and_flags(
            self._track_observation(track_consistency=0.9, depth_valid_in_mask=0.04)
        )
        jump_score, jump_flags = self._score_and_flags(
            self._track_observation(
                track_consistency=0.9,
                last_translation_delta_m=0.45,
                last_rotation_delta_deg=75.0,
            )
        )

        self.assertLess(depth_score, stable_score)
        self.assertLess(jump_score, stable_score)
        self.assertIn("depth_in_mask_low", depth_flags)
        self.assertIn("near_jump_limit", jump_flags)

    def test_depth_quality_score_is_available_as_subscore(self) -> None:
        """深度质量子分应能独立查看，便于真机 HUD 和日志验证。"""

        low = score_depth_quality(self._track_observation(track_consistency=-1.0, depth_valid_in_mask=0.04))
        mid = score_depth_quality(self._track_observation(track_consistency=-1.0, depth_valid_in_mask=0.20))
        high = score_depth_quality(self._track_observation(track_consistency=-1.0, depth_valid_in_mask=0.35))

        self.assertLess(low, mid)
        self.assertLess(mid, high)
        self.assertAlmostEqual(high, 1.0)

    def test_score_breakdown_exposes_every_multiplier(self) -> None:
        """评分分解应暴露每个乘性子分，供 HUD 逐项显示。"""

        observation = self._track_observation(
            track_consistency=0.4,
            depth_valid_in_mask=0.2,
            last_translation_delta_m=0.12,
            last_rotation_delta_deg=10.0,
        )

        breakdown = score_observation_breakdown(observation)

        self.assertAlmostEqual(breakdown.phase_score, 1.0)
        self.assertAlmostEqual(breakdown.consistency_score, 0.4)
        self.assertGreater(breakdown.depth_score, 0.0)
        self.assertLess(breakdown.jump_score, 1.0)
        self.assertAlmostEqual(breakdown.mask_score, 1.0)
        self.assertAlmostEqual(breakdown.reject_score, 1.0)
        self.assertAlmostEqual(
            breakdown.final_score,
            breakdown.phase_score
            * breakdown.consistency_score
            * breakdown.depth_score
            * breakdown.jump_score
            * breakdown.mask_score
            * breakdown.reject_score,
        )

    @staticmethod
    def _score_and_flags(observation: PoseObservation) -> tuple[float, tuple[str, ...]]:
        """从完整评分分解中取测试关心的最终分数和 flags。"""

        breakdown = score_observation_breakdown(observation)
        return breakdown.final_score, breakdown.flags

    @staticmethod
    def _track_observation(
        *,
        track_consistency: float,
        depth_valid_in_mask: float = 0.35,
        last_translation_delta_m: float = 0.01,
        last_rotation_delta_deg: float = 2.0,
        consistency_expected: bool = False,
    ) -> PoseObservation:
        """构造 TRACK 阶段的最小评分样本。"""

        return PoseObservation(
            has_pose=True,
            phase="TRACK",
            pose_source="TRACK",
            depth_valid_ratio=0.55,
            depth_valid_in_mask=depth_valid_in_mask,
            mask_area_ratio=0.08,
            consistency_expected=consistency_expected,
            consistency_status="valid" if track_consistency >= 0.0 else "disabled",
            track_consistency=track_consistency,
            consistency_mask_iou=max(track_consistency, 0.0),
            consistency_depth_inlier=max(track_consistency, 0.0),
            last_translation_delta_m=last_translation_delta_m,
            last_rotation_delta_deg=last_rotation_delta_deg,
        )


if __name__ == "__main__":
    unittest.main()

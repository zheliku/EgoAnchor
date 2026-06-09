"""PoseObservation 可靠性评分测试。"""

from __future__ import annotations

import unittest

from egoanchor.perception import PoseObservation
from egoanchor.reliability import ConfidenceAccumulator, PoseScoreConfig, score_observation_breakdown


class PoseQualityTest(unittest.TestCase):
    """验证 Gate × Quality × Confidence 评分能让各子分承担独立职责。"""

    def test_score_uses_reprojection_as_quality_signal(self) -> None:
        """低重投影分应降低 Quality，并写入 reprojection_low。"""

        high_score, high_flags = self._score_and_flags(self._track_observation(track_reprojection=0.9))
        low_score, low_flags = self._score_and_flags(self._track_observation(track_reprojection=0.3))

        self.assertGreater(high_score, 0.75)
        self.assertLess(low_score, high_score)
        self.assertLess(low_score, 0.75)
        self.assertNotIn("reprojection_low", high_flags)
        self.assertIn("reprojection_low", low_flags)

    def test_score_marks_missing_reprojection_without_penalty_when_disabled(self) -> None:
        """未启用重投影检测时应标记无信号，但不额外把 reprojection 当故障。"""

        score, flags = self._score_and_flags(self._track_observation(track_reprojection=-1.0))

        self.assertGreater(score, 0.80)
        self.assertIn("no_reprojection_signal", flags)

    def test_score_excludes_missing_reprojection_instead_of_penalizing(self) -> None:
        """开启重投影检测但本帧无可用颜色信号（如纯色物体）时，应排除颜色项而非惩罚。"""

        excluded_score, excluded_flags = self._score_and_flags(
            self._track_observation(track_reprojection=-1.0, render_quality_expected=True)
        )
        baseline_score, _ = self._score_and_flags(
            self._track_observation(track_reprojection=-1.0, render_quality_expected=False)
        )

        self.assertAlmostEqual(excluded_score, baseline_score)
        self.assertIn("no_reprojection_signal", excluded_flags)
        self.assertNotIn("reprojection_missing_expected", excluded_flags)

    def test_effective_low_depth_pulls_down_geometry_core(self) -> None:
        """重投影高但深度有效低分时，几何合取核应把最终分拉到低档。"""

        breakdown = score_observation_breakdown(
            self._track_observation(
                track_reprojection=0.81,
                render_quality_status="valid",
                render_quality_depth_alignment=0.0,
                render_quality_depth_inlier=0.0,
                render_quality_depth_residual_m=0.048,
            )
        )

        self.assertAlmostEqual(breakdown.reprojection_score, 0.81)
        self.assertAlmostEqual(breakdown.depth_score, 0.0)
        self.assertLess(breakdown.final_score, 0.35)
        self.assertIn("depth_alignment_low", breakdown.flags)

    def test_missing_depth_signal_does_not_enter_geometry_core(self) -> None:
        """深度覆盖不足时仍显示中性 depth_score，但不参与几何核惩罚。"""

        breakdown = score_observation_breakdown(
            self._track_observation(
                track_reprojection=0.81,
                render_quality_status="render_exception",
                render_quality_depth_alignment=0.0,
                depth_valid_in_mask=0.04,
            )
        )
        accumulator = ConfidenceAccumulator()
        seeded = score_observation_breakdown(
            self._track_observation(
                track_reprojection=0.81,
                render_quality_status="render_exception",
                render_quality_depth_alignment=0.0,
                depth_valid_in_mask=0.04,
            ),
            confidence_accumulator=accumulator,
        )
        latest = breakdown
        for _ in range(4):
            latest = score_observation_breakdown(
                self._track_observation(
                    track_reprojection=-1.0,
                    render_quality_status="warmup",
                    render_quality_depth_alignment=0.0,
                    depth_valid_in_mask=0.04,
                ),
                confidence_accumulator=accumulator,
            )

        self.assertAlmostEqual(breakdown.depth_score, 0.5)
        self.assertGreater(breakdown.final_score, 0.7)
        self.assertIn("depth_coverage_insufficient", breakdown.flags)
        self.assertIn("quality_pending", latest.flags)
        self.assertAlmostEqual(latest.confidence_score, seeded.confidence_score)

    def test_depth_alignment_is_quality_signal(self) -> None:
        """depth_score 应来自渲染深度对齐，而不是 mask 内有效深度覆盖率满分。"""

        stable_score, _ = self._score_and_flags(
            self._track_observation(track_reprojection=0.9, render_quality_depth_alignment=0.9)
        )
        low_depth_score, low_depth_flags = self._score_and_flags(
            self._track_observation(track_reprojection=0.9, render_quality_depth_alignment=0.25)
        )

        self.assertLess(low_depth_score, stable_score)
        self.assertIn("depth_alignment_low", low_depth_flags)

    def test_depth_coverage_insufficient_is_neutral_depth_score(self) -> None:
        """深度覆盖不足时 depth_score 应为 0.5，而不是无信号也给满分。"""

        observation = self._track_observation(depth_valid_in_mask=0.04, render_quality_depth_alignment=0.0)
        breakdown = score_observation_breakdown(observation)

        self.assertAlmostEqual(breakdown.depth_score, 0.5)
        self.assertIn("depth_coverage_insufficient", breakdown.flags)

    def test_depth_quality_missing_render_is_neutral(self) -> None:
        """渲染深度缺失时 depth_score 应为中性值，不能用粗略 z 值伪装匹配。"""

        breakdown = score_observation_breakdown(
            self._track_observation(
                render_quality_status="render_exception",
                render_quality_depth_alignment=0.0,
                depth_median_in_mask=0.4,
            )
        )

        self.assertAlmostEqual(breakdown.depth_score, 0.5)

    def test_jump_score_uses_frame_dt_adaptive_soft_threshold(self) -> None:
        """低帧率下正常位移不应因 30fps 固定软阈值而误报 near_jump_limit。"""

        fast = score_observation_breakdown(
            self._track_observation(last_translation_delta_m=0.34, frame_dt_s=1.0 / 30.0)
        )
        slow = score_observation_breakdown(
            self._track_observation(last_translation_delta_m=0.34, frame_dt_s=0.18)
        )

        self.assertLess(fast.jump_score, slow.jump_score)
        self.assertIn("near_jump_limit", fast.flags)
        self.assertNotIn("near_jump_limit", slow.flags)

    def test_mask_score_is_smooth_gate(self) -> None:
        """没有投影面积信号时，mask 全图面积异常仍应平滑降分。"""

        tiny = score_observation_breakdown(self._track_observation(mask_area_ratio=0.001))
        small = score_observation_breakdown(self._track_observation(mask_area_ratio=0.006))
        normal = score_observation_breakdown(self._track_observation(mask_area_ratio=0.08))
        large = score_observation_breakdown(self._track_observation(mask_area_ratio=0.55))

        self.assertLess(tiny.mask_score, small.mask_score)
        self.assertLess(small.mask_score, normal.mask_score)
        self.assertLess(large.mask_score, normal.mask_score)
        self.assertIn("mask_too_small", tiny.flags)
        self.assertIn("mask_too_large", large.flags)

    def test_mask_score_uses_projected_area_ratio_without_touching_depth(self) -> None:
        """投影面积可用时，mask_score 使用 Cutie 面积/投影面积，depth 保持自己的深度匹配。"""

        breakdown = score_observation_breakdown(
            self._track_observation(
                track_reprojection=0.95,
                render_quality_depth_alignment=0.9,
                render_quality_area_ratio_score=0.25,
                render_quality_render_area_px=200,
            )
        )

        self.assertAlmostEqual(breakdown.reprojection_score, 0.95)
        self.assertAlmostEqual(breakdown.depth_score, 0.9)
        self.assertAlmostEqual(breakdown.mask_score, 0.25)
        self.assertIn("mask_visible_area_low", breakdown.flags)

    def test_confidence_accumulator_warms_up_final_score(self) -> None:
        """连续高质量帧应让 confidence 从 0.5..1.0 逐步释放最终分。"""

        accumulator = ConfidenceAccumulator()
        first = score_observation_breakdown(self._track_observation(), confidence_accumulator=accumulator)
        latest = first
        for _ in range(9):
            latest = score_observation_breakdown(self._track_observation(), confidence_accumulator=accumulator)

        self.assertAlmostEqual(first.confidence_score, 0.55)
        self.assertAlmostEqual(latest.confidence_score, 1.0)
        self.assertLess(first.final_score, latest.final_score)

    def test_warmup_frames_do_not_ramp_confidence(self) -> None:
        """无几何证据的 warmup 帧应信任 pose 但不虚攒 confidence。"""

        accumulator = ConfidenceAccumulator()
        first = score_observation_breakdown(
            self._track_observation(
                track_reprojection=-1.0,
                render_quality_status="warmup",
                depth_valid_in_mask=0.04,
                render_quality_depth_alignment=0.0,
            ),
            confidence_accumulator=accumulator,
        )
        latest = first
        for _ in range(5):
            latest = score_observation_breakdown(
                self._track_observation(
                    track_reprojection=-1.0,
                    render_quality_status="warmup",
                    depth_valid_in_mask=0.04,
                    render_quality_depth_alignment=0.0,
                ),
                confidence_accumulator=accumulator,
            )

        self.assertGreater(first.final_score, 0.45)
        self.assertAlmostEqual(first.confidence_score, 0.5)
        self.assertAlmostEqual(latest.confidence_score, 0.5)
        self.assertIn("quality_pending", latest.flags)

    def test_both_weights_zero_falls_back(self) -> None:
        """重投影和深度权重都清零时，应回退 0.5/0.5 避免几何核无效。"""

        config = PoseScoreConfig(reproj_weight=0.0, depth_weight=0.0)

        self.assertAlmostEqual(config.reproj_weight, 0.5)
        self.assertAlmostEqual(config.depth_weight, 0.5)

    def test_score_breakdown_exposes_gate_quality_confidence_formula(self) -> None:
        """评分分解应暴露 Gate、Quality 和 Confidence，供 HUD 逐项显示。"""

        accumulator = ConfidenceAccumulator()
        observation = self._track_observation(
            track_reprojection=0.4,
            render_quality_depth_alignment=0.6,
            last_translation_delta_m=0.12,
            last_rotation_delta_deg=10.0,
        )

        breakdown = score_observation_breakdown(observation, confidence_accumulator=accumulator)

        self.assertAlmostEqual(breakdown.phase_score, 1.0)
        self.assertAlmostEqual(breakdown.reprojection_score, 0.4)
        self.assertGreater(breakdown.depth_score, 0.0)
        self.assertLess(breakdown.jump_score, 1.0)
        self.assertAlmostEqual(breakdown.mask_score, 1.0)
        self.assertAlmostEqual(breakdown.reject_score, 1.0)
        self.assertAlmostEqual(
            breakdown.final_score,
            breakdown.gate_score * breakdown.quality_score * breakdown.confidence_score,
        )

    @staticmethod
    def _score_and_flags(observation: PoseObservation) -> tuple[float, tuple[str, ...]]:
        """从完整评分分解中取测试关心的最终分数和 flags。"""

        breakdown = score_observation_breakdown(observation)
        return breakdown.final_score, breakdown.flags

    @staticmethod
    def _track_observation(
        *,
        track_reprojection: float = 0.9,
        render_quality_depth_alignment: float = 0.85,
        render_quality_status: str = "valid",
        depth_valid_in_mask: float = 0.35,
        depth_median_in_mask: float = 0.5,
        mask_area_ratio: float = 0.08,
        last_translation_delta_m: float = 0.01,
        last_rotation_delta_deg: float = 2.0,
        frame_dt_s: float = 1.0 / 30.0,
        render_quality_expected: bool = False,
        render_quality_area_ratio_score: float = 1.0,
        render_quality_render_area_px: int = 0,
        render_quality_depth_inlier: float | None = None,
        render_quality_depth_residual_m: float = 0.0,
    ) -> PoseObservation:
        """构造 TRACK 阶段的最小评分样本。"""

        return PoseObservation(
            has_pose=True,
            phase="TRACK",
            pose_matrix_cv_camera=(
                1.0,
                0.0,
                0.0,
                0.0,
                0.0,
                1.0,
                0.0,
                0.0,
                0.0,
                0.0,
                1.0,
                0.5,
                0.0,
                0.0,
                0.0,
                1.0,
            ),
            pose_source="TRACK",
            depth_valid_ratio=0.55,
            depth_valid_in_mask=depth_valid_in_mask,
            depth_median_in_mask=depth_median_in_mask,
            mask_area_ratio=mask_area_ratio,
            render_quality_expected=render_quality_expected,
            render_quality_status=render_quality_status,
            track_reprojection=track_reprojection,
            render_quality_mask_iou=max(track_reprojection, 0.0),
            render_quality_depth_inlier=render_quality_depth_inlier
            if render_quality_depth_inlier is not None
            else max(render_quality_depth_alignment, 0.0),
            render_quality_depth_alignment=render_quality_depth_alignment,
            render_quality_area_ratio_score=render_quality_area_ratio_score,
            render_quality_render_area_px=render_quality_render_area_px,
            render_quality_depth_residual_m=render_quality_depth_residual_m,
            last_translation_delta_m=last_translation_delta_m,
            last_rotation_delta_deg=last_rotation_delta_deg,
            frame_dt_s=frame_dt_s,
        )


if __name__ == "__main__":
    unittest.main()
